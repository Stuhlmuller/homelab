#!/usr/bin/env python3
"""Failure boundaries of checked SQLite snapshots; no running Kuma required."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import tracemalloc
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("backup", ROOT / "clusters/homelab/apps/uptime-kuma/backup.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


class Backups(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.dest = self.root / "backups"
        self.catalog = self.root / "catalog"
        self.catalog.write_text("{}")
        (self.source / "db-config.json").write_text('{"type":"sqlite"}')
        self.db = sqlite3.connect(self.source / "kuma.db")
        self.db.executescript(
            "PRAGMA journal_mode=WAL; CREATE TABLE monitor(id INTEGER); CREATE TABLE heartbeat(id INTEGER); INSERT INTO monitor VALUES(7); INSERT INTO heartbeat VALUES(1);"
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def snapshot(self):
        return B.snapshot(self.source, self.dest, self.catalog)

    def bundle(self):
        return sorted(self.dest.glob("snapshot-*"))[-1]

    def rewrite(self, entries):
        p = self.bundle() / "data.tar.gz"
        with tarfile.open(p, "w:gz") as tar:
            for name, kind, data in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = len(data) if kind == tarfile.REGTYPE else 0
                if kind == tarfile.SYMTYPE:
                    info.linkname = "/tmp/escape"
                tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        m = self.bundle() / "manifest.json"
        d = json.loads(m.read_text())
        d["sha256"] = B.digest(p)
        m.write_text(json.dumps(d))

    def test_live_wal_snapshot_and_restore_preserve_history(self):
        self.assertTrue((self.source / "kuma.db-wal").exists())
        self.snapshot()
        restored = self.root / "restore"
        m = B.restore(self.dest, restored)
        self.assertEqual(m["monitorIds"], [7])
        self.assertEqual(B.summary(restored / "kuma.db")["heartbeats"], 1)

    def test_concurrent_wal_writes_keep_snapshot_consistent(self):
        self.db.execute("CREATE TABLE payload(value BLOB)")
        self.db.executemany("INSERT INTO payload VALUES(?)", [(b"x" * 512,)] * 10000)
        self.db.commit()
        source_db = self.source / "kuma.db"
        first_batch = threading.Event()
        connect = sqlite3.connect

        def write_after_first_batch():
            if not first_batch.wait(10):
                raise AssertionError("backup did not copy a partial batch")
            with closing(connect(source_db)) as connection:
                connection.execute("INSERT INTO heartbeat VALUES(2)")
                connection.commit()

        class ObservedReader(sqlite3.Connection):
            def backup(self, target, *, progress, **options):
                def interleave_write(status, remaining, total):
                    if status == sqlite3.SQLITE_OK and remaining and not first_batch.is_set():
                        # Commit between sqlite3_backup_step calls, then let the copy finish.
                        first_batch.set()
                        writer.result(timeout=10)
                    progress(status, remaining, total)

                return super().backup(target, progress=interleave_write, **options)

        def connect_with_probe(database, *args, **kwargs):
            if database == f"file:{source_db}?mode=ro":
                kwargs["factory"] = ObservedReader
            return connect(database, *args, **kwargs)

        with ThreadPoolExecutor(max_workers=1) as pool:
            writer = pool.submit(write_after_first_batch)
            with patch.object(B.sqlite3, "connect", side_effect=connect_with_probe):
                result = self.snapshot()
            writer.result(timeout=10)

        self.assertEqual(result["heartbeats"], 1)
        self.assertEqual(self.db.execute("SELECT id FROM heartbeat ORDER BY id").fetchall(), [(1,), (2,)])
        restored = self.root / "restore"
        B.restore(self.dest, restored)
        with closing(connect(restored / "kuma.db")) as database:
            self.assertEqual(database.execute("SELECT id FROM heartbeat ORDER BY id").fetchall(), [(1,)])
            self.assertEqual(
                database.execute("SELECT count(*) FROM payload WHERE value = ?", (b"x" * 512,)).fetchone()[0],
                10000,
            )
            self.assertEqual(database.execute("SELECT count(*) FROM payload").fetchone()[0], 10000)

    def test_wal_snapshot_keeps_progress_when_every_step_sees_a_commit(self):
        self.db.executescript(
            "CREATE TABLE payload(value BLOB); INSERT INTO payload VALUES(zeroblob(5000000));"
        )
        connect = sqlite3.connect
        live = self.db
        pages_left = []

        class CommittingReader(sqlite3.Connection):
            def backup(self, target, *, progress, **kwargs):
                def commit_after_step(status, remaining, total):
                    pages_left.append(remaining)
                    progress(status, remaining, total)
                    if remaining:
                        live.execute("INSERT INTO heartbeat VALUES(2)")
                        live.commit()

                return super().backup(target, progress=commit_after_step, **kwargs)

        def connect_with_writer(path, *args, **kwargs):
            if str(path).endswith("?mode=ro"):
                kwargs["factory"] = CommittingReader
            return connect(path, *args, **kwargs)

        # A fake clock bounds the failure if copying restarts on every commit.
        with patch.object(B.sqlite3, "connect", side_effect=connect_with_writer):
            with patch.object(B, "time") as clock:
                clock.monotonic.side_effect = lambda: len(pages_left) * 10
                result = self.snapshot()
        self.assertGreater(len(pages_left), 2)
        self.assertEqual(pages_left, sorted(set(pages_left), reverse=True))
        self.assertEqual(pages_left[-1], 0)
        self.assertEqual(result["heartbeats"], 1)
        self.assertEqual(
            live.execute("SELECT count(*) FROM heartbeat").fetchone()[0], len(pages_left)
        )
        restored = B.restore(self.dest, self.root / "restored")
        self.assertEqual(restored["heartbeats"], 1)

    def test_snapshot_timeout_releases_wal_reader_and_cleans_staging(self):
        self.snapshot()
        before = list(self.dest.iterdir())
        scratch = self.root / "scratch"
        scratch.mkdir()
        with patch.object(B, "time") as clock:
            clock.monotonic.side_effect = [0, 121]
            with self.assertRaisesRegex(TimeoutError, "snapshot-timeout"):
                B.snapshot(self.source, self.dest, self.catalog, scratch_directory=scratch)
        self.assertEqual(list(self.dest.iterdir()), before)
        self.assertEqual(list(scratch.iterdir()), [])
        self.db.execute("INSERT INTO heartbeat VALUES(2)")
        self.db.commit()
        self.assertEqual(self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone(), (0, 0, 0))
        self.assertEqual(self.snapshot()["heartbeats"], 2)

    def test_partial_catalog_configuration_not_published(self):
        self.db.execute("ALTER TABLE monitor ADD COLUMN description TEXT")
        self.db.commit()
        self.catalog.write_text('{"monitors":[{"key":"missing"}]}')
        with self.assertRaisesRegex(ValueError, "history-not-ready"):
            self.snapshot()
        self.assertFalse(list(self.dest.glob("snapshot-*")))

    def test_empty_history_never_published(self):
        self.db.execute("DELETE FROM heartbeat")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "history-not-ready"):
            self.snapshot()
        self.assertFalse(list(self.dest.glob("snapshot-*")))

    def test_failed_publish_preserves_previous_good_bundle(self):
        self.snapshot()
        before = list(self.dest.iterdir())
        with patch.object(B.os, "rename", side_effect=OSError("publication unavailable")):
            with self.assertRaises(OSError):
                self.snapshot()
        self.assertEqual(list(self.dest.iterdir()), before)

    def test_secret_files_are_not_archived(self):
        (self.source / "secret").mkdir()
        (self.source / "secret/password").write_text("never archive")
        self.snapshot()
        with tarfile.open(self.bundle() / "data.tar.gz") as tar:
            self.assertEqual(set(tar.getnames()), {"kuma.db", "db-config.json"})

    def test_corrupt_checksum_is_rejected(self):
        self.snapshot()
        (self.bundle() / "data.tar.gz").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "invalid-backup"):
            B.restore(self.dest, self.root / "restore")

    def test_traversal_absolute_symlink_and_duplicate_members_rejected(self):
        for name, kind in [
            ("../escape", tarfile.REGTYPE),
            ("/tmp/escape", tarfile.REGTYPE),
            ("upload/link", tarfile.SYMTYPE),
        ]:
            with self.subTest(name=name):
                self.snapshot()
                self.rewrite([(name, kind, b"x")])
                with self.assertRaisesRegex(ValueError, "unsafe-archive"):
                    B.restore(self.dest, self.root / "restore")
                self.assertFalse((self.root / "restore").exists())
        self.snapshot()
        self.rewrite([("kuma.db", tarfile.REGTYPE, b"x")] * 2)
        with self.assertRaises(ValueError):
            B.restore(self.dest, self.root / "restore")

    def test_incomplete_archive_rejected(self):
        self.snapshot()
        self.rewrite([("db-config.json", tarfile.REGTYPE, b'{"type":"sqlite"}')])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            B.restore(self.dest, self.root / "restore")

    def test_source_symlink_rejected(self):
        (self.source / "upload").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "unsafe-upload"):
            self.snapshot()

    def test_restore_never_overwrites_existing_data(self):
        self.snapshot()
        dest = self.root / "restore"
        dest.mkdir()
        (dest / "keep").write_text("keep")
        with self.assertRaisesRegex(ValueError, "not-empty"):
            B.restore(self.dest, dest)
        self.assertEqual((dest / "keep").read_text(), "keep")

    def test_verify_failure_never_deletes_preexisting_destination(self):
        self.snapshot()
        dest = self.root / "restore"
        dest.mkdir()
        (dest / "keep").write_text("keep")
        with patch.object(B.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "not-empty"):
                B.verify(self.dest, dest, "unused")
            spawn.assert_not_called()
        self.assertEqual((dest / "keep").read_text(), "keep")

    def test_retention_keeps_fourteen_complete_bundles(self):
        for _ in range(16):
            self.snapshot()
        self.assertEqual(len(list(self.dest.glob("snapshot-*"))), 14)
        self.assertFalse(list(self.dest.glob(".pending-*")))


class Fence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "kuma.db"
        c = sqlite3.connect(self.db)
        c.executescript("""CREATE TABLE monitor(id INTEGER,active BOOLEAN,user_id INTEGER,url TEXT);
CREATE TABLE notification(id INTEGER,active BOOLEAN,is_default BOOLEAN,user_id INTEGER,config TEXT);
CREATE TABLE maintenance(id INTEGER,active BOOLEAN,title TEXT);
CREATE TABLE monitor_notification(id INTEGER,monitor_id INTEGER,notification_id INTEGER);
CREATE TABLE setting(id INTEGER PRIMARY KEY,key VARCHAR(200),value TEXT,type VARCHAR(20));
CREATE TABLE user(id INTEGER,password TEXT);CREATE TABLE heartbeat(id INTEGER,time TEXT);
INSERT INTO monitor VALUES(7,1,1,'http://reachable.fixture');
INSERT INTO notification VALUES(4,1,1,1,'private-definition');
INSERT INTO maintenance VALUES(3,1,'keep');INSERT INTO monitor_notification VALUES(1,7,4);
INSERT INTO user VALUES(1,'private-hash');INSERT INTO heartbeat VALUES(1,'keep-history');
INSERT INTO setting(key,value,type) VALUES('jwtSecret','"private-token"','general');""")
        c.commit()
        self.schema = B.hash_value(B.schema_shape(c))
        c.close()
        self.pin = patch.object(B, "PINNED_SCHEMA", self.schema)
        self.pin.start()

    def tearDown(self):
        self.pin.stop()
        self.temp.cleanup()

    def execute(self, sql, args=()):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute(sql, args)

    def assert_invalid(self, evidence):
        with closing(sqlite3.connect(self.db)) as c, c:
            with self.assertRaises(ValueError):
                B.assert_fence(c, evidence)

    def test_large_history_evidence_streams_with_bounded_python_memory(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.executemany("INSERT INTO heartbeat VALUES(?,?)", ((i, "x" * 512) for i in range(2, 50002)))
        tracemalloc.start()
        try:
            with closing(sqlite3.connect(self.db)) as connection, connection:
                result = B.private_evidence(connection)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(result["heartbeat"]["rows"], 50001)
        self.assertLess(peak, 2 * 1024 * 1024)

    def test_transaction_preserves_private_evidence(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            before = B.private_evidence(c)
        result = B.fence_clone(self.root)
        self.assertEqual(result, before)
        with closing(sqlite3.connect(self.db)) as c, c:
            B.assert_fence(c, before)

    def test_unknown_schema_and_duplicate_keys_fail_before_spawn(self):
        for sql in [
            "ALTER TABLE monitor ADD COLUMN unexpected TEXT",
            "INSERT INTO setting(key,value) VALUES('jwtSecret','false')",
        ]:
            with self.subTest(sql=sql):
                # Each mutation is independently rolled back by restoring the database bytes.
                original = self.db.read_bytes()
                self.execute(sql)
                with patch.object(B, "restore", return_value={}), patch.object(B.subprocess, "Popen") as spawn:
                    with self.assertRaises(ValueError):
                        B.verify("unused", self.root, "unused")
                    spawn.assert_not_called()
                self.root.mkdir(exist_ok=True)
                self.db.write_bytes(original)

    def test_every_activation_and_binding_postcondition_is_independent(self):
        evidence = B.fence_clone(self.root)
        cases = [
            (table, flag)
            for table, flags in [
                ("monitor", ["active"]),
                ("notification", ["active", "is_default"]),
                ("maintenance", ["active"]),
            ]
            for flag in flags
        ]
        for table, flag in cases:
            for value in (1, None):
                with self.subTest(table=table, flag=flag, value=value):
                    self.execute(f"UPDATE {table} SET {flag}=?", (value,))
                    self.assert_invalid(evidence)
                    self.execute(f"UPDATE {table} SET {flag}=0")
        self.execute("INSERT INTO monitor_notification VALUES(1,7,4)")
        self.assert_invalid(evidence)

    def test_each_setting_missing_wrong_type_duplicate_fails(self):
        evidence = B.fence_clone(self.root)
        for key, expected in B.FENCED_SETTINGS.items():
            for wrong in ("null", "true", "0", '"false"'):
                self.execute("UPDATE setting SET value=? WHERE key=?", (wrong, key))
                self.assert_invalid(evidence)
            self.execute("DELETE FROM setting WHERE key=?", (key,))
            self.assert_invalid(evidence)
            self.execute("INSERT INTO setting(key,value,type) VALUES(?,?,?)", (key, json.dumps(expected), "general"))
            self.execute("INSERT INTO setting(key,value,type) VALUES(?,?,?)", (key, json.dumps(expected), "general"))
            self.assert_invalid(evidence)
            self.execute("DELETE FROM setting WHERE id=(SELECT max(id) FROM setting WHERE key=?)", (key,))

    def test_identity_or_history_changes_detected(self):
        evidence = B.fence_clone(self.root)
        self.execute("UPDATE user SET password='changed'")
        self.assert_invalid(evidence)

    def test_verification_discards_only_new_clone_on_success_and_failure(self):
        for error in (None, ValueError("fence-failed")):
            self.root.mkdir(exist_ok=True)
            self.db.write_text("disposable")
            with (
                patch.object(B, "restore", return_value={"verified": "fixture"}),
                patch.object(B, "_verify_clone", return_value={"ok": True}, side_effect=error),
            ):
                if error:
                    with self.assertRaises(ValueError):
                        B.verify("untouched-archive", self.root, "unused")
                else:
                    self.assertEqual(B.verify("untouched-archive", self.root, "unused"), {"ok": True})
                self.assertFalse(self.root.exists())

    def test_spawn_boundary_revalidates_fence_and_never_inherits_environment(self):
        original = B.fence_clone

        def corrupt(path):
            evidence = original(path)
            self.execute("UPDATE monitor SET active=1")
            return evidence

        with (
            patch.object(B, "restore", return_value={}),
            patch.object(B, "fence_clone", side_effect=corrupt),
            patch.object(B.subprocess, "Popen") as spawn,
        ):
            with self.assertRaises(ValueError):
                B.verify("unused", self.root, "unused")
            spawn.assert_not_called()
        self.assertEqual(set(B.CHILD_ENV), {"PATH", "HOME", "TMPDIR"})
        for key in ["NODE_OPTIONS", "HTTP_PROXY", "HTTPS_PROXY", "UPTIME_KUMA_PORT", "CLOUDFLARED_TOKEN"]:
            self.assertNotIn(key, B.CHILD_ENV)


class RestoreManifest(unittest.TestCase):
    def test_dedicated_identity_and_ephemeral_clone_only(self):
        app = ROOT / "clusters/homelab/apps/uptime-kuma"

        def read(name):
            return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(app / name)], text=True))

        job = read("restore-verification-job.yaml")["spec"]["template"]["spec"]
        account = read("restore-serviceaccount.yaml")
        self.assertEqual(job["serviceAccountName"], "uptime-kuma-restore")
        self.assertFalse(job["automountServiceAccountToken"])
        self.assertFalse(account["automountServiceAccountToken"])
        self.assertEqual(account["metadata"]["name"], job["serviceAccountName"])
        self.assertEqual(
            [v["persistentVolumeClaim"]["claimName"] for v in job["volumes"] if "persistentVolumeClaim" in v],
            ["uptime-kuma-backups"],
        )
        self.assertTrue(next(v for v in job["volumes"] if v["name"] == "restore")["emptyDir"])
        container = job["containers"][0]
        self.assertNotIn("env", container)
        self.assertNotIn("envFrom", container)
        self.assertEqual(
            container["command"],
            [
                "python3",
                "/backup-code/backup.py",
                "verify",
                "--source",
                "/backups/snapshots",
                "--destination",
                "/restore/data",
                "--password-file",
                "/secret/admin-password",
            ],
        )
        for mount in container["volumeMounts"]:
            if mount["name"] in {"code", "config", "backups", "secret"}:
                self.assertTrue(mount["readOnly"])
        for path in (ROOT / "clusters").rglob("*.yaml"):
            if path.name not in {"restore-serviceaccount.yaml", "restore-verification-job.yaml", "kustomization.yaml"}:
                text = path.read_text()
                self.assertNotIn("cluster.local/ns/monitoring/sa/uptime-kuma-restore", text)
                if "kind: RoleBinding" in text or "kind: ClusterRoleBinding" in text:
                    self.assertNotIn("uptime-kuma-restore", text)


if __name__ == "__main__":
    unittest.main()
