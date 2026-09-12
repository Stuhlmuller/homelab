#!/usr/bin/env python3
"""Exercise snapshot publication and corruption failures using synthetic bytes."""

import hashlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


script = Path(__file__).resolve().parents[1] / "talos-etcd-backup.py"
spec = importlib.util.spec_from_file_location("talos_etcd_backup", script)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.destination = self.root / "backups"
        self.destination.mkdir(mode=0o700)
        self.config = self.root / "talosconfig"
        self.config.touch(mode=0o600)
        self.executable = self.root / "talosctl"
        self.executable.touch(mode=0o700)
        self.payload = b"synthetic fixture; never cluster data".ljust(4096, b"\x00")
        self.snapshot = self.payload + hashlib.sha256(self.payload).digest()

    def client(self, command, **kwargs):
        self.assertEqual(command[:-1], [
            str(self.executable), "--talosconfig", str(self.config),
            "--endpoints", "10.1.0.199", "--nodes", "10.1.0.199",
            "etcd", "snapshot",
        ])
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["timeout"], 300)
        snapshot = Path(command[-1])
        snapshot.touch(mode=0o600)
        snapshot.write_bytes(self.snapshot)
        return subprocess.CompletedProcess(command, 0, stdout=(
            "snapshot info: hash 0123abcd, revision 42, total keys 7, total size 4096\n"
        ))

    def test_success_is_private_repeatable_and_verifiable_offline(self):
        with patch.object(backup.subprocess, "run", side_effect=self.client) as client:
            first, record = backup.backup(self.destination, self.config, self.executable)
            second, _ = backup.backup(self.destination, self.config, self.executable)
        self.assertEqual(client.call_count, 2)
        self.assertNotEqual(first, second)
        self.assertEqual(backup.verify(first), record)
        self.assertEqual(record["integrity"]["sha256"], hashlib.sha256(self.snapshot).hexdigest())
        self.assertEqual(record["metadata"]["revision"], 42)
        self.assertEqual(first.stat().st_mode & 0o777, 0o700)
        for path in first.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(set(self.destination.iterdir()), {first, second})

    def test_corruption_and_truncation_never_publish_or_remove_prior_backup(self):
        with patch.object(backup.subprocess, "run", side_effect=self.client):
            existing, _ = backup.backup(self.destination, self.config, self.executable)
            for contents in (self.snapshot[:-1], b"x" + self.snapshot[1:], b""):
                with self.subTest(contents_length=len(contents)):
                    self.snapshot = contents
                    with self.assertRaises(ValueError):
                        backup.backup(self.destination, self.config, self.executable)
                    self.assertEqual(list(self.destination.iterdir()), [existing])
        backup.verify(existing)

    def test_changed_completed_snapshot_fails_offline_verification(self):
        with patch.object(backup.subprocess, "run", side_effect=self.client):
            directory, _ = backup.backup(self.destination, self.config, self.executable)
        replacement = b"different but internally checksummed".ljust(4096, b"\x00")
        (directory / backup.SNAPSHOT).write_bytes(
            replacement + hashlib.sha256(replacement).digest()
        )
        with self.assertRaisesRegex(ValueError, "manifest"):
            backup.verify(directory)

    def test_missing_metadata_client_failure_and_timeout_never_publish(self):
        outcomes = [subprocess.CompletedProcess([], 0, stdout=""),
                    subprocess.CalledProcessError(1, "talosctl"),
                    subprocess.TimeoutExpired("talosctl", 300)]
        for result in outcomes:
            with self.subTest(result=result):
                with patch.object(backup.subprocess, "run", side_effect=[result]):
                    with self.assertRaises((ValueError, subprocess.SubprocessError)):
                        backup.backup(self.destination, self.config, self.executable)
                self.assertEqual(list(self.destination.iterdir()), [])

    def test_unsafe_destination_fails_before_client_runs(self):
        with patch.object(backup.subprocess, "run") as client:
            os.chmod(self.destination, 0o755)
            with self.assertRaisesRegex(ValueError, "0700"):
                backup.backup(self.destination, self.config, self.executable)
            os.chmod(self.destination, 0o700)
            (self.root / ".git").write_text("gitdir: elsewhere\n")
            with self.assertRaisesRegex(ValueError, "Git"):
                backup.backup(self.destination, self.config, self.executable)
            with self.assertRaisesRegex(ValueError, "absolute"):
                backup.backup(Path("relative"), self.config, self.executable)
        client.assert_not_called()

    def test_directory_entries_are_synced_before_and_after_publication(self):
        synced = []
        real_sync = backup.sync_directory

        def observe_sync(path):
            synced.append(path)
            if path == self.destination:
                completed = list(self.destination.iterdir())
                self.assertEqual(len(completed), 1)
                self.assertFalse(completed[0].name.startswith(".partial-"))
                backup.verify(completed[0])
            else:
                self.assertTrue(path.name.startswith(".partial-"))
                self.assertEqual(set(path.iterdir()),
                                 {path / backup.SNAPSHOT, path / backup.MANIFEST})
                backup.verify(path)
            real_sync(path)

        with patch.object(backup.subprocess, "run", side_effect=self.client):
            with patch.object(backup, "sync_directory", side_effect=observe_sync):
                directory, _ = backup.backup(self.destination, self.config, self.executable)
        self.assertEqual(len(synced), 2)
        self.assertEqual(synced[1], self.destination)
        self.assertEqual(directory.parent, self.destination)

    def test_directory_sync_failure_never_reports_success(self):
        with patch.object(backup.subprocess, "run", side_effect=self.client):
            existing, record = backup.backup(self.destination, self.config, self.executable)
        for failure_index in (0, 1):
            with self.subTest(failure_index=failure_index):
                calls = [None, None]
                calls[failure_index] = OSError("directory sync failed")
                with patch.object(backup.subprocess, "run", side_effect=self.client):
                    with patch.object(backup, "sync_directory", side_effect=calls):
                        with self.assertRaisesRegex(OSError, "directory sync failed"):
                            backup.backup(self.destination, self.config, self.executable)
                completed = list(self.destination.iterdir())
                self.assertEqual(len(completed), 1 + failure_index)
                self.assertEqual(backup.verify(existing), record)
                # Failure after rename retains the verified data, but the call
                # fails because persistence of its final name is unconfirmed.
                for directory in completed:
                    backup.verify(directory)

    def test_explicit_client_path_is_used(self):
        args = [str(script), "backup", "--destination", str(self.destination),
                "--talosconfig", str(self.config), "--talosctl", str(self.executable)]
        with patch.object(backup.subprocess, "run", side_effect=self.client) as client:
            with patch.object(backup.sys, "argv", args), patch("builtins.print"):
                self.assertEqual(backup.main(), 0)
        self.assertEqual(client.call_args.args[0][0], str(self.executable))

    def test_missing_client_argument_fails_before_download(self):
        args = [str(script), "backup", "--destination", str(self.destination),
                "--talosconfig", str(self.config)]
        with patch.object(backup.subprocess, "run") as client:
            with patch.object(backup.sys, "argv", args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    backup.main()
        self.assertEqual(failure.exception.code, 2)
        client.assert_not_called()
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_invalid_client_paths_fail_before_download(self):
        non_executable = self.root / "not-executable"
        non_executable.touch(mode=0o600)
        invalid = ["talosctl", "./talosctl", str(self.root / "missing"),
                   str(non_executable), str(self.root)]
        for executable in invalid:
            with self.subTest(executable=executable):
                args = [str(script), "backup", "--destination", str(self.destination),
                        "--talosconfig", str(self.config), "--talosctl", executable]
                with patch.object(backup.subprocess, "run") as client:
                    with patch.object(backup.sys, "argv", args), redirect_stderr(io.StringIO()):
                        self.assertEqual(backup.main(), 1)
                client.assert_not_called()
                self.assertEqual(list(self.destination.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
