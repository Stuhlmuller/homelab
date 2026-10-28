#!/usr/bin/env python3
"""Ensure Bulldozer's protected credential lane writes only its fixed keys."""

import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("credential", ROOT / "scripts/bulldozer-credential.py")
credential = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credential)


class CredentialTest(unittest.TestCase):
    def test_fixed_targets_and_validation_before_write(self):
        key = "-----BEGIN TEST KEY-----\ntest\n-----END TEST KEY-----\n"
        calls = []
        paths = []
        writes = []

        def run(args, **kwargs):
            calls.append((args, kwargs))
            if args[:3] == ["aws", "ssm", "put-parameter"]:
                path = Path(args[args.index("--cli-input-json") + 1].removeprefix("file://"))
                paths.append(path)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertNotIn(key, str(args))
                self.assertNotIn("BULLDOZER_APP_ID", credential.os.environ)
                self.assertNotIn("BULLDOZER_PRIVATE_KEY", credential.os.environ)
                writes.append(json.loads(path.read_text()))

        with patch.dict(credential.os.environ, {"BULLDOZER_APP_ID": "123", "BULLDOZER_PRIVATE_KEY": key}), \
                patch.object(credential.subprocess, "run", side_effect=run):
            credential.main()
        self.assertEqual(calls[0][0][:2], ["openssl", "pkey"])
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual([item["Name"] for item in writes], [
            "/homelab/bulldozer/github-app/integration-id",
            "/homelab/bulldozer/github-app/private-key",
        ])
        self.assertEqual([item["Value"] for item in writes], ["123", key])
        self.assertTrue(all(item["Type"] == "SecureString" and item["Overwrite"] for item in writes))

        calls.clear()
        with patch.dict(credential.os.environ, {"BULLDOZER_APP_ID": "bad", "BULLDOZER_PRIVATE_KEY": key}), \
                patch.object(credential.subprocess, "run", side_effect=run), \
                self.assertRaises(ValueError):
            credential.main()
        self.assertEqual(calls, [])

    def test_payload_removed_after_aws_failure(self):
        key = "-----BEGIN TEST KEY-----\ntest\n-----END TEST KEY-----\n"
        paths = []

        def fail_write(args, **kwargs):
            if args[:3] == ["aws", "ssm", "put-parameter"]:
                paths.append(Path(args[args.index("--cli-input-json") + 1].removeprefix("file://")))
                raise subprocess.CalledProcessError(1, args)

        with patch.dict(credential.os.environ, {"BULLDOZER_APP_ID": "123", "BULLDOZER_PRIVATE_KEY": key}), \
                patch.object(credential.subprocess, "run", side_effect=fail_write), \
                self.assertRaises(subprocess.CalledProcessError):
            credential.main()
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())


if __name__ == "__main__":
    unittest.main()
