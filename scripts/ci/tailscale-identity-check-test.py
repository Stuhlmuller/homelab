#!/usr/bin/env python3
"""Offline checks for pre-signed authkey scope and private status handling."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("identity", Path(__file__).with_name("tailscale-identity-check.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def status(identity="plan"):
    return {"BackendState": "Running", "Self": {"Online": True, "Tags": [f"tag:homelab-ci-{identity}"]},
            "CurrentTailnet": {"MagicDNSSuffix": MODULE.TAILNET}, "Private": "synthetic-private-data"}


class IdentityTest(unittest.TestCase):
    def check(self, result=None, error=None, identity="plan"):
        output = io.StringIO()
        completed = subprocess.CompletedProcess([], 0, json.dumps(result), "synthetic-private-stderr")
        with patch.object(MODULE.subprocess, "run", return_value=completed, side_effect=error) as command:
            with redirect_stdout(output), redirect_stderr(output):
                code = MODULE.main([identity])
        self.assertNotIn("synthetic-private", output.getvalue())
        self.assertEqual(command.call_args.args[0], ["tailscale", "status", "--json"])
        self.assertTrue(command.call_args.kwargs["capture_output"])
        self.assertEqual(command.call_args.kwargs["timeout"], 20)
        return code

    def test_accepts_only_each_exact_identity(self):
        for identity in ("plan", "apply", "cordium"):
            self.assertEqual(self.check(status(identity), identity=identity), 0)

    def test_rejects_wrong_or_broader_tags(self):
        for tags in ([], ["tag:homelab-ci-apply"], ["tag:homelab-ci-plan", "tag:homelab-ci-apply"], None):
            data = status()
            data["Self"]["Tags"] = tags
            self.assertEqual(self.check(data), 1)

    def test_rejects_disconnected_and_foreign_tailnet(self):
        for field, value in (("BackendState", "Stopped"), ("Self", {"Online": False}),
                             ("CurrentTailnet", {"MagicDNSSuffix": "other.ts.net"})):
            data = copy.deepcopy(status())
            data[field] = value
            self.assertEqual(self.check(data), 1)

    def test_rejects_malformed_status_without_traceback(self):
        for data in (None, [], {}, {"Self": [], "CurrentTailnet": "private"}):
            self.assertEqual(self.check(data), 1)

    def test_command_failures_withhold_output(self):
        for error in (FileNotFoundError("synthetic-private-path"),
                      subprocess.CalledProcessError(1, [], output="synthetic-private-output"),
                      subprocess.TimeoutExpired([], 20, output="synthetic-private-timeout"),
                      ValueError("synthetic-private-invalid-json")):
            self.assertEqual(self.check(error=error), 1)


if __name__ == "__main__":
    unittest.main()
