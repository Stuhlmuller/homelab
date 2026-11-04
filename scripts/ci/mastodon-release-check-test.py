#!/usr/bin/env python3
"""Exercise stale, failed, misordered and unsafe database release evidence."""
import copy
import contextlib
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("release", Path(__file__).with_name("mastodon-release-check.py"))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
NOW = datetime(2026, 11, 1, 20, tzinfo=timezone.utc)
APP = {"status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}}
CRON = {"metadata": {"uid": "backup-cron"}, "spec": {"suspend": False}}
BACKUP = {"metadata": {"creationTimestamp": "2026-11-01T11:00:00Z", "ownerReferences": [
    {"kind": "CronJob", "name": "mastodon-backup", "uid": "backup-cron", "controller": True}]},
    "status": {"conditions": [{"type": "Complete", "status": "True"}],
               "completionTime": "2026-11-01T11:00:12Z"}}
RESTORE = {"metadata": {"labels": {"app.kubernetes.io/name": "mastodon-restore-verification"}},
           "status": {"conditions": [{"type": "Complete", "status": "True"}],
                      "startTime": "2026-11-01T11:01:00Z", "completionTime": "2026-11-01T11:02:00Z"},
           "spec": {"template": {"spec": {"automountServiceAccountToken": False, "volumes": [
               {"name": "backup", "persistentVolumeClaim": {"claimName": "mastodon-backup", "readOnly": True}},
               {"name": "restore", "emptyDir": {}}]}}}}


class ReleaseCheckTest(unittest.TestCase):
    def run_stopped_gate(self, cron=None, jobs=None, error=None, application=None):
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        class StoppedFailure(ValueError):
            pass

        stopped = SimpleNamespace(check=Mock(side_effect=error), Failure=StoppedFailure)
        loader = SimpleNamespace(exec_module=Mock())
        app = copy.deepcopy(APP) if application is None else copy.deepcopy(application)
        if application is None:
            app["status"]["sync"]["status"] = "OutOfSync"
        changed = subprocess.CompletedProcess([], 0, "scripts/ci/mastodon-stopped-baseline.py\0")
        output, diagnostic = io.StringIO(), io.StringIO()
        with (patch("sys.argv", ["check", "--base-ref", "origin/main"]),
              patch.object(release.subprocess, "run", return_value=changed),
              patch.object(release, "read_json", side_effect=[app, cron or CRON,
                           {"items": [BACKUP, RESTORE] if jobs is None else jobs}]),
              patch.object(release, "datetime", FrozenDateTime),
              patch.object(release.importlib.util, "spec_from_file_location",
                           return_value=SimpleNamespace(loader=loader)),
              patch.object(release.importlib.util, "module_from_spec", return_value=stopped),
              contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostic)):
            result = release.main()
        return result, output.getvalue(), diagnostic.getvalue(), stopped.check

    def test_verified_stop_accepts_only_the_baseline_error(self):
        result, output, errors, check = self.run_stopped_gate()
        self.assertEqual(result, 0)
        self.assertEqual(errors, "")
        self.assertIn("Verified source-bound stopped", output)
        check.assert_called_once()
        self.assertEqual(check.call_args.args[1:], ("origin/main", NOW))

        suspended = copy.deepcopy(CRON)
        suspended["spec"]["suspend"] = True
        stale = copy.deepcopy(BACKUP)
        stale["status"]["completionTime"] = "2026-10-30T11:00:12Z"
        unsafe = copy.deepcopy(RESTORE)
        unsafe["spec"]["template"]["spec"]["volumes"][0]["persistentVolumeClaim"]["readOnly"] = False
        for cron, jobs, message in ((suspended, [BACKUP, RESTORE], "backup is suspended"),
                                    (CRON, [stale, RESTORE], "backup has not succeeded"),
                                    (CRON, [BACKUP], "no fresh successful isolated"),
                                    (CRON, [BACKUP, unsafe], "no fresh successful isolated")):
            with self.subTest(message=message):
                result, output, errors, check = self.run_stopped_gate(cron=cron, jobs=jobs)
                self.assertEqual(result, 1)
                check.assert_called_once()
                self.assertIn(message, errors)
                self.assertNotIn("baseline is not Synced/Healthy", errors)
                self.assertNotIn("restore passed", output)

    def test_healthy_baseline_never_invokes_stopped_alternative(self):
        result, _, errors, check = self.run_stopped_gate(application=APP)
        self.assertEqual(result, 0)
        self.assertEqual(errors, "")
        check.assert_not_called()

    def test_stopped_evidence_errors_fail_closed_and_remain_private(self):
        private = "SYNTHETIC_PRIVATE_DIAGNOSTIC"
        for error in (subprocess.CalledProcessError(1, "kubectl", output=private, stderr=private),
                      KeyError(private), TypeError(private), ValueError(private),
                      AttributeError(private), OSError(private)):
            with self.subTest(error=type(error).__name__):
                result, output, errors, check = self.run_stopped_gate(error=error)
                self.assertEqual(result, 1)
                check.assert_called_once()
                self.assertIn("evidence unavailable", errors)
                self.assertNotIn(private, output + errors)

    def test_checker_only_edits_trigger_the_protected_live_gate(self):
        workflow = Path(__file__).parents[2] / ".github/workflows/terragrunt-plan.yml"
        scope = textwrap.dedent(workflow.read_text().split("      - name: Detect Live Terragrunt Plan Scope\n", 1)[1]
                                .split("        run: |\n", 1)[1].split("      - name:", 1)[0])
        paths = ["scripts/ci/mastodon-release-check.py", "scripts/ci/mastodon-release-check-test.py",
                 "scripts/ci/mastodon-stopped-baseline.py", "scripts/ci/mastodon-stopped-baseline-test.py"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git = root / "git"
            git.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_CHANGED_PATH"\n')
            git.chmod(0o700)
            for path in paths + ["clusters/homelab/apps/mastodon/README.md"]:
                with self.subTest(path=path):
                    output = root / "outputs"
                    output.write_text("")
                    result = subprocess.run(["bash", "-eu", "-c", scope], capture_output=True,
                                            text=True, timeout=5, check=False,
                                            env={**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                                                 "BASE_REF": "main", "GITHUB_OUTPUT": str(output),
                                                 "TEST_CHANGED_PATH": path})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = str(path in paths).lower()
                    self.assertIn("requires-live-plan=" + expected, output.read_text())
                    self.assertIn("requires-runtime-check=" + expected, output.read_text())
                    self.assertEqual(release.runtime_changed([path]), path in paths)

    def test_gitops_initial_and_scheduled_restore_templates_supply_release_evidence(self):
        root = Path(__file__).parents[2]
        rendered = subprocess.check_output(["kubectl", "kustomize", str(root / "clusters/homelab/apps/mastodon")],
                                           text=True)
        resources = json.loads(subprocess.check_output([
            "yq", "eval-all", "-o=json", ". as $doc ireduce ([]; . + [$doc])", "-",
        ], input=rendered, text=True))
        resources = {resource["metadata"]["name"]: resource for resource in resources}
        self.assertIn("mastodon-restore-verification", resources,
                      "Scheduled restore producer is missing from the candidate manifests.")
        self.assertIn("mastodon-restore-verification-v2", resources,
                      "Initial restore producer is missing from the candidate manifests.")
        scheduled = resources["mastodon-restore-verification"]
        self.assertFalse(scheduled["spec"]["suspend"])
        for template in (scheduled["spec"]["jobTemplate"], resources["mastodon-restore-verification-v2"]):
            evidence = copy.deepcopy(template)
            evidence["status"] = RESTORE["status"]
            self.assertEqual(release.failures(APP, CRON, [BACKUP, evidence], NOW), [])

    def test_gate_rejects_fork_runtime_changes_and_failed_live_checks(self):
        workflow = Path(__file__).parents[2] / ".github/workflows/terragrunt-plan.yml"
        gate = textwrap.dedent(workflow.read_text().split("      - name: Require Applicable Checks\n", 1)[1]
                               .split("        run: |\n", 1)[1])
        baseline = {**os.environ, "STATIC_RESULT": "success", "LIVE_PLAN_REQUIRED": "true",
                    "RUNTIME_CHECK_REQUIRED": "true", "TRUSTED_HEAD": "true",
                    "LIVE_PLAN_RESULT": "success", "SKIP_NOTE_RESULT": "skipped"}
        for changes, succeeds in (({}, True), ({"TRUSTED_HEAD": "false"}, False),
                                  ({"LIVE_PLAN_RESULT": "failure"}, False),
                                  ({"LIVE_PLAN_REQUIRED": "false"}, False),
                                  ({"RUNTIME_CHECK_REQUIRED": ""}, False),
                                  ({"STATIC_RESULT": "failure"}, False)):
            result = subprocess.run(["bash", "-c", gate], env={**baseline, **changes},
                                    capture_output=True, text=True, timeout=5, check=False)
            self.assertEqual(result.returncode == 0, succeeds, changes)

    def test_failed_read_stops_without_disclosing_private_diagnostics(self):
        private = "SYNTHETIC_PRIVATE_TOKEN"
        changed = subprocess.CompletedProcess([], 0, "clusters/homelab/apps/mastodon/workloads.yaml\0")
        denied = subprocess.CalledProcessError(1, "kubectl", output=private, stderr=private)
        output = io.StringIO()
        with (patch("sys.argv", ["check", "--base-ref", "origin/main"]),
              patch.object(release.subprocess, "run", return_value=changed),
              patch.object(release, "read_json", side_effect=denied) as read,
              contextlib.redirect_stderr(output)):
            self.assertEqual(release.main(), 1)
        self.assertEqual(read.call_count, 1)
        self.assertIn("evidence unavailable", output.getvalue())
        self.assertNotIn(private, output.getvalue())

    def test_scope_excludes_docs_and_includes_deleted_runtime_paths(self):
        self.assertFalse(release.runtime_changed(["docs/ci-cd.md", "clusters/homelab/apps/mastodon/README.md"]))
        self.assertTrue(release.runtime_changed(["clusters/homelab/apps/mastodon/workloads.yaml"]))
        self.assertTrue(release.runtime_changed(["IaC/homelab/us-west-2/apps/mastodon/terragrunt.stack.hcl"]))

    def test_fresh_ordered_evidence_passes(self):
        self.assertEqual(release.failures(APP, CRON, [BACKUP, RESTORE], NOW), [])

    def test_old_restore_does_not_accept_fresh_backup(self):
        restore = copy.deepcopy(RESTORE)
        restore["status"]["startTime"] = "2026-10-25T17:18:08Z"
        restore["status"]["completionTime"] = "2026-10-25T17:18:15Z"
        self.assertEqual(len(release.failures(APP, CRON, [BACKUP, restore], NOW)), 1)

    def test_latest_failed_backup_cannot_fall_back_to_an_older_success(self):
        failed = copy.deepcopy(BACKUP)
        failed["metadata"]["creationTimestamp"] = "2026-11-01T12:00:00Z"
        failed["status"] = {"conditions": [{"type": "Failed", "status": "True"}]}
        self.assertEqual(len(release.failures(APP, CRON, [BACKUP, RESTORE, failed], NOW)), 2)

    def test_stale_future_naive_and_missing_completion_fail(self):
        for completion in ("2026-10-30T11:00:00Z", "2026-11-02T11:00:00Z", "2026-11-01T11:00:00", None):
            backup = copy.deepcopy(BACKUP)
            backup["status"]["completionTime"] = completion
            self.assertIsNone(release.completed_at(backup, NOW))

    def test_foreign_cronjob_and_unhealthy_application_fail(self):
        cron = copy.deepcopy(CRON)
        cron["metadata"]["uid"] = "recreated-cron"
        self.assertEqual(len(release.failures({}, cron, [BACKUP, RESTORE], NOW)), 3)

    def test_restore_before_backup_and_production_mounts_fail(self):
        for change in ("early", "secret", "production-pvc", "writable-backup", "api-token",
                       "secret-env", "secret-env-from", "projected-token", "host-path", "host-network"):
            restore = copy.deepcopy(RESTORE)
            pod = restore["spec"]["template"]["spec"]
            if change == "early":
                restore["status"]["startTime"] = "2026-11-01T10:00:00Z"
            elif change == "secret":
                pod["volumes"].append({"name": "credentials", "secret": {"secretName": "production"}})
            elif change == "production-pvc":
                pod["volumes"].append({"name": "db", "persistentVolumeClaim": {"claimName": "production"}})
            elif change == "writable-backup":
                pod["volumes"][0]["persistentVolumeClaim"]["readOnly"] = False
            elif change == "secret-env":
                pod["containers"] = [{"env": [{"name": "PASSWORD", "valueFrom": {"secretKeyRef": {}}}]}]
            elif change == "secret-env-from":
                pod["initContainers"] = [{"envFrom": [{"secretRef": {"name": "production"}}]}]
            elif change == "projected-token":
                pod["volumes"].append({"name": "token", "projected": {"sources": [{"serviceAccountToken": {}}]}})
            elif change == "host-path":
                pod["volumes"].append({"name": "host", "hostPath": {"path": "/var"}})
            elif change == "host-network":
                pod["hostNetwork"] = True
            else:
                pod["automountServiceAccountToken"] = True
            self.assertEqual(len(release.failures(APP, CRON, [BACKUP, restore], NOW)), 1)


if __name__ == "__main__":
    unittest.main()
