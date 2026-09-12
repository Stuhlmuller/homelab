#!/usr/bin/env python3
"""Synthetic offsite scheduling tests; no client, launchd, or network operations."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


HERE = Path(__file__).resolve().parent
fixture = module("publication_fixture", HERE / "etcd-offsite-backup-check.py")
scheduler = module("offsite_schedule", HERE.parent / "etcd-offsite-schedule.py")


class ScheduleTests(fixture.PublicationFixture):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
        self.created = self.now - timedelta(hours=3)
        self.runtime = self.output
        self.attempts = self.runtime / "attempts"
        self.attempts.mkdir(mode=0o700)
        (self.runtime / scheduler.local.LOCK).touch(mode=0o600)
        self.scheduled = self.root / "scheduled"
        self.scheduled.mkdir(mode=0o700)
        (self.scheduled / scheduler.local.LOCK).touch(mode=0o600)
        self.source.rename(self.scheduled / "etcd-20260912T090000Z-fixture")
        self.source = self.scheduled / "etcd-20260912T090000Z-fixture"
        self.snapshot = self.source / fixture.offsite.FILES[0]
        self.confirm(self.source, self.created)
        self.policy = {"format": 1, "launchd_label": "org.homelab.etcd-offsite",
                       "minute": 27, "stale_after_hours": 36}
        self.settings = {"runtime_directory": str(self.runtime),
                         "local_runtime_directory": str(self.root / "local-runtime")}
        context = patch.object(scheduler.local, "installed", return_value=(
            {}, {"stale_after_hours": 36}, self.scheduled))
        context.start()
        self.addCleanup(context.stop)

    def confirm(self, path, created):
        manifest = path / "manifest.json"
        value = json.loads(manifest.read_text())
        value["created_at"] = created.isoformat()
        fixture.offsite.save(manifest, value)
        scheduler.local.record_success(self.scheduled, path, value)

    def run_attempt(self, now=None):
        return scheduler.run_schedule(self.runtime, self.settings, self.policy, self.aws,
                                      now=now or self.now)

    def status(self, now=None):
        return scheduler.status(self.runtime, self.policy, self.target, now or self.now)

    def test_verified_success_then_dedup_without_any_aws_call(self):
        result = self.run_attempt()
        self.assertEqual(result["action"], "verified")
        self.assertEqual(result["status"], "fresh")
        self.assertEqual(result["source_created_at"], self.created.isoformat())
        self.assertEqual(result["age_hours"], 3)
        self.assertEqual(sum(op == "put-object" for op, _ in self.calls), 2)
        calls = list(self.calls)
        self.assertEqual(self.run_attempt()["action"], "skipped")
        self.assertEqual(self.calls, calls)

    def test_lost_response_resumes_same_prefix_after_original_loss(self):
        self.lose_put_response = True
        result = self.run_attempt()
        self.assertEqual(result["action"], "failed")
        self.assertEqual(result["last_attempt"]["failure"], "timeout")
        keys = set(self.remote)
        shutil.rmtree(self.source)  # Simulate later independent local retention.
        result = self.run_attempt()
        self.assertEqual(result["action"], "verified")
        self.assertTrue(keys <= set(self.remote))
        self.assertEqual(sum(op == "put-object" for op, _ in self.calls), 2)

    def test_partial_retrieval_does_not_claim_success_and_resumes(self):
        self.corrupt_download = True
        self.assertEqual(self.run_attempt()["action"], "failed")
        self.assertEqual(self.status()["status"], "missing")
        self.corrupt_download = False
        self.assertEqual(self.run_attempt()["action"], "verified")
        self.assertEqual(sum(op == "put-object" for op, _ in self.calls), 2)
        self.assertTrue(list(self.attempts.glob("*/.partial-retrieval-*")))

    def test_newer_identical_sha_never_refreshes_old_remote_manifest_age(self):
        self.run_attempt()
        newer = self.scheduled / "etcd-20260914T090000Z-newer"
        shutil.copytree(self.source, newer)
        later = self.now + timedelta(hours=48)
        self.confirm(newer, later - timedelta(hours=1))
        calls = list(self.calls)
        result = self.run_attempt(later)
        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["age_hours"], 51)
        self.assertEqual(result["source_created_at"], self.created.isoformat())
        self.assertEqual(self.calls, calls)

    def test_source_lock_is_shared_during_copy_and_released_before_network(self):
        real_prepare = scheduler.offsite.prepare
        def prepare(*args, **kwargs):
            with scheduler.local.schedule_lock(self.scheduled, shared=True):
                pass
            with self.assertRaises(ValueError):
                with scheduler.local.schedule_lock(self.scheduled):
                    pass
            return real_prepare(*args, **kwargs)
        real_check = self.aws.check
        def check():
            with scheduler.local.schedule_lock(self.scheduled):
                pass  # Local writer is never blocked by AWS work.
            with self.assertRaises(ValueError):
                with scheduler.local.schedule_lock(self.runtime):
                    pass  # A second offsite attempt is blocked.
            return real_check()
        with patch.object(scheduler.offsite, "prepare", side_effect=prepare), \
                patch.object(self.aws, "check", side_effect=check):
            self.assertEqual(self.run_attempt()["action"], "verified")

    def test_expired_session_preserves_local_cadence_and_previous_verified_copy(self):
        self.run_attempt()
        old_receipt = (self.scheduled / scheduler.local.SUCCESS).read_bytes()
        newer = self.scheduled / "etcd-20260913T090000Z-newer"
        shutil.copytree(self.source, newer)
        data = b"different synthetic snapshot".ljust(4096, b"\0")
        import hashlib
        (newer / "etcd.snapshot").write_bytes(data + hashlib.sha256(data).digest())
        value = json.loads((newer / "manifest.json").read_text())
        value["integrity"] = fixture.offsite.backup.snapshot_digest(newer / "etcd.snapshot")
        fixture.offsite.save(newer / "manifest.json", value)
        later = self.now + timedelta(hours=24)
        self.confirm(newer, later - timedelta(hours=3))
        local_receipt = (self.scheduled / scheduler.local.SUCCESS).read_bytes()
        self.assertNotEqual(old_receipt, local_receipt)
        self.fail_operation = "get-caller-identity"
        result = self.run_attempt(later)
        self.assertEqual(result["action"], "failed")
        self.assertEqual(result["source_created_at"], self.created.isoformat())
        self.assertEqual(result["age_hours"], 27)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual((self.scheduled / scheduler.local.SUCCESS).read_bytes(), local_receipt)
        with scheduler.local.schedule_lock(self.scheduled):
            pass

    def test_unconfirmed_source_and_busy_local_writer_do_not_publish(self):
        (self.scheduled / scheduler.local.SUCCESS).unlink()
        self.assertEqual(self.run_attempt()["action"], "failed")
        self.assertEqual(self.calls, [])
        self.confirm(self.source, self.created)
        with scheduler.local.schedule_lock(self.scheduled):
            self.assertEqual(self.run_attempt()["action"], "failed")
        self.assertEqual(self.calls, [])

    def test_crash_after_prepare_adopts_same_durable_pair(self):
        real_save = scheduler.local.write_json
        def fail_pending(path, value):
            if path.name == scheduler.STATE and value.get("pending_sha"):
                raise KeyboardInterrupt("simulated process interruption")
            return real_save(path, value)
        with patch.object(scheduler.local, "write_json", side_effect=fail_pending):
            with self.assertRaises(KeyboardInterrupt):
                self.run_attempt()
        publication = next(self.attempts.glob("*/publication-*"))
        prefix = json.loads((publication / "publication.json").read_text())["prefix"]
        self.assertEqual(self.calls, [])
        self.assertEqual(self.run_attempt()["action"], "verified")
        self.assertEqual(len(list(self.attempts.glob("*/publication-*"))), 1)
        self.assertTrue(all(key.startswith(prefix + "/") for key in self.remote))

    def test_interrupted_verified_receipt_skips_network_and_commits_success(self):
        real_save = scheduler.local.write_json
        def fail_success(path, value):
            if path.name == scheduler.STATE and value.get("last_verified_sha"):
                raise KeyboardInterrupt("simulated interruption after verification")
            return real_save(path, value)
        with patch.object(scheduler.local, "write_json", side_effect=fail_success):
            with self.assertRaises(KeyboardInterrupt):
                self.run_attempt()
        calls = list(self.calls)
        self.assertEqual(self.run_attempt()["action"], "skipped")
        self.assertEqual(self.calls, calls)
        self.assertEqual(self.status()["status"], "fresh")

    def test_copy_failure_preserves_orphan_without_network_then_retries(self):
        with patch.object(scheduler.offsite.shutil, "copyfile", side_effect=OSError("disk full")):
            self.assertEqual(self.run_attempt()["action"], "failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.run_attempt()["action"], "verified")
        self.assertEqual(len(list(self.attempts.glob("*/publication-*"))), 2)

    def test_corrupted_retained_receipt_fails_without_new_prefix(self):
        self.fail_operation = "get-caller-identity"
        self.run_attempt()
        publication = next(self.attempts.glob("*/publication-*"))
        fixture.offsite.save(publication / "publication.json", {})
        calls = list(self.calls)
        self.assertEqual(self.run_attempt()["action"], "failed")
        self.assertEqual(self.calls, calls)
        self.assertEqual(len(list(self.attempts.glob("*/publication-*"))), 1)

    def test_ambiguous_prepared_pairs_fail_without_publishing(self):
        self.fail_operation = "get-caller-identity"
        self.run_attempt()
        publication = next(self.attempts.glob("*/publication-*"))
        scheduler.offsite.prepare(self.source, publication.parent, self.target)
        calls = list(self.calls)
        self.assertEqual(self.run_attempt()["action"], "failed")
        self.assertEqual(self.calls, calls)

    def test_pending_source_completes_before_a_newer_local_copy(self):
        self.lose_put_response = True
        self.run_attempt()
        newer = self.scheduled / "etcd-20260913T090000Z-newer"
        shutil.copytree(self.source, newer)
        self.confirm(newer, self.now + timedelta(hours=20))
        with patch.object(scheduler, "select_publication", side_effect=AssertionError("pending first")):
            result = self.run_attempt(self.now + timedelta(hours=24))
        self.assertEqual(result["action"], "verified")
        self.assertEqual(result["source_created_at"], self.created.isoformat())


class InstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.runtime = self.root / "runtime"
        self.source_runtime = self.root / "local-runtime"
        self.scheduled = self.root / "scheduled"
        self.operator = self.root / "operator"
        for path in (self.source_runtime, self.scheduled, self.operator):
            path.mkdir(mode=0o700)
        self.tool = self.root / "tool"
        self.tool.write_text("mocked executable")
        self.tool.chmod(0o700)
        self.real_reviewed_sources = scheduler.reviewed_sources
        self.files = {name: (HERE.parent.parent / name).read_bytes() for name in scheduler.SOURCES}
        self.args = SimpleNamespace(revision="a" * 40, runtime_directory=self.runtime,
                                    local_runtime_directory=self.source_runtime,
                                    python=self.tool, aws_cli=self.tool, profile="default")
        self.calls = []
        self.loaded = False
        self.fail_bootstrap_once = False
        def command(arguments, check=True):
            args = [str(arg) for arg in arguments]
            self.calls.append(args)
            if "bootstrap" in args:
                self.loaded = True
                if self.fail_bootstrap_once:
                    self.fail_bootstrap_once = False
                    raise subprocess.CalledProcessError(1, args)
            if "bootout" in args:
                self.loaded = False
            return subprocess.CompletedProcess(args, 0 if "print" not in args or self.loaded else 1, stdout="")
        def durable(path, create=False):
            if create:
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
            return fixture.offsite.backup.private_directory(path)
        for context in (
                patch.object(scheduler.local, "command", side_effect=command),
                patch.object(scheduler.local, "durable_directory", side_effect=durable),
                patch.object(scheduler.local, "installed", return_value=({}, {}, self.scheduled)),
                patch.object(scheduler, "reviewed_sources", return_value=self.files),
                patch.object(scheduler.sys, "platform", "darwin"),
                patch.object(scheduler.Path, "home", return_value=self.operator),
                patch.object(scheduler.offsite.AWS, "check", side_effect=AssertionError("install must not contact AWS"))):
            context.start()
            self.addCleanup(context.stop)

    def test_install_preserves_relative_sources_and_uses_separate_service(self):
        scheduler.install(self.args)
        settings, policy, target = scheduler.installed(self.runtime)
        self.assertEqual(target, fixture.offsite.destination())
        self.assertEqual(settings["local_runtime_directory"], str(self.source_runtime))
        self.assertEqual(settings["profile"], "default")
        release = self.runtime / "releases" / self.args.revision
        for name, data in self.files.items():
            self.assertEqual((release / name).read_bytes(), data)
            self.assertEqual((release / name).stat().st_mode & 0o777, 0o600)
        plist = scheduler.render_plist(settings, policy)
        self.assertEqual(plist["StartCalendarInterval"], {"Minute": 27})
        self.assertTrue(plist["RunAtLoad"])
        self.assertNotIn("KeepAlive", plist)
        self.assertNotIn("EnvironmentVariables", plist)
        self.assertEqual(plist["ProgramArguments"][1], str(release / scheduler.SOURCES[0]))
        self.assertTrue(self.loaded)
        self.assertFalse(any("org.homelab.etcd-backup" in arg for call in self.calls for arg in call))
        (release / scheduler.DESTINATION).write_text("changed")
        with self.assertRaisesRegex(ValueError, "reviewed release"):
            scheduler.installed(self.runtime)

    def test_failed_service_update_restores_prior_loaded_configuration_and_attempts(self):
        scheduler.install(self.args)
        before = (self.runtime / "installation.json").read_bytes()
        retained = self.runtime / "attempts" / "operator-record"
        retained.write_text("preserve")
        self.args.revision = "b" * 40
        self.fail_bootstrap_once = True
        with self.assertRaisesRegex(ValueError, "previous loaded schedule restored"):
            scheduler.install(self.args)
        self.assertTrue(self.loaded)
        self.assertEqual((self.runtime / "installation.json").read_bytes(), before)
        self.assertEqual(retained.read_text(), "preserve")

    def test_active_attempt_blocks_install_without_disrupting_service(self):
        scheduler.install(self.args)
        before = list(self.calls)
        with scheduler.local.schedule_lock(self.runtime):
            with self.assertRaisesRegex(ValueError, "lock is busy"):
                scheduler.install(self.args)
        self.assertTrue(self.loaded)
        self.assertFalse(any("bootout" in call for call in self.calls[len(before):]))

    def test_source_runtime_cannot_be_changed_in_place(self):
        scheduler.install(self.args)
        other = self.root / "other-runtime"
        other.mkdir(mode=0o700)
        self.args.local_runtime_directory = other
        with self.assertRaisesRegex(ValueError, "fresh runtime"):
            scheduler.install(self.args)
        self.assertTrue(self.loaded)


    def test_uninstall_is_idempotent_and_preserves_local_schedule_and_attempts(self):
        scheduler.install(self.args)
        retained = self.runtime / "attempts" / "operator-record"
        retained.write_text("preserve")
        arguments = ["etcd-offsite-schedule.py", "uninstall", "--runtime-directory", str(self.runtime)]
        with patch.object(scheduler.sys, "argv", arguments), patch("builtins.print"):
            self.assertEqual(scheduler.main(), 0)
            self.assertEqual(scheduler.main(), 0)
        self.assertFalse(self.loaded)
        self.assertTrue((self.runtime / "installation.json").exists())
        self.assertEqual(retained.read_text(), "preserve")
        self.assertTrue(self.source_runtime.exists())
        self.assertTrue(self.scheduled.exists())

    def test_first_bootstrap_failure_restores_absent_service(self):
        self.fail_bootstrap_once = True
        with self.assertRaisesRegex(ValueError, "previous unloaded state restored"):
            scheduler.install(self.args)
        self.assertFalse(self.loaded)
        self.assertFalse((self.runtime / "installation.json").exists())
    def test_reviewed_source_requires_exact_head_and_destination_bytes(self):
        repository = self.root / "repository"
        for name, data in self.files.items():
            path = repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        def git(arguments, **kwargs):
            if "rev-parse" in arguments:
                stdout = self.args.revision
            elif "show" in arguments:
                stdout = self.files[arguments[-1].split(":", 1)[1]].decode()
            else:
                stdout = ""
            return subprocess.CompletedProcess(arguments, 0, stdout=stdout)
        # Bypass only the install fixture's reviewed_sources mock here.
        with patch.object(scheduler, "HERE", repository / "scripts"), \
                patch.object(scheduler.local, "command", side_effect=git):
            self.assertEqual(self.real_reviewed_sources(self.args.revision), self.files)
            with self.assertRaisesRegex(ValueError, "checkout HEAD"):
                self.real_reviewed_sources("b" * 40)
            (repository / scheduler.DESTINATION).write_text("unreviewed destination")
            with self.assertRaisesRegex(ValueError, "checkout source"):
                self.real_reviewed_sources(self.args.revision)


if __name__ == "__main__":
    unittest.main()
