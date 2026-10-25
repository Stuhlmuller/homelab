#!/usr/bin/env python3
"""Ensure Bulldozer's protected credential lane writes only its fixed keys."""

import importlib.util
import json
from pathlib import Path
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

        def run(args, **kwargs):
            calls.append((args, kwargs))

        with patch.dict(credential.os.environ, {"BULLDOZER_APP_ID": "123", "BULLDOZER_PRIVATE_KEY": key}), \
                patch.object(credential.subprocess, "run", side_effect=run):
            credential.main()
        self.assertEqual(calls[0][0][:2], ["openssl", "pkey"])
        writes = [json.loads(kwargs["input"]) for args, kwargs in calls[1:]]
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


if __name__ == "__main__":
    unittest.main()
