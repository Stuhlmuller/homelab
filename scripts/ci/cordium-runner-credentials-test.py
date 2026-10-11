#!/usr/bin/env python3
"""Prove fixed-slot credential intake validates both inputs before any write."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("credentials", Path(__file__).resolve().parents[1] / "cordium-runner-credentials.py")
credentials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credentials)


class Intake(unittest.TestCase):
    def exercise(self, *, invalid_slot=False, invalid_native=False, wrong_app=False, second_write_fails=False):
        writes = []
        events = []
        key = "private-key-fixture"
        token = "native-token-fixture"
        environment = {"CORDIUM_RUNNER_APP_PRIVATE_KEY": key, "CORDIUM_RUNNER_AUTH_TOKEN": token}

        def command(*args, env=None):
            self.assertNotIn(key, args)
            self.assertNotIn(token, args)
            self.assertFalse(set(environment) & set(env))
            self.assertNotIn("OCTELIUM_AUTH_TOKEN", env)
            if "describe-parameters" in args:
                name = args[args.index("--parameter-filters") + 1].split("Values=")[1]
                events.append("metadata")
                return json.dumps({"Parameters": [{"Name": name, "Type": "String" if invalid_slot else "SecureString", "KeyId": "alias/aws/ssm", "Tier": "Standard"}]}).encode()
            self.assertIn("put-parameter", args)
            path = Path(args[args.index("--cli-input-json") + 1].removeprefix("file://"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            payload = json.loads(path.read_text())
            self.assertIn(payload["Name"], credentials.PARAMETERS.values())
            writes.append(payload["Name"])
            events.append("write")
            if second_write_fails and len(writes) == 2:
                raise RuntimeError("private command failure")
            return b'{"Version":2}'

        def native(value, directory):
            self.assertEqual(value, token)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            events.append("native")
            if invalid_native:
                raise RuntimeError("wrong identity")

        error = None
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), patch.object(sys, "argv", ["intake"]), \
             patch.object(credentials, "context"), patch.object(credentials, "command", side_effect=command), \
             patch.object(credentials, "validate_native", side_effect=native), \
             patch.object(credentials.github, "app_jwt", return_value="fixture"), \
             patch.object(credentials.github, "github_client", return_value=lambda *_: {"id": 1 if wrong_app else 5270069}), \
             contextlib.redirect_stdout(output):
            try:
                credentials.inject()
            except RuntimeError as caught:
                error = caught
        self.assertNotIn(key, output.getvalue())
        self.assertNotIn(token, output.getvalue())
        return error, writes, events

    def test_both_validations_precede_writes_to_only_the_declared_slots(self):
        error, writes, events = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(writes, list(credentials.PARAMETERS.values()))
        self.assertEqual(events, ["metadata", "metadata", "native", "write", "write"])

    def test_invalid_metadata_identity_or_app_never_writes(self):
        for options in ({"invalid_slot": True}, {"invalid_native": True}, {"wrong_app": True}):
            error, writes, _ = self.exercise(**options)
            self.assertIsNotNone(error)
            self.assertEqual(writes, [])

    def test_partial_write_is_failure_not_success(self):
        error, writes, _ = self.exercise(second_write_fails=True)
        self.assertIsNotNone(error)
        self.assertEqual(len(writes), 2)

    def test_context_refuses_untrusted_events_before_git_or_transport(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(credentials.github, "verify_reviewed_main") as guard:
            with self.assertRaises(RuntimeError):
                credentials.context()
            guard.assert_not_called()

    def test_native_validation_strips_unrelated_credentials_and_always_logs_out(self):
        for wrong_user, failed_login in ((False, False), (True, False), (False, True)):
            calls = []
            def command(*args, env=None):
                calls.append(args)
                if args == ("octelium", "version"):
                    return b"gitCommit: 5e4eb3e36911ba4f66f5f43df2cc4b264211c4ce\n"
                self.assertFalse(any(key.startswith("AWS_") for key in env))
                self.assertNotIn("GH_TOKEN", env)
                if "logout" in args:
                    self.assertNotIn("OCTELIUM_AUTH_TOKEN", env)
                    return b""
                self.assertEqual(env["OCTELIUM_AUTH_TOKEN"], "native-fixture")
                if "login" in args:
                    if failed_login:
                        raise RuntimeError("private login failure")
                    return b""
                return json.dumps({"domain": "stinkyboi.com", "user": {
                    "metadata": {"name": "operator" if wrong_user else "homelab-cordium-runners"},
                    "spec": {"type": "WORKLOAD", "authorization": {"policies": ["homelab-cordium-runner-execution"]}}}}).encode()
            environment = {"AWS_SECRET_ACCESS_KEY": "private-fixture", "GH_TOKEN": "private-fixture"}
            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(credentials, "command", side_effect=command), \
                 patch.object(credentials.native, "native_transport", return_value=contextlib.nullcontext(environment)):
                if wrong_user or failed_login:
                    with self.assertRaises(RuntimeError):
                        credentials.validate_native("native-fixture", Path(directory))
                else:
                    credentials.validate_native("native-fixture", Path(directory))
            self.assertEqual(calls[-1][-1], "logout")


if __name__ == "__main__":
    unittest.main()
