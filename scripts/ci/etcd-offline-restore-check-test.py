#!/usr/bin/env python3
"""Exercise offline restore decisions with synthetic bytes and a fake client."""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


script = Path(__file__).resolve().parents[1] / "etcd-offline-restore-check.py"
spec = importlib.util.spec_from_file_location("offline_restore", script)
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class RestoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.destination = self.root / "checks"
        self.source.mkdir(mode=0o700)
        self.destination.mkdir(mode=0o700)
        payload = b"synthetic bytes; not an etcd database".ljust(4096, b"\0")
        self.snapshot = self.source / restore.backup.SNAPSHOT
        self.snapshot.write_bytes(payload + hashlib.sha256(payload).digest())
        self.snapshot.chmod(0o600)
        self.record = {"format": 1, "snapshot": restore.backup.SNAPSHOT,
                       "metadata": {"hash": "0123abcd", "revision": 42,
                                    "total_keys": 7, "total_size": 4096},
                       "integrity": restore.backup.snapshot_digest(self.snapshot)}
        manifest = self.source / restore.backup.MANIFEST
        manifest.write_text(json.dumps(self.record))
        manifest.chmod(0o600)
        self.archive = self.root / "release.zip"
        with zipfile.ZipFile(self.archive, "w") as package:
            package.writestr("etcd-v3.6.5-darwin-arm64/etcdutl", b"synthetic client")
            package.writestr("etcd-v3.6.5-darwin-arm64/etcd", b"never extract server")
            package.writestr("../../outside", b"never extract arbitrary members")
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        for context in (patch.dict(restore.ARCHIVES, {"darwin-arm64": digest}),
                        patch.object(restore.platform, "system", return_value="Darwin"),
                        patch.object(restore.platform, "machine", return_value="arm64")):
            context.start()
            self.addCleanup(context.stop)
        self.commands = []
        self.restored_revision = 42
        self.restored_keys = 7

    def client(self, command, **kwargs):
        self.commands.append(command)
        cwd = kwargs["cwd"]
        self.assertEqual(command[0], str(cwd / "etcdutl"))
        self.assertEqual(kwargs["env"], {})
        self.assertEqual(kwargs["timeout"], 300)
        self.assertTrue(kwargs["check"])
        self.assertTrue(kwargs["capture_output"])
        if command[1:] == ["version"]:
            output = "etcdutl version: 3.6.5\nAPI version: 3.6\n"
        elif command[1:3] == ["snapshot", "status"]:
            self.assertEqual(command[4:], ["--write-out=json"])
            path = Path(command[3])
            self.assertTrue(path.is_file())
            restored = path.name == "db"
            output = json.dumps({"hash": 0x123abce if restored else 0x123abcd,
                                 "revision": self.restored_revision if restored else 42,
                                 "totalKey": self.restored_keys if restored else 7,
                                 "totalSize": 8192 if restored else 4096,
                                 "version": "3.6.0"})
        elif command[1:3] == ["snapshot", "restore"]:
            self.assertEqual(command[3:], [
                str(cwd / "snapshot.db"), "--data-dir", str(cwd / "restored"),
                "--name", "offline-validation", "--initial-cluster",
                "offline-validation=http://127.0.0.1:2380",
                "--initial-advertise-peer-urls", "http://127.0.0.1:2380",
                "--initial-cluster-token", "offline-validation",
            ])
            db = cwd / "restored/member/snap/db"
            db.parent.mkdir(parents=True)
            db.write_bytes(b"synthetic restored database")
            wal = cwd / "restored/member/wal"
            wal.mkdir()
            (wal / "synthetic.wal").write_bytes(b"synthetic wal")
            output = "client diagnostics withheld"
        else:
            self.fail(f"unexpected client operation {command[1:3]}")
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    def check(self):
        return restore.restore_check(self.source, self.destination, self.archive)

    def test_success_preserves_source_and_only_runs_offline_commands(self):
        original = self.snapshot.read_bytes()
        with patch.object(restore.subprocess, "run", side_effect=self.client):
            first, receipt = self.check()
            second, _ = self.check()
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.commands), 8)
        self.assertEqual(self.snapshot.read_bytes(), original)
        self.assertEqual(restore.backup.verify(self.source), self.record)
        self.assertTrue(receipt["restore_checksum_enabled"])
        self.assertFalse(receipt["server_started"])
        self.assertFalse(receipt["control_plane_recovery_tested"])
        self.assertNotEqual(receipt["snapshot_status"]["hash"], receipt["restored_status"]["hash"])
        self.assertEqual(receipt["restored_status"]["revision"], 42)
        self.assertFalse((self.root / "outside").exists())
        for path in first.rglob("*"):
            self.assertNotEqual(path.name, "etcd")
            self.assertEqual(path.stat().st_mode & 0o777,
                             0o700 if path.is_dir() or path.name == "etcdutl" else 0o600)
        self.assertEqual(first.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads((first / "receipt.json").read_text()), receipt)

    def test_bad_archive_or_snapshot_fails_before_client_and_preserves_prior_output(self):
        prior = self.destination / "existing"
        prior.mkdir(mode=0o700)
        with patch.object(restore.subprocess, "run") as client:
            with patch.dict(restore.ARCHIVES, {"darwin-arm64": "0" * 64}):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    self.check()
            self.snapshot.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                self.check()
        client.assert_not_called()
        self.assertEqual(list(self.destination.iterdir()), [prior])

    def test_linux_archive_extracts_only_exact_regular_client_member(self):
        archive = self.root / "release.tar.gz"
        with tarfile.open(archive, "w:gz") as package:
            member = tarfile.TarInfo("etcd-v3.6.5-linux-amd64/etcdutl")
            contents = b"synthetic linux client"
            member.size = len(contents)
            package.addfile(member, io.BytesIO(contents))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with patch.object(restore.platform, "system", return_value="Linux"):
            with patch.object(restore.platform, "machine", return_value="x86_64"):
                with patch.dict(restore.ARCHIVES, {"linux-amd64": digest}):
                    binary, provenance = restore.release_archive(archive)
        self.assertEqual(binary, contents)
        self.assertEqual(provenance["platform"], "linux-amd64")

    def test_unsupported_host_and_relative_archive_fail_before_client(self):
        with patch.object(restore.subprocess, "run") as client:
            with patch.object(restore.platform, "system", return_value="Windows"):
                with self.assertRaisesRegex(ValueError, "supported operator"):
                    self.check()
            with self.assertRaisesRegex(ValueError, "absolute"):
                restore.restore_check(self.source, self.destination, Path("release.zip"))
        client.assert_not_called()

    def test_private_outside_git_and_source_destination_required(self):
        with patch.object(restore.subprocess, "run") as client:
            self.destination.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "0700"):
                self.check()
            self.destination.chmod(0o700)
            with self.assertRaisesRegex(ValueError, "outside the source"):
                restore.restore_check(self.source, self.source, self.archive)
            (self.root / ".git").touch()
            with self.assertRaisesRegex(ValueError, "Git"):
                self.check()
        client.assert_not_called()

    def test_incorrect_version_rejects_before_opening_snapshot(self):
        result = subprocess.CompletedProcess([], 0, stdout="etcdutl version: 3.6.6\n")
        with patch.object(restore.subprocess, "run", return_value=result) as client:
            with self.assertRaisesRegex(ValueError, "version"):
                self.check()
        self.assertEqual(client.call_count, 1)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_metadata_disagreement_never_publishes(self):
        for field in ("restored_revision", "restored_keys"):
            with self.subTest(field=field):
                prior = getattr(self, field)
                setattr(self, field, prior + 1)
                with patch.object(restore.subprocess, "run", side_effect=self.client):
                    with self.assertRaisesRegex(ValueError, "revision or key count"):
                        self.check()
                self.assertEqual(list(self.destination.iterdir()), [])
                setattr(self, field, prior)
        self.record["metadata"]["revision"] = 99
        (self.source / restore.backup.MANIFEST).write_text(json.dumps(self.record))
        with patch.object(restore.subprocess, "run", side_effect=self.client):
            with self.assertRaisesRegex(ValueError, "manifest"):
                self.check()
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_restore_failure_timeout_and_parser_error_remove_only_this_attempt(self):
        prior = self.destination / "existing"
        prior.mkdir(mode=0o700)
        for error in (subprocess.CalledProcessError(1, "etcdutl"),
                      subprocess.TimeoutExpired("etcdutl", 300),
                      ValueError("malformed database metadata")):
            with self.subTest(error=type(error).__name__):
                def fail_restore(command, **kwargs):
                    if command[1:3] == ["snapshot", "restore"]:
                        raise error
                    return self.client(command, **kwargs)
                with patch.object(restore.subprocess, "run", side_effect=fail_restore):
                    with self.assertRaises(type(error)):
                        self.check()
                self.assertEqual(list(self.destination.iterdir()), [prior])
                restore.backup.verify(self.source)

    def test_source_change_during_restore_is_detected(self):
        def change_source(command, **kwargs):
            result = self.client(command, **kwargs)
            if command[1:3] == ["snapshot", "restore"]:
                self.snapshot.write_bytes(b"concurrently changed")
            return result
        with patch.object(restore.subprocess, "run", side_effect=change_source):
            with self.assertRaises(ValueError):
                self.check()
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_client_errors_never_print_database_diagnostics(self):
        args = [str(script), "--backup-directory", str(self.source),
                "--destination", str(self.destination), "--etcd-archive", str(self.archive)]
        error = subprocess.CalledProcessError(1, "etcdutl", output="PRIVATE_KEY_DATA",
                                             stderr="PRIVATE_KEY_DATA")
        output = io.StringIO()
        with patch.object(restore.sys, "argv", args), redirect_stderr(output):
            with patch.object(restore.subprocess, "run", side_effect=error):
                self.assertEqual(restore.main(), 1)
        self.assertNotIn("PRIVATE_KEY_DATA", output.getvalue())

    def test_status_rejects_invalid_or_empty_numeric_metadata(self):
        for metadata in ({}, [], {"hash": False, "revision": 1, "totalKey": 1, "totalSize": 1},
                         {"hash": -1, "revision": 1, "totalKey": 1, "totalSize": 1},
                         {"hash": 1, "revision": 0, "totalKey": 1, "totalSize": 1}):
            with self.subTest(metadata=metadata):
                with patch.object(restore, "run_tool", return_value=json.dumps(metadata)):
                    with self.assertRaises(ValueError):
                        restore.snapshot_status(Path("unused"), Path("unused"), self.root)

    def test_publication_sync_failure_does_not_report_success(self):
        for failure_index in (0, 1):
            with self.subTest(failure_index=failure_index):
                calls = [None, None]
                calls[failure_index] = OSError("sync failed")
                with patch.object(restore.subprocess, "run", side_effect=self.client):
                    with patch.object(restore.backup, "sync_directory", side_effect=calls):
                        with self.assertRaises(OSError):
                            self.check()
                self.assertEqual(len(list(self.destination.iterdir())), failure_index)
                restore.backup.verify(self.source)


if __name__ == "__main__":
    unittest.main()
