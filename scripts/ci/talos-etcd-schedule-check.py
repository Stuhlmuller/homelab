#!/usr/bin/env python3
"""Exercise real scheduling/retention code with synthetic snapshots; no live calls."""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


script = Path(__file__).resolve().parents[1] / "talos-etcd-schedule.py"
spec = importlib.util.spec_from_file_location("talos_etcd_schedule", script)
schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedule)
backup = schedule.backup


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.scheduled = self.root / "scheduled"
        self.scheduled.mkdir(mode=0o700)
        (self.scheduled / schedule.LOCK).touch(mode=0o600)
        self.manual = self.root / "etcd-manual-preserve"
        self.manual.mkdir(mode=0o700)
        (self.manual / "operator-file").write_text("manual snapshot remains untouched")
        self.config = self.root / "talosconfig"
        self.config.touch(mode=0o600)
        self.client = self.root / "talosctl"
        self.client.touch(mode=0o700)
        self.now = datetime(2026, 9, 7, 16, tzinfo=timezone.utc)
        self.policy = schedule.read_policy(script.parent / "config/talos-etcd-backup-schedule.json")
        self.payload = b"synthetic snapshot; no cluster contents".ljust(4096, b"\0")

    def download(self, command, **kwargs):
        self.assertEqual(command[:-1], [str(self.client), "--talosconfig", str(self.config),
                                       "--endpoints", "10.1.0.199", "--nodes", "10.1.0.199",
                                       "etcd", "snapshot"])
        path = Path(command[-1])
        path.touch(mode=0o600)
        path.write_bytes(self.payload + hashlib.sha256(self.payload).digest())
        return subprocess.CompletedProcess(command, 0, stdout=(
            "snapshot info: hash 0123abcd, revision 42, total keys 7, total size 4096\n"))

    def save(self, age_days=0):
        when = self.now - timedelta(days=age_days)
        with patch.object(backup, "datetime", wraps=datetime) as clock:
            clock.now.return_value = when
            with patch.object(backup.subprocess, "run", side_effect=self.download):
                directory, record = backup.backup(self.scheduled, self.config, self.client)
        return directory, record

    def confirm(self, directory, record):
        schedule.write_json(self.scheduled / schedule.SUCCESS, {
            "directory": directory.name, "created_at": record["created_at"],
            "sha256": record["integrity"]["sha256"]})

    def run_scheduled(self):
        with patch.object(backup, "datetime", wraps=datetime) as clock, patch.object(schedule, "datetime", wraps=datetime) as scheduler_clock:
            clock.now.return_value = self.now
            scheduler_clock.now.return_value = self.now
            return schedule.run_schedule(self.scheduled, self.policy, self.config,
                                         self.client, self.now)

    def test_first_run_then_hourly_checks_avoid_extra_snapshots(self):
        with patch.object(backup.subprocess, "run", side_effect=self.download) as download:
            self.assertEqual(self.run_scheduled()["action"], "backed-up")
            self.now += timedelta(hours=23, minutes=59, seconds=59)
            self.assertEqual(self.run_scheduled()["action"], "skipped")
            self.assertEqual(download.call_count, 1)
            self.now += timedelta(seconds=1)
            self.assertEqual(self.run_scheduled()["action"], "backed-up")
            self.assertEqual(download.call_count, 2)

    def test_wake_catchup_makes_one_backup_and_no_replayed_backlog(self):
        directory, record = self.save(age_days=3)
        self.confirm(directory, record)
        with patch.object(backup.subprocess, "run", side_effect=self.download) as download:
            self.assertEqual(self.run_scheduled()["action"], "backed-up")
            self.assertEqual(self.run_scheduled()["action"], "skipped")
            self.assertEqual(download.call_count, 1)

    def test_same_second_copies_are_ordered_by_completion_not_random_suffix(self):
        first, _ = self.save()
        first.rename(first.with_name(first.name[:21] + "-zzzz"))
        self.now += timedelta(microseconds=1)
        second, record = self.save()
        renamed = second.with_name(second.name[:21] + "-aaaa")
        second.rename(renamed)
        self.confirm(renamed, record)
        status = schedule.latest_status(self.scheduled, self.policy, self.now)
        self.assertEqual(status["directory"], str(renamed))
        self.assertEqual(status["status"], "fresh")

    def test_corrupt_old_collision_group_does_not_force_hourly_backups(self):
        first, _ = self.save(age_days=3)
        first.rename(first.with_name(first.name[:21] + "-zzzz"))
        second, _ = self.save(age_days=3)
        (second / backup.MANIFEST).write_text("corrupt old manifest")
        latest, record = self.save()
        self.confirm(latest, record)
        self.assertEqual(schedule.latest_status(self.scheduled, self.policy, self.now)["status"], "fresh")
        with patch.object(backup.subprocess, "run") as download:
            self.assertEqual(self.run_scheduled()["action"], "skipped")
            download.assert_not_called()
        self.now += timedelta(days=1)
        with patch.object(backup.subprocess, "run", side_effect=self.download) as download:
            result = self.run_scheduled()
            self.assertEqual(result["action"], "backed-up")
            self.assertIn("retention_warning", result)
            self.assertEqual(result["pruned"], [])
            self.assertEqual(download.call_count, 1)
        self.assertEqual(len(schedule.completed_directories(self.scheduled)), 4)
        self.assertEqual((second / backup.MANIFEST).read_text(), "corrupt old manifest")

    def test_status_is_offline_and_reports_missing_stale_and_corruption(self):
        with patch.object(backup.subprocess, "run") as download:
            self.assertEqual(schedule.latest_status(self.scheduled, self.policy, self.now)["status"], "missing")
            download.assert_not_called()
        directory, record = self.save(age_days=1.5)
        self.confirm(directory, record)
        with patch.object(backup.subprocess, "run") as download:
            self.assertEqual(schedule.latest_status(self.scheduled, self.policy, self.now)["status"], "stale")
            download.assert_not_called()
        (directory / backup.SNAPSHOT).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "truncated"):
            schedule.latest_status(self.scheduled, self.policy, self.now)
        with patch.object(backup.subprocess, "run", side_effect=self.download) as download, patch.object(schedule, "prune") as prune:
            result = self.run_scheduled()
            self.assertEqual(result["action"], "backed-up")
            self.assertIn("retention_warning", result)
            self.assertEqual(download.call_count, 1)
            prune.assert_not_called()
        self.assertEqual((directory / backup.SNAPSHOT).read_bytes(), b"corrupt")

    def test_malformed_success_receipt_does_not_permanently_stop_new_backups(self):
        directory, record = self.save(age_days=1)
        (self.scheduled / schedule.SUCCESS).write_text("invalid receipt")
        with self.assertRaises(ValueError):
            schedule.latest_status(self.scheduled, self.policy, self.now)
        with patch.object(backup.subprocess, "run", side_effect=self.download) as download, patch.object(schedule, "prune") as prune:
            result = self.run_scheduled()
            self.assertEqual(result["action"], "backed-up")
            self.assertIn("retention_warning", result)
            self.assertEqual(download.call_count, 1)
            prune.assert_not_called()
        self.assertEqual(backup.verify(directory), record)

    def test_failure_and_timeout_do_not_prune_or_advance_success(self):
        directory, record = self.save(age_days=40)
        self.confirm(directory, record)
        receipt = (self.scheduled / schedule.SUCCESS).read_bytes()
        for error in (subprocess.CalledProcessError(1, "talosctl"),
                      subprocess.TimeoutExpired("talosctl", 300)):
            with self.subTest(error=type(error).__name__):
                with patch.object(backup.subprocess, "run", side_effect=error), patch.object(schedule, "prune") as prune:
                    with self.assertRaises(type(error)):
                        self.run_scheduled()
                    prune.assert_not_called()
                self.assertEqual((self.scheduled / schedule.SUCCESS).read_bytes(), receipt)
                self.assertEqual(backup.verify(directory), record)
                self.assertEqual(len(schedule.completed_directories(self.scheduled)), 1)

    def test_post_publish_sync_failure_retries_instead_of_trusting_new_directory(self):
        directory, record = self.save(age_days=2)
        self.confirm(directory, record)
        original_sync = backup.sync_directory
        def fail_destination(path):
            if path == self.scheduled:
                raise OSError("destination sync failed")
            original_sync(path)
        with patch.object(backup.subprocess, "run", side_effect=self.download):
            with patch.object(backup, "sync_directory", side_effect=fail_destination), patch.object(schedule, "prune") as prune:
                with self.assertRaises(OSError):
                    self.run_scheduled()
                prune.assert_not_called()
        self.assertEqual(schedule.latest_status(self.scheduled, self.policy, self.now)["status"], "unconfirmed")
        self.now += timedelta(hours=1)
        with patch.object(backup.subprocess, "run", side_effect=self.download) as download:
            self.assertEqual(self.run_scheduled()["action"], "backed-up")
            self.assertEqual(download.call_count, 1)

    def test_receipt_publication_failure_cannot_prune(self):
        directory, record = self.save(age_days=40)
        self.confirm(directory, record)
        with patch.object(backup.subprocess, "run", side_effect=self.download):
            with patch.object(schedule, "write_json", side_effect=OSError("receipt sync failed")), patch.object(schedule, "prune") as prune:
                with self.assertRaises(OSError):
                    self.run_scheduled()
                prune.assert_not_called()
        self.assertTrue(directory.exists())

    def test_receipt_sync_failure_after_replace_restores_old_receipt_and_retries(self):
        directory, record = self.save(age_days=40)
        self.confirm(directory, record)
        receipt = self.scheduled / schedule.SUCCESS
        previous = receipt.read_bytes()
        original_sync = backup.sync_directory
        failures = []
        def fail_after_receipt_replace(path):
            if path == self.scheduled and receipt.exists() and receipt.read_bytes() != previous and not failures:
                failures.append(json.loads(receipt.read_text())["directory"])
                raise OSError("receipt directory sync failed after replace")
            original_sync(path)
        with patch.object(backup.subprocess, "run", side_effect=self.download):
            with patch.object(backup, "sync_directory", side_effect=fail_after_receipt_replace), patch.object(schedule, "prune") as prune:
                with self.assertRaisesRegex(OSError, "after replace"):
                    self.run_scheduled()
                prune.assert_not_called()
        self.assertEqual(len(failures), 1)
        self.assertEqual(receipt.read_bytes(), previous)
        self.assertEqual(backup.verify(directory), record)
        self.assertEqual(schedule.latest_status(self.scheduled, self.policy, self.now)["status"], "unconfirmed")
        self.now += timedelta(hours=1)
        with patch.object(backup.subprocess, "run", side_effect=self.download) as download:
            self.assertEqual(self.run_scheduled()["action"], "backed-up")
            self.assertEqual(download.call_count, 1)

    def test_retention_preserves_28_days_and_manual_and_interrupted_data(self):
        for age in range(1, 36):
            directory, record = self.save(age_days=age)
            if age == 1:
                self.confirm(directory, record)
        partial = self.scheduled / ".partial-etcd-interrupted"
        partial.mkdir(mode=0o700)
        unknown = self.scheduled / "operator-note"
        unknown.write_text("preserve")
        with patch.object(backup.subprocess, "run", side_effect=self.download):
            result = self.run_scheduled()
        self.assertEqual(len(result["pruned"]), 7)
        self.assertEqual(len(schedule.completed_directories(self.scheduled)), 29)
        self.assertTrue((self.manual / "operator-file").exists())
        self.assertTrue(partial.exists())
        self.assertEqual(unknown.read_text(), "preserve")

    def test_retention_keeps_at_least_seven_valid_copies_when_all_old(self):
        for age in range(40, 50):
            directory, record = self.save(age_days=age)
            if age == 40:
                self.confirm(directory, record)
        with patch.object(backup.subprocess, "run", side_effect=self.download):
            self.run_scheduled()
        self.assertEqual(len(schedule.completed_directories(self.scheduled)), 7)

    def test_corrupt_retention_candidate_prevents_any_deletion(self):
        for age in range(40, 50):
            directory, record = self.save(age_days=age)
            if age == 40:
                self.confirm(directory, record)
            if age == 45:
                (directory / backup.SNAPSHOT).write_bytes(b"broken")
        with patch.object(backup.subprocess, "run", side_effect=self.download):
            result = self.run_scheduled()
            self.assertEqual(result["action"], "backed-up")
            self.assertIn("retention_warning", result)
            self.assertEqual(result["pruned"], [])
        self.assertEqual(len(schedule.completed_directories(self.scheduled)), 11)

    def test_overlap_stops_before_download_and_status_uses_shared_lock(self):
        with schedule.schedule_lock(self.scheduled):
            with patch.object(backup.subprocess, "run") as download:
                with self.assertRaisesRegex(ValueError, "running"):
                    self.run_scheduled()
                with self.assertRaisesRegex(ValueError, "running"):
                    with schedule.schedule_lock(self.scheduled, shared=True):
                        self.fail("lock should be busy")
                download.assert_not_called()

    def test_scheduled_symlink_cannot_target_manual_siblings(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            schedule.run_schedule(alias, self.policy, self.config, self.client, self.now)

    def test_plist_uses_hourly_calendar_wake_coalescing_and_explicit_durable_code(self):
        settings = {"runtime_directory": "/Users/operator/.local/share/homelab/etcd-runtime",
                    "revision": "a" * 40, "python": "/opt/operator/python3"}
        plist = schedule.render_plist(settings, self.policy)
        self.assertEqual(plistlib.loads(plistlib.dumps(plist)), plist)
        self.assertEqual(plist["StartCalendarInterval"], {"Minute": 17})
        self.assertTrue(plist["RunAtLoad"])
        self.assertNotIn("StartInterval", plist)
        self.assertNotIn("EnvironmentVariables", plist)
        self.assertNotIn("KeepAlive", plist)
        self.assertEqual(plist["ProgramArguments"], ["/opt/operator/python3",
            "/Users/operator/.local/share/homelab/etcd-runtime/releases/" + "a" * 40 + "/talos-etcd-schedule.py",
            "run", "--runtime-directory", settings["runtime_directory"]])

    def test_source_install_rejects_dirty_code_and_wrong_reviewed_head(self):
        repo = self.root / "repo"
        (repo / "scripts/config").mkdir(parents=True)
        contents = {name: b"reviewed source\n" for name in schedule.SOURCES}
        for name, data in contents.items():
            (repo / name).write_bytes(data)
        revision = "a" * 40
        def git(args, **kwargs):
            if "rev-parse" in args:
                output = revision + "\n"
            elif "show" in args:
                output = contents[args[-1].split(":", 1)[1]].decode()
            else:
                output = ""
            return subprocess.CompletedProcess(args, 0, stdout=output)
        with patch.object(schedule, "HERE", repo / "scripts"), patch.object(schedule, "command", side_effect=git):
            self.assertEqual(len(schedule.reviewed_sources(revision)), 3)
            (repo / "scripts/talos-etcd-backup.py").write_text("uncommitted change\n")
            with self.assertRaisesRegex(ValueError, "local source differs"):
                schedule.reviewed_sources(revision)
            with self.assertRaisesRegex(ValueError, "HEAD does not match"):
                schedule.reviewed_sources("b" * 40)

    def test_install_copies_reviewed_code_and_uninstall_preserves_all_backups(self):
        runtime = self.root / "runtime"
        operator = self.root / "operator"
        operator.mkdir(mode=0o700)
        files = {Path(name).name: (script.parent.parent / name).read_bytes() for name in schedule.SOURCES}
        args = SimpleNamespace(revision="a" * 40, runtime_directory=runtime,
                               backup_root=self.root, talosconfig=self.config,
                               talosctl=self.client, python=self.client)
        def directory(path, create=False):
            if create:
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
            return backup.private_directory(path)
        calls = []
        def local_command(args, check=True):
            calls.append([str(arg) for arg in args])
            output = "Client:\nTalos v1.11.3\n" if "--client" in args else ""
            code = 1 if "print" in args else 0
            return subprocess.CompletedProcess(args, code, stdout=output)
        with patch.object(schedule, "durable_directory", side_effect=directory), patch.object(schedule, "reviewed_sources", return_value=files), patch.object(schedule, "command", side_effect=local_command), patch.object(schedule.sys, "platform", "darwin"), patch.object(Path, "home", return_value=operator):
            result = schedule.install(args)
            self.assertEqual(result["revision"], args.revision)
            release = runtime / "releases" / args.revision
            for name, data in files.items():
                self.assertEqual((release / name).read_bytes(), data)
                self.assertEqual((release / name).stat().st_mode & 0o777, 0o600)
            settings, policy, selected = schedule.installed(runtime)
            self.assertEqual(selected, self.scheduled)
            self.assertEqual(settings["source_sha256"]["talos-etcd-backup.py"], hashlib.sha256(files["talos-etcd-backup.py"]).hexdigest())
            plist = operator / "Library/LaunchAgents/org.homelab.etcd-backup.plist"
            self.assertTrue(plist.exists())
            self.assertTrue(any("bootstrap" in call for call in calls))
            self.assertFalse(any("snapshot" in call for call in calls))
            with patch.object(schedule.sys, "argv", [str(script), "uninstall", "--runtime-directory", str(runtime)]), patch("builtins.print"):
                self.assertEqual(schedule.main(), 0)
                self.assertEqual(schedule.main(), 0)
            self.assertFalse(plist.exists())
            self.assertTrue((self.manual / "operator-file").exists())
            self.assertTrue(release.is_dir())
            self.assertTrue(self.scheduled.is_dir())
            (release / Path(schedule.POLICY_SOURCE).name).write_text("unreviewed edit")
            with self.assertRaisesRegex(ValueError, "reviewed release manifest"):
                schedule.installed(runtime)


if __name__ == "__main__":
    unittest.main()
