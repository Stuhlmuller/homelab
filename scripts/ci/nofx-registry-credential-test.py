#!/usr/bin/env python3
"""Offline behavior tests: only a verified narrow credential reaches SSM."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "nofx-registry-credential.py"
spec = importlib.util.spec_from_file_location("nofx_registry_credential", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
# Deliberately synthetic; constructed so scanning never mistakes it for a token.
TOKEN = "ghp_" + "x" * 36


class Response:
    def __init__(self, login="rstuhlmuller", scopes="read:packages"):
        self.headers = {"X-OAuth-Scopes": scopes}
        self.login = login

    def read(self, maximum):
        return json.dumps({"login": self.login}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class CredentialTests(unittest.TestCase):
    def test_accepts_only_dedicated_owner_and_scope(self):
        for login, scopes, valid in [
            ("rstuhlmuller", "read:packages", True),
            ("other-user", "read:packages", False),
            ("rstuhlmuller", "read:packages, repo", False),
            ("rstuhlmuller", "read:packages, write:packages", False),
            ("rstuhlmuller", "read:packages, delete:packages", False),
            ("rstuhlmuller", "read:packages, workflow", False),
            ("rstuhlmuller", "", False),
        ]:
            with self.subTest(login=login, scopes=scopes), patch.object(module.urllib.request, "build_opener") as opener:
                opener.return_value.open.return_value = Response(login, scopes)
                if valid:
                    module.github_user(TOKEN)
                else:
                    with self.assertRaises(module.Failure):
                        module.github_user(TOKEN)
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url, "https://api.github.com/user")
                self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")

    def test_subprocess_failure_never_echoes_credentials(self):
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, TOKEN, TOKEN)) as run:
            with self.assertRaises(module.Failure) as failure:
                module.command(["aws", "ssm", "put-parameter"], data=TOKEN)
            self.assertNotIn(TOKEN, str(failure.exception))
            self.assertNotIn(TOKEN, " ".join(run.call_args.args[0]))
            self.assertNotIn("NOFX_GHCR_READ_TOKEN", run.call_args.kwargs["env"])

    def run_rotation(self, *, fail_at=None, argv=None):
        calls = []

        def step(name):
            def operation(*args):
                calls.append(name)
                if name == fail_at:
                    raise module.Failure("synthetic validation failure")
            return operation

        output = io.StringIO()
        with patch.dict(os.environ, {"NOFX_GHCR_READ_TOKEN": TOKEN}), patch.object(sys, "argv", argv or [str(SCRIPT)]), \
                patch.object(module, "validate_context", side_effect=step("context")), \
                patch.object(module, "github_user", side_effect=step("user")), \
                patch.object(module, "parameter_metadata", side_effect=step("parameter")), \
                patch.object(module, "authenticate_images", side_effect=step("images")), \
                patch.object(module, "command", return_value='{"Version": 2}') as command, \
                redirect_stdout(output), redirect_stderr(output):
            status = module.main()
        return status, calls, command, output.getvalue()

    def test_success_validates_twice_before_stdin_only_write(self):
        status, calls, command, output = self.run_rotation()
        self.assertEqual(status, 0)
        self.assertEqual(calls, ["context", "user", "parameter", "images", "context"])
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0], [
            "aws", "ssm", "put-parameter", "--region", "us-west-2",
            "--cli-input-json", "file:///dev/stdin", "--output", "json",
        ])
        payload = json.loads(command.call_args.kwargs["data"])
        self.assertEqual(payload, {"Name": module.PARAMETER, "Type": "SecureString", "KeyId": "alias/aws/ssm", "Value": TOKEN, "Overwrite": True})
        self.assertNotIn(TOKEN, output)

    def test_failed_validation_never_writes_ssm(self):
        for stage in ["context", "user", "parameter", "images"]:
            with self.subTest(stage=stage):
                status, _, command, output = self.run_rotation(fail_at=stage)
                self.assertEqual(status, 1)
                command.assert_not_called()
                self.assertNotIn(TOKEN, output)

    def test_unknown_exception_does_not_leak_secret(self):
        with patch.object(module, "rotate", side_effect=ValueError(TOKEN)), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(module.main(), 1)
        self.assertNotIn(TOKEN, output.getvalue())

    def test_cli_inputs_rejected(self):
        status, calls, command, _ = self.run_rotation(argv=[str(SCRIPT), "alternative-target"])
        self.assertEqual(status, 1)
        self.assertEqual(calls, [])
        command.assert_not_called()

    def test_requires_existing_secure_parameter(self):
        good = {"Name": module.PARAMETER, "Type": "SecureString", "KeyId": "alias/aws/ssm", "Tier": "Standard"}
        for parameters, valid in [([], False), ([good], True), ([good, good], False),
                                  ([dict(good, Type="String")], False),
                                  ([dict(good, KeyId="other-key")], False)]:
            with patch.object(module, "command", return_value=json.dumps({"Parameters": parameters})):
                if valid:
                    module.parameter_metadata()
                else:
                    with self.assertRaises(module.Failure):
                        module.parameter_metadata()

    def test_both_full_images_and_provenance_checked_with_temporary_auth(self):
        paths = []

        def command(args, **kwargs):
            paths.append(Path(args[2]))
            self.assertTrue(paths[-1].is_dir())
            if "login" in args:
                self.assertEqual(kwargs["data"], TOKEN)
                self.assertNotIn(TOKEN, args)
            if "inspect" in args:
                return json.dumps({"org.opencontainers.image.source": "https://github.com/Stuhlmuller/homelab", "org.opencontainers.image.revision": module.SOURCE_SHA})
            return ""

        with patch.object(module, "command", side_effect=command) as run:
            module.authenticate_images(TOKEN)
        pulls = [call.args[0] for call in run.call_args_list if "pull" in call.args[0]]
        self.assertEqual([args[-1] for args in pulls], list(module.IMAGES))
        self.assertTrue(all(not path.exists() for path in paths))

    def test_stale_main_rejected_before_write(self):
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": module.REPO,
               "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": "a" * 40}
        with patch.dict(os.environ, env), patch.object(module, "command", side_effect=["a" * 40, "b" * 40 + "\trefs/heads/main\n"]):
            with self.assertRaises(module.Failure):
                module.validate_context()

    def test_main_advancing_during_pulls_prevents_write(self):
        with patch.dict(os.environ, {"NOFX_GHCR_READ_TOKEN": TOKEN}), patch.object(sys, "argv", [str(SCRIPT)]), \
                patch.object(module, "validate_context", side_effect=[None, module.Failure("stale main")]), \
                patch.object(module, "github_user"), patch.object(module, "parameter_metadata"), \
                patch.object(module, "authenticate_images"), patch.object(module, "command") as command, \
                redirect_stderr(io.StringIO()):
            self.assertEqual(module.main(), 1)
        command.assert_not_called()

    def test_authentication_redirect_rejected(self):
        with self.assertRaises(module.Failure):
            module.NoRedirect().redirect_request(None, None, 302, None, None, "https://unexpected.invalid/")


if __name__ == "__main__":
    unittest.main()
