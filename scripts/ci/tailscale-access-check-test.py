#!/usr/bin/env python3
"""Offline coverage for live identity verification and the no-op denial probe."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("access_check", Path(__file__).with_name("tailscale-access-check.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AccessCheckTest(unittest.TestCase):
    def run_check(self, identity="plan", *, denial=True, message=None, groups=None, credentials=None):
        calls = []
        def fake(args):
            calls.append(args)
            if args[:2] == ["config", "view"]:
                result = {"clusters": [{"cluster": {"server": MODULE.SERVER}}], "users": [{"user": credentials or {}}]}
            elif args[:2] == ["auth", "whoami"]:
                result = {"status": {"userInfo": {"groups": groups or [f"tag:homelab-ci-{identity}", "system:authenticated"]}}}
            elif args[:2] == ["auth", "can-i"]:
                return subprocess.CompletedProcess(args, 0, "yes\n", "")
            elif "patch" in args and "--dry-run=server" not in args:
                return subprocess.CompletedProcess(args, 1 if denial else 0, "", message if message is not None else "homelab-ci-plan-dry-run: "+MODULE.DENIAL)
            else:
                return subprocess.CompletedProcess(args, 0, "application.argoproj.io/tailscale", "")
            return subprocess.CompletedProcess(args, 0, json.dumps(result), "")
        output = io.StringIO()
        with patch.object(MODULE, "command", side_effect=fake), redirect_stdout(output), redirect_stderr(output):
            status = MODULE.main([identity])
        return status, output.getvalue(), calls

    def test_plan_requires_successful_dry_run_then_specific_real_write_denial(self):
        status, output, calls = self.run_check()
        self.assertEqual(status, 0, output)
        patches = [call for call in calls if "patch" in call]
        self.assertEqual(len(patches), 2)
        self.assertIn("--dry-run=server", patches[0])
        self.assertNotIn("--dry-run=server", patches[1])
        self.assertTrue(all("--patch=[]" in call for call in patches))
        self.assertTrue(all(call[1:5] == ["argocd", "patch", "application", "tailscale"] for call in patches))

    def test_missing_admission_or_unrelated_failures_do_not_pass(self):
        for kwargs in [{"denial": False}, {"message": "Forbidden by RBAC"}, {"message": "dial tcp: timeout"}]:
            with self.subTest(kwargs=kwargs):
                status, _, _ = self.run_check(**kwargs)
                self.assertEqual(status, 1)

    def test_wrong_identity_or_bearer_token_never_reaches_patch(self):
        for kwargs in [{"groups": ["tag:homelab-ci-apply"]}, {"groups": ["tag:homelab-ci-plan", "system:masters"]},
                       {"credentials": {"token": "synthetic-private-token"}}]:
            status, output, calls = self.run_check(**kwargs)
            self.assertEqual(status, 1)
            self.assertFalse(any("patch" in call for call in calls))
            self.assertNotIn("synthetic-private-token", output)

    def test_apply_uses_only_dry_run_and_checks_cluster_permission(self):
        status, output, calls = self.run_check("apply")
        self.assertEqual(status, 0, output)
        self.assertEqual(len([call for call in calls if "patch" in call]), 1)
        self.assertIn(["auth", "can-i", "*", "*", "--all-namespaces"], calls)


if __name__ == "__main__":
    unittest.main()
