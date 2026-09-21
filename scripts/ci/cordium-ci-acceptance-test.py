#!/usr/bin/env python3
"""Reject false authorization evidence without obtaining credentials or calling a cluster."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "acceptance", Path(__file__).resolve().parents[1] / "cordium-ci-acceptance.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
SHA = "a" * 40
REPOSITORY = "Stuhlmuller/homelab"
DENIED_REF = "refs/heads/codex/cordium-oidc-denial"
USAGE = "Usage:\n  octelium login [flags]\n\nFlags:\n  -h, --help\n"


def environment(mode):
    ref = DENIED_REF if mode == "deny-ref" else "refs/heads/main"
    workflow = "cordium-login-denial.yml" if mode == "deny-workflow" else "cordium-check.yml"
    return {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_OWNER_ID": "252389862", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": ref, "GITHUB_SHA": SHA,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/{workflow}@{ref}",
    }


class Denials(unittest.TestCase):
    def response(self, mode, *, code=None):
        code = code or ("Unauthenticated" if mode == "deny-ref" else "PermissionDenied")
        description = "Octelium: Unauthorized" if mode == "forbidden-method" else ""
        raw = f"rpc error: code = {code} desc = {description}"
        formatted = raw if mode == "forbidden-method" else f"gRPC error {code}: {description}"
        return subprocess.CompletedProcess([], 1, formatted + "\n", "Error: " + raw + "\n" + USAGE)

    def test_only_case_specific_exact_server_errors_are_evidence(self):
        for mode in ("deny-ref", "deny-workflow", "forbidden-method"):
            self.assertTrue(acceptance.is_expected_denial(self.response(mode), mode, USAGE))
        self.assertFalse(acceptance.is_expected_denial(
            self.response("deny-ref", code="PermissionDenied"), "deny-ref", USAGE))

    def test_transport_proxy_tls_and_success_cannot_pass(self):
        for mode in ("deny-ref", "deny-workflow", "forbidden-method"):
            for message in (
                "rpc error: code = Unavailable desc = connection refused",
                "rpc error: code = PermissionDenied desc = unexpected HTTP status code received from server: 403 (Forbidden)",
                "x509: certificate signed by unknown authority",
                "context deadline exceeded",
            ):
                self.assertFalse(acceptance.is_expected_denial(
                    subprocess.CompletedProcess([], 1, message + "\n", message + "\n"), mode, USAGE))
            result = self.response(mode)
            result.returncode = 0
            self.assertFalse(acceptance.is_expected_denial(result, mode, USAGE))

    def test_mixed_output_and_forged_usage_do_not_pass(self):
        for stream in ("stdout", "stderr"):
            result = self.response("deny-workflow")
            setattr(result, stream, getattr(result, stream) + "transport failed\n")
            self.assertFalse(acceptance.is_expected_denial(result, "deny-workflow", USAGE))
        result = self.response("forbidden-method")
        result.stdout = "\x1b[31m" + result.stdout
        self.assertFalse(acceptance.is_expected_denial(result, "forbidden-method", USAGE))
        self.assertFalse(acceptance.is_expected_denial(
            self.response("deny-ref"), "deny-ref", USAGE + "extra\n"))

    def exercise(self, mode, *, returncode=1, timeout=False, logout_fails=False, interrupted=False, expired=False):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            self.assertTrue(kwargs["capture_output"])
            self.assertLessEqual(kwargs["timeout"], 60)
            if command[-1] == "--help":
                return subprocess.CompletedProcess(command, 0, "Pinned client\n\n" + USAGE, "")
            if "logout" in command:
                if logout_fails:
                    raise subprocess.CalledProcessError(1, command)
                return subprocess.CompletedProcess(command, 0, "", "")
            if interrupted:
                raise SystemExit(143)
            if timeout:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            response = self.response(mode)
            response.returncode = returncode
            return response

        output = io.StringIO()
        self.last_calls = calls
        with patch.dict(os.environ, environment(mode), clear=True), patch.object(
                sys, "argv", ["acceptance", "--mode", mode, "--homedir", "/tmp/private-login",
                              "--deadline", str(1700000030 if expired else 1700000600)]), patch.object(
                acceptance.signal, "signal"), patch.object(
                acceptance.time, "time", return_value=1700000000), patch.object(
                acceptance.subprocess, "run", side_effect=run), contextlib.redirect_stdout(
                output), contextlib.redirect_stderr(output):
            result = acceptance.main()
        self.assertNotIn("gRPC", output.getvalue())
        self.assertNotIn("private-login", output.getvalue())
        return result, calls

    def test_denial_modes_never_call_cordium_or_create_workspaces(self):
        for mode in ("deny-ref", "deny-workflow"):
            result, calls = self.exercise(mode)
            self.assertEqual(result, 0)
            self.assertTrue(all(command[0] == "octelium" for command in calls))
            self.assertFalse(any("create" in command for command in calls))
            self.assertEqual(sum("logout" in command for command in calls), 1)

    def test_unexpected_login_success_logs_out_and_fails(self):
        for failure in (False, True):
            result, calls = self.exercise("deny-workflow", returncode=0, logout_fails=failure)
            self.assertNotEqual(result, 0)
            self.assertEqual(sum("logout" in command for command in calls), 1)
            self.assertFalse(any("cordium" in command for command in calls))

    def test_timeout_is_not_authorization_evidence(self):
        result, calls = self.exercise("deny-ref", timeout=True)
        self.assertNotEqual(result, 0)
        self.assertEqual(sum("logout" in command for command in calls), 1)

    def test_cleanup_runs_on_interruption_and_cleanup_failure_stays_failed(self):
        with self.assertRaises(SystemExit) as interrupted:
            self.exercise("deny-workflow", interrupted=True)
        self.assertEqual(interrupted.exception.code, 143)
        self.assertEqual(sum("logout" in command for command in self.last_calls), 1)
        self.assertNotEqual(self.exercise("deny-ref", logout_fails=True)[0], 0)

    def test_exhausted_setup_does_not_attempt_login(self):
        result, calls = self.exercise("deny-workflow", expired=True)
        self.assertNotEqual(result, 0)
        self.assertEqual(calls, [])

    def test_forbidden_probe_is_the_fixed_read_only_listspace_call(self):
        result, calls = self.exercise("forbidden-method")
        self.assertEqual(result, 0)
        self.assertEqual(calls[-1][-4:], ["get", "space", "--out", "json"])
        self.assertEqual(calls[-1][0], "cordium")
        self.assertFalse(any("create" in command or "exec" in command for command in calls))


class Context(unittest.TestCase):
    def test_real_fixed_contexts_are_required(self):
        for mode in ("checks", "force-failure", "forbidden-method", "deny-ref", "deny-workflow"):
            acceptance.verify_context(mode, environment(mode))
        for mode in ("checks", "force-failure", "forbidden-method"):
            with self.assertRaises(ValueError):
                acceptance.verify_context(mode, environment("deny-ref"))
        with self.assertRaises(ValueError):
            acceptance.verify_context("deny-ref", environment("checks"))
        with self.assertRaises(ValueError):
            acceptance.verify_context("deny-workflow", environment("checks"))

    def test_changed_claim_context_and_native_overrides_fail_before_transport(self):
        for key, value in (
            ("GITHUB_ACTIONS", "false"), ("GITHUB_REPOSITORY", "other/repo"),
            ("GITHUB_REPOSITORY_OWNER_ID", "0"), ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_SHA", "not-a-sha"), ("GITHUB_REF", "refs/heads/other"),
            ("GITHUB_WORKFLOW_REF", "other.yml@refs/heads/main"),
            ("OCTELIUM_INSECURE_TLS", "true"), ("OCTELIUM_AUTH_PROXY_SOCKET", "/tmp/proxy"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                acceptance.verify_context("checks", {**environment("checks"), key: value})


class Workflow(unittest.TestCase):
    def job(self, filename="cordium-check.yml", job="check"):
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows" / filename
        return json.loads(subprocess.check_output(["yq", "-o=json", f".jobs.{job}", str(workflow)], text=True))

    def test_dispatch_gate_keeps_workspace_modes_on_main(self):
        run = self.job()["steps"][0]["run"]
        for mode in ("checks", "force-failure", "forbidden-method", "deny-ref", "arbitrary"):
            for ref in ("refs/heads/main", DENIED_REF, "refs/heads/other"):
                for expected in (SHA, "b" * 40):
                    allowed = (expected == SHA and
                               ((mode == "deny-ref" and ref == DENIED_REF) or
                                (mode in ("checks", "force-failure", "forbidden-method")
                                 and ref == "refs/heads/main")))
                    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", run],
                                            env={**os.environ, "CHECK_MODE": mode, "ACTUAL_REF": ref,
                                                 "ACTUAL_SHA": SHA, "EXPECTED_SHA": expected},
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode == 0, allowed, (mode, ref, expected))

    def test_intentional_failure_stays_failed_and_requires_cleanup_receipt(self):
        run = self.job()["steps"][-1]["run"]
        marker = "Expected remote exit 42 and disposable workspace deletion verified."
        for status, receipt, expected in ((42, True, 42), (42, False, 1), (1, True, 1), (0, True, 1)):
            with tempfile.TemporaryDirectory() as temporary:
                binary = Path(temporary) / "nix"
                binary.write_text("#!/bin/bash\nprintf '%s\\n' 'private-native-output'\n" +
                                  (f"printf '%s\\n' '{marker}'\n" if receipt else "") +
                                  f"exit {status}\n")
                binary.chmod(0o700)
                result = subprocess.run(
                    ["bash", "-e", "-o", "pipefail", "-c", run], capture_output=True, text=True, timeout=5,
                    env={**os.environ, "CHECK_MODE": "force-failure", "RUNNER_TEMP": temporary,
                         "PATH": temporary + os.pathsep + os.environ["PATH"]})
                self.assertEqual(result.returncode, expected)
                self.assertNotIn("private-native-output", result.stdout + result.stderr)
                if expected == 42:
                    self.assertIn("::notice::" + marker, result.stdout)
                self.assertEqual(sorted(path.name for path in Path(temporary).iterdir()), ["nix"])

    def test_login_denial_keeps_fixed_mode_and_cleanup_budget(self):
        job = self.job("cordium-login-denial.yml", "deny")
        self.assertLess(sum(step["timeout-minutes"] for step in job["steps"]), job["timeout-minutes"])
        self.assertIn("deny-workflow", job["steps"][-1]["run"])
        self.assertNotIn("cordium-check.py", job["steps"][-1]["run"])
        self.assertIn("7 * 60", job["steps"][-1]["run"])


if __name__ == "__main__":
    unittest.main()
