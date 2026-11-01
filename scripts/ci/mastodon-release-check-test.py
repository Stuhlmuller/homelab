#!/usr/bin/env python3
"""Exercise stale, failed, misordered and unsafe database release evidence."""
import copy
import contextlib
from datetime import datetime, timezone
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import textwrap
import unittest
from unittest.mock import patch

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
        for change in ("early", "secret", "production-pvc", "writable-backup", "api-token"):
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
            else:
                pod["automountServiceAccountToken"] = True
            self.assertEqual(len(release.failures(APP, CRON, [BACKUP, restore], NOW)), 1)


if __name__ == "__main__":
    unittest.main()
