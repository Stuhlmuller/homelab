#!/usr/bin/env python3
"""Exercise private publication and fail-closed Multica backup checks offline."""

import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("multica_backup", ROOT / "scripts/multica-upgrade-backup.py")
BACKUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKUP)


def archive_bytes(data=b"upload contents", name="./upload.txt", symlink=False):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w") as archive:
        entry = tarfile.TarInfo(name)
        entry.size = len(data)
        if symlink:
            entry.type = tarfile.SYMTYPE
            entry.linkname = "outside"
            entry.size = 0
        archive.addfile(entry, io.BytesIO(data))
    return result.getvalue()


class FakeCluster:
    def __init__(self, changed_upload=False, changed_state=False, changed_pod=False,
                 reject_dump=False):
        self.changed_upload = changed_upload
        self.changed_state = changed_state
        self.changed_pod = changed_pod
        self.reject_dump = reject_dump
        self.tar_calls = self.state_calls = self.source_calls = 0
        self.restore_calls = []
        self.archive_timeouts = []

    def json(self, args):
        return {"clusters": [{"cluster": {"server": BACKUP.API_SERVER}}]}

    def sources(self):
        self.source_calls += 1
        suffix = "new" if self.changed_pod and self.source_calls > 1 else "original"
        return {name: {"name": name, "uid": suffix}
                for name in ("postgres", "backend", "runtime")}

    def state(self, postgres):
        self.state_calls += 1
        return {"active_tasks": 0, "attachment_hash":
                "changed" if self.changed_state and self.state_calls > 1 else "original"}

    def execute(self, pod, container, args, **kwargs):
        self.archive_timeouts.append(kwargs.get("timeout"))
        if args[0] == "tar":
            self.tar_calls += 1
            data = b"changed" if self.changed_upload and self.tar_calls > 1 else b"original"
            kwargs["stdout"].write(archive_bytes(data))
        elif args[0] == "pg_dump":
            kwargs["stdout"].write(b"PGDMP fixture")
        elif args[0] == "pg_restore":
            self.restore_calls.append(args[1:])
            if self.reject_dump:
                raise subprocess.CalledProcessError(1, args)
            assert kwargs["stdin"].read() == b"PGDMP fixture"
        else:
            raise AssertionError(f"unexpected command: {args[0]}")


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.destination = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def capture(self, cluster):
        with patch.object(BACKUP, "Cluster", return_value=cluster):
            return BACKUP.backup(self.destination, "kubectl", "test-context")

    def test_private_capture_and_offline_corruption_detection(self):
        cluster = FakeCluster()
        directory, record = self.capture(cluster)
        self.assertEqual(record["consistency"], "online-stable-uploads")
        self.assertEqual(BACKUP.verify(directory), record)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual({path.name for path in directory.iterdir()},
                         {"manifest.json", "multica.dump", "uploads.tar"})
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in directory.iterdir()))
        self.assertEqual(cluster.restore_calls,
                         [["--list"], ["--exit-on-error", "--file=/dev/null"]])
        self.assertEqual(cluster.archive_timeouts, [3600] * 5)
        with (directory / "multica.dump").open("ab") as output:
            output.write(b"corruption")
        with self.assertRaises(ValueError):
            BACKUP.verify(directory)

    def test_changed_sources_and_invalid_dump_never_publish(self):
        existing = self.destination / "earlier-backup"
        existing.mkdir(mode=0o700)
        for option in ("changed_upload", "changed_state", "changed_pod", "reject_dump"):
            with self.subTest(option=option):
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    self.capture(FakeCluster(**{option: True}))
                self.assertEqual(list(self.destination.iterdir()), [existing])

    def test_archive_paths_and_links_are_not_trusted(self):
        archive = self.destination / "uploads.tar"
        for name, symlink in (("../escape", False), ("/absolute", False), ("link", True)):
            with self.subTest(name=name):
                archive.write_bytes(archive_bytes(name=name, symlink=symlink))
                with self.assertRaises(ValueError):
                    BACKUP.upload_inventory(archive)

    def test_destination_must_be_private_and_outside_git(self):
        os.chmod(self.destination, 0o755)
        with self.assertRaises(ValueError):
            BACKUP.private_directory(self.destination)
        os.chmod(self.destination, 0o700)
        (self.destination / ".git").write_text("gitdir: private\n")
        with self.assertRaises(ValueError):
            BACKUP.private_directory(self.destination)

    def test_active_tasks_fail_before_capture(self):
        cluster = BACKUP.Cluster("kubectl", "test-context")
        with (
            patch.object(cluster, "execute", return_value=subprocess.CompletedProcess(
                [], 0, stdout=json.dumps({"active_tasks": 1}).encode())),
            self.assertRaises(ValueError),
        ):
            cluster.state("postgres")

    def test_unclaimed_work_survives_guard_but_daemon_owned_work_blocks(self):
        # Execute the exact count subquery sent to PostgreSQL against every
        # documented task status; queued and scheduled records remain backed up.
        query = BACKUP.STATE_QUERY.split("'active_tasks', (", 1)[1].split("),", 1)[0]
        with sqlite3.connect(":memory:") as database:
            database.execute("CREATE TABLE agent_task_queue (status TEXT)")
            for status in ("queued", "deferred", "completed", "failed", "cancelled"):
                database.execute("INSERT INTO agent_task_queue VALUES (?)", (status,))
            self.assertEqual(database.execute(query).fetchone()[0], 0)
            for expected, status in enumerate(
                    ("dispatched", "running", "waiting_local_directory"), start=1):
                database.execute("INSERT INTO agent_task_queue VALUES (?)", (status,))
                self.assertEqual(database.execute(query).fetchone()[0], expected)

    def test_metadata_and_archive_subprocess_deadlines_are_aligned(self):
        cluster = BACKUP.Cluster("kubectl", "test-context")
        response = subprocess.CompletedProcess([], 0, stdout=b'{"active_tasks": 0}')
        with patch.object(BACKUP.subprocess, "run", return_value=response) as run:
            cluster.json(["get", "pods", "-o", "json"])
            self.assertEqual(run.call_args.args[0], [
                "kubectl", "--context", "test-context", "--namespace", "ai",
                "--request-timeout=30s", "get", "pods", "-o", "json"])
            self.assertEqual(run.call_args.kwargs["timeout"], 30)

            cluster.state("postgres-pod")
            self.assertEqual(run.call_args.kwargs["timeout"], 30)
            self.assertIn("--request-timeout=30s", run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][6:14], [
                "exec", "-i", "postgres-pod", "-c", "postgres", "--", "psql", "-X"])

            command = ["tar", "-C", "/app/data/uploads", "-cf", "-", "."]
            BACKUP.capture(cluster, self.destination / "archive.tar", "backend-pod",
                           "backend", command)
            self.assertEqual(run.call_args.args[0], [
                "kubectl", "--context", "test-context", "--namespace", "ai",
                "--request-timeout=3600s", "exec", "-i", "backend-pod", "-c",
                "backend", "--", *command])
            self.assertEqual(run.call_args.kwargs["timeout"], 3600)
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
            self.assertTrue(run.call_args.kwargs["check"])


if __name__ == "__main__":
    unittest.main()
