#!/usr/bin/env python3
"""Exercise the private Harbor mirror credential materializer offline."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "mirror_credential", ROOT / "scripts/talos-harbor-mirror-credential.py"
)
credential = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(credential)
SHA = "a" * 40
PASSWORD = "fixture"


class MirrorCredentialTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name).resolve()
        self.repo = base / "repo"
        self.repo.mkdir()
        (self.repo / ".git").touch()
        self.private = base / "private"
        self.private.mkdir()
        self.private.chmod(0o700)

    def command(self, *, stale=False):
        calls = []
        checks = 0

        def run(arguments, **kwargs):
            nonlocal checks
            calls.append((arguments, kwargs))
            if arguments[:2] == ["git", "status"]:
                checks += 1
                return ""
            if arguments == ["git", "rev-parse", "HEAD"]:
                return SHA + "\n"
            if arguments[:2] == ["git", "ls-remote"]:
                return ("b" * 40 if stale and checks > 1 else SHA) + "\trefs/heads/main\n"
            self.assertEqual(arguments[:8], [
                "aws", "--profile", "operator", "--region", credential.REGION,
                "--no-cli-pager", "--no-cli-auto-prompt", "ssm",
            ])
            self.assertEqual(arguments[8:], ["get-parameter", "--name", credential.PARAMETER,
                                             "--with-decryption", "--output", "json"])
            return json.dumps({"Parameter": {"Name": credential.PARAMETER,
                                               "Type": "SecureString", "Value": PASSWORD}})

        return run, calls

    def test_materializes_only_the_fixed_parameter_after_two_main_checks(self):
        run, calls = self.command()
        output = io.StringIO()
        with patch.object(credential, "ROOT", self.repo), patch.object(credential, "command", side_effect=run), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            target = credential.materialize("operator", self.private, SHA)
        self.assertEqual(target, self.private / credential.FILENAME)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(json.loads(target.read_text()), {"username": credential.USERNAME, "password": PASSWORD})
        self.assertNotIn(PASSWORD, output.getvalue())
        self.assertEqual(sum(arguments[:2] == ["git", "status"] for arguments, _ in calls), 2)
        self.assertEqual(sum(arguments[:2] == ["aws", "--profile"] for arguments, _ in calls), 1)

    def test_stale_main_preserves_existing_credential_file(self):
        target = self.private / credential.FILENAME
        target.write_text('{"username":"robot$mirror+pull","password":"previous"}\n')
        target.chmod(0o600)
        original = target.read_bytes()
        run, _ = self.command(stale=True)
        with patch.object(credential, "ROOT", self.repo), patch.object(credential, "command", side_effect=run):
            with self.assertRaises(credential.CredentialError):
                credential.materialize("operator", self.private, SHA)
        self.assertEqual(target.read_bytes(), original)

    def test_private_destination_and_existing_file_are_strict(self):
        with patch.object(credential, "ROOT", self.repo):
            for path in (Path("relative"), self.repo):
                with self.subTest(path=path), self.assertRaises(credential.CredentialError):
                    credential.private_directory(path)
            self.private.chmod(0o755)
            with self.assertRaises(credential.CredentialError):
                credential.private_directory(self.private)
            self.private.chmod(0o700)
            unsafe = self.private / credential.FILENAME
            unsafe.symlink_to("missing")
            with self.assertRaises(credential.CredentialError):
                credential.write_credential(self.private, PASSWORD)

    def test_aws_child_environment_excludes_credentials_and_proxies(self):
        result = subprocess.CompletedProcess([], 1, PASSWORD, PASSWORD)
        inherited = {
            "AWS_PROFILE": "wrong",
            "AWS_SECRET_ACCESS_KEY": PASSWORD,
            "HTTP_PROXY": "http://proxy.invalid:8080",
            "HTTPS_PROXY": "http://proxy.invalid:8080",
            "ALL_PROXY": "http://proxy.invalid:8080",
            "NO_PROXY": "internal.invalid",
            "http_proxy": "http://proxy.invalid:8080",
            "https_proxy": "http://proxy.invalid:8080",
            "all_proxy": "http://proxy.invalid:8080",
            "no_proxy": "internal.invalid",
        }
        with patch.dict(os.environ, inherited), \
                patch.object(credential.subprocess, "run", return_value=result) as run:
            with self.assertRaises(credential.CredentialError) as error:
                credential.command(["aws", "ssm", "get-parameter"])
        self.assertNotIn(PASSWORD, str(error.exception))
        environment = run.call_args.kwargs["env"]
        for key in inherited:
            self.assertNotIn(key, environment)

    def test_main_never_reports_private_exception_data(self):
        output = io.StringIO()
        with patch.object(credential, "materialize", side_effect=ValueError(PASSWORD)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(credential.main(["--profile", "operator", "--directory", str(self.private),
                                              "--expected-sha", SHA]), 1)
        self.assertNotIn(PASSWORD, output.getvalue())


if __name__ == "__main__":
    unittest.main()
