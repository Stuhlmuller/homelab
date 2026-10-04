#!/usr/bin/env python3
"""Exercise exact-main OIDC verification without network or infrastructure writes."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("entra-oidc-verify.py")
SPEC = importlib.util.spec_from_file_location("entra_oidc_verify", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SHA = "a" * 40
ENVIRONMENT = {
    "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
    "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_SHA": SHA, "EXPECTED_SHA": SHA,
    "ARM_CLIENT_ID": "11111111-1111-4111-8111-111111111111",
    "ARM_TENANT_ID": "22222222-2222-4222-8222-222222222222",
    "ARM_USE_OIDC": "true", "ARM_USE_CLI": "false", "ARM_USE_MSI": "false",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.invalid/oidc",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "synthetic-private-token",
}


class VerifyTest(unittest.TestCase):
    def run_script(self, *, environment=None, fail_unit=None, plan_status=0,
                   main_sha=SHA, signed=True, dirty="", move_after=None):
        calls = []
        api_count = 0

        def run(args, **kwargs):
            nonlocal api_count
            calls.append(args)
            self.assertTrue(kwargs["capture_output"])
            self.assertFalse(kwargs["check"])
            status, output = 0, ""
            if args == ["git", "rev-parse", "HEAD"]:
                output = SHA
            elif args[:2] == ["git", "status"]:
                output = dirty
            elif args[:2] == ["gh", "api"]:
                api_count += 1
                current = "b" * 40 if move_after and api_count > move_after else main_sha
                output = json.dumps({"sha": current, "commit": {"verification": {"verified": signed}}})
            elif args[0] == "terragrunt" and args[-2:] == ["stack", "generate"]:
                pass
            elif args[0] == "terragrunt" and "plan" in args:
                unit = Path(args[args.index("--working-dir") + 1]).name
                status = plan_status if unit == fail_unit else 0
                output = "synthetic-private-plan"
            else:
                raise AssertionError("Unexpected command")
            return subprocess.CompletedProcess(args, status, output, "synthetic-private-stderr")

        output = io.StringIO()
        with patch.dict(os.environ, environment or ENVIRONMENT, clear=True), \
                patch.object(MODULE.subprocess, "run", side_effect=run), \
                redirect_stdout(output), redirect_stderr(output):
            status = MODULE.main()
        self.assertNotIn("synthetic-private", output.getvalue())
        self.assertNotIn(ENVIRONMENT["ARM_CLIENT_ID"], output.getvalue())
        return status, calls, output.getvalue()

    def test_all_four_complete_resources_refresh_without_mutation(self):
        status, calls, output = self.run_script()
        self.assertEqual(status, 0, output)
        plans = [args for args in calls if "plan" in args]
        self.assertEqual([Path(args[args.index("--working-dir") + 1]).name for args in plans],
                         ["fleet", "fleet-pilot-user", "grafana", "octelium"])
        for args in plans:
            self.assertEqual(args[args.index("plan") + 1:],
                             ["-input=false", "-lock=false", "-refresh=true", "-detailed-exitcode", "-no-color"])
        for args in calls:
            self.assertFalse(set(args) & {"apply", "import", "destroy", "state", "-refresh-only", "-target"})

    def test_drift_and_authentication_failures_stop_later_units(self):
        for code in (1, 2):
            for unit in MODULE.UNITS:
                with self.subTest(code=code, unit=unit):
                    status, calls, output = self.run_script(fail_unit=unit, plan_status=code)
                    self.assertEqual(status, 1)
                    plans = [args for args in calls if "plan" in args]
                    self.assertEqual(len(plans), MODULE.UNITS.index(unit) + 1)
                    self.assertIn("category=drift" if code == 2 else "category=command-failed", output)

    def test_invalid_oidc_or_dispatch_context_never_reaches_provider(self):
        for key in ENVIRONMENT:
            with self.subTest(missing=key):
                environment = {name: value for name, value in ENVIRONMENT.items() if name != key}
                status, calls, _ = self.run_script(environment=environment)
                self.assertEqual(status, 1)
                self.assertEqual(calls, [])
        for key, value in (("ARM_CLIENT_SECRET", "synthetic-private-secret"),
                           ("GITHUB_REF", "refs/heads/other"), ("EXPECTED_SHA", "b" * 40),
                           ("ARM_USE_CLI", "true"), ("ARM_USE_MSI", "true"),
                           ("ARM_CLIENT_ID", "invalid")):
            with self.subTest(key=key):
                status, calls, _ = self.run_script(environment={**ENVIRONMENT, key: value})
                self.assertEqual(status, 1)
                self.assertEqual(calls, [])

    def test_stale_unsigned_and_dirty_main_stop_before_planning(self):
        for options in ({"main_sha": "b" * 40}, {"signed": False}, {"dirty": "?? file\n"}):
            with self.subTest(options=options):
                status, calls, _ = self.run_script(**options)
                self.assertEqual(status, 1)
                self.assertFalse(any(args[0] == "terragrunt" for args in calls))

    def test_main_movement_stops_remaining_plans(self):
        status, calls, _ = self.run_script(move_after=2)
        self.assertEqual(status, 1)
        self.assertEqual(len([args for args in calls if "plan" in args]), 1)

    def test_command_exception_withholds_private_details(self):
        with patch.object(MODULE.subprocess, "run", side_effect=OSError("synthetic-private")):
            with self.assertRaises(MODULE.Failure) as failure:
                MODULE.command(["terragrunt", "plan"], "Entra unit fleet")
        self.assertNotIn("synthetic-private", str(failure.exception))

    def test_only_fixed_error_categories_are_reported(self):
        for marker, expected in (("Authorization_RequestDenied", "entra-authorization-denied"),
                                 ("AADSTS700213", "entra-authentication-failed"),
                                 ("AccessDeniedException", "access-denied"),
                                 ("synthetic-private", "command-failed")):
            with self.subTest(marker=marker):
                result = subprocess.CompletedProcess([], 1, "synthetic-private", marker + " synthetic-private")
                with patch.object(MODULE.subprocess, "run", return_value=result):
                    with self.assertRaises(MODULE.Failure) as failure:
                        MODULE.command(["terragrunt", "plan"], "Entra unit fleet")
                self.assertEqual(str(failure.exception),
                                 "ENTRA_VERIFY_FAILURE stage=entra-unit-fleet category=" + expected)

    def test_workflow_reports_only_complete_allowlisted_failure_markers(self):
        workflow = (MODULE.ROOT / ".github/workflows/entra-oidc-verify.yml").read_text()
        start = workflow.index("          import re\n")
        code = textwrap.dedent(workflow[start:workflow.index("          PY\n", start)])
        marker = "ENTRA_VERIFY_FAILURE stage=entra-unit-fleet category=entra-authorization-denied"
        with tempfile.NamedTemporaryFile(mode="w") as private_log:
            private_log.write("synthetic-private\n" + marker + "\n" + marker + " synthetic-private\n")
            private_log.write("ENTRA_VERIFY_FAILURE stage=synthetic-private category=command-failed\n")
            private_log.flush()
            result = subprocess.run([sys.executable, "-I", "-c", code, private_log.name],
                                    capture_output=True, text=True, check=True, timeout=5)
        self.assertEqual(result.stdout, "::error::" + marker + "\n")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
