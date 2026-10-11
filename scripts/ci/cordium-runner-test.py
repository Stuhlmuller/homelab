#!/usr/bin/env python3
"""Exercise one-job credential handling and independent cleanup without live APIs."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("runner", Path(__file__).resolve().parents[1] / "cordium-runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
SHA = "a" * 40
JIT = "cHJpdmF0ZS1qaXQtZml4dHVyZQ=="


class Lifecycle(unittest.TestCase):
    def exercise(self, *, failure=False, wrong_sha=False, retained=False, cleanup_fails=False, invalid_name=False, invalid_jit=False):
        calls = []
        api_calls = []
        present = [True]
        lists = [0]

        def command(arguments, **kwargs):
            args = arguments[5:]
            calls.append((args, kwargs))
            output = b""
            if args[:2] == ["get", "workspace"] and args[2] == "--out":
                lists[0] += 1
                output = json.dumps({"items": [{"metadata": {"name": "old"}}] if retained and lists[0] == 1 else []}).encode()
            elif args[:2] == ["create", "workspace"]:
                output = json.dumps({"metadata": {"name": "--all" if invalid_name else "abc"}}).encode()
            elif args[0] == "get":
                output = b'{"status":{"state":"RUNNING"}}'
            elif "rev-parse" in args:
                output = ("b" * 40 if wrong_sha else SHA).encode()
            elif args[0] == "exec":
                self.assertEqual(kwargs["input"], JIT.encode())
                self.assertNotIn(JIT, args)
                self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
                self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
                if failure:
                    raise subprocess.CalledProcessError(17, arguments)
            elif args[0] == "delete" and cleanup_fails:
                raise subprocess.CalledProcessError(1, arguments)
            return subprocess.CompletedProcess(arguments, 0, output, b"")

        def api(method, path, body=None):
            api_calls.append((method, path, body))
            if method == "POST":
                self.assertEqual(body["labels"], ["self-hosted", "Linux", "X64", "cordium-canary"])
                return {"runner": {"id": 23, "name": "cordium-abc"}, "encoded_jit_config": "invalid secret!" if invalid_jit else JIT}
            if method == "DELETE":
                present[0] = False
                return None
            if present[0]:
                return {"id": 23}
            raise RuntimeError("GitHub request failed with HTTP 404; response withheld")

        output = io.StringIO()
        error = None
        with patch.object(runner.subprocess, "run", side_effect=command), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                runner.provision(api, ["cordium", "--homedir", "/private/fixture", "--domain", "stinkyboi.com"], SHA)
            except (RuntimeError, subprocess.CalledProcessError) as caught:
                error = caught
        self.assertNotIn(JIT, output.getvalue())
        return error, calls, api_calls

    def test_one_job_receives_only_jit_stdin_then_disposes_workspace_and_runner(self):
        error, calls, api_calls = self.exercise()
        self.assertIsNone(error)
        self.assertIn(["delete", "workspace", "abc"], [args for args, _ in calls])
        self.assertIn(("DELETE", "/repos/Stuhlmuller/homelab/actions/runners/23", None), api_calls)

    def test_failure_and_invalid_jit_still_clean_both_resources(self):
        for options in ({"failure": True}, {"invalid_jit": True}, {"cleanup_fails": True}):
            error, calls, api_calls = self.exercise(**options)
            self.assertIsNotNone(error)
            self.assertIn(["delete", "workspace", "abc"], [args for args, _ in calls])
            self.assertIn(("DELETE", "/repos/Stuhlmuller/homelab/actions/runners/23", None), api_calls)

    def test_wrong_checkout_or_retained_inventory_prevents_registration(self):
        for options in ({"wrong_sha": True}, {"retained": True}, {"invalid_name": True}):
            error, calls, api_calls = self.exercise(**options)
            self.assertIsNotNone(error)
            self.assertEqual(api_calls, [])
            if not options.get("wrong_sha"):
                self.assertFalse(any(args[0] == "delete" for args, _ in calls))

    def test_only_exact_runner_404_is_absence(self):
        with self.assertRaises(RuntimeError):
            runner.runner_present(Mock(side_effect=RuntimeError("GitHub request failed with HTTP 403; response withheld")), "Stuhlmuller/homelab", 23)

    def test_shared_github_client_accepts_empty_delete_response(self):
        response = io.BytesIO()
        response.status = 204
        opener = Mock()
        opener.open.return_value = response
        with patch.object(runner.github_operator.urllib.request, "build_opener", return_value=opener):
            self.assertIsNone(runner.github_operator.github_client("fixture")("DELETE", "/repos/Stuhlmuller/homelab/actions/runners/23"))

    def test_disabled_pool_rejects_before_reading_key_or_opening_clients(self):
        with patch.object(sys, "argv", ["runner", "--expected-sha", SHA, "--app-key-file", "/missing/key", "--homedir", "/missing/login"]), \
             patch.object(runner.github_operator, "verify_reviewed_main"), \
             patch.object(runner.github_operator, "command", return_value=b""), \
             patch.object(runner.github_operator, "app_jwt") as signer, \
             self.assertRaisesRegex(RuntimeError, "registration is disabled"):
            runner.main()
        signer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
