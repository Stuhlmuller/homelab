#!/usr/bin/env python3
"""Exercise remote failure propagation and disposal without a live workspace."""
import contextlib
import importlib.util
import io
import json
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("cordium_check", Path(__file__).resolve().parents[1] / "cordium-check.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
SHA = "a" * 40


class Lifecycle(unittest.TestCase):
    def exercise(self, *, remote_exit=0, wrong_sha=False, cleanup_fails=False, leftover=False, create_name="abc", preexisting=False):
        commands = []
        lists = 0

        def run(command, **kwargs):
            nonlocal lists
            args = command[5:]
            commands.append(args)
            output = ""
            if args[:2] == ["get", "workspace"] and args[2] == "--out":
                lists += 1
                items = [{"metadata": {"name": "abc"}}] if (preexisting or (leftover and lists > 1)) else []
                output = json.dumps({"items": items})
            elif args[:2] == ["create", "workspace"]:
                self.assertNotIn("--start", args)
                output = json.dumps({"metadata": {"name": create_name}})
            elif args[0] == "get":
                output = json.dumps({"status": {"state": "RUNNING"}})
            elif args[0] == "exec" and "rev-parse" in args:
                output = ("b" * 40 if wrong_sha else SHA) + "\n"
            elif args[0] == "exec" and remote_exit:
                raise subprocess.CalledProcessError(remote_exit, command)
            elif args[0] == "delete" and cleanup_fails:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, output, "")

        previous = signal.getsignal(signal.SIGTERM)
        try:
            with patch.object(sys, "argv", ["cordium-check.py", "--checkout", SHA, "--homedir", "/tmp/test-login"]), patch.object(runner.subprocess, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = runner.main()
        finally:
            signal.signal(signal.SIGTERM, previous)
        return result, commands

    def test_remote_failure_is_preserved_and_cleaned(self):
        result, commands = self.exercise(remote_exit=42)
        self.assertEqual(result, 42)
        self.assertIn(["delete", "workspace", "abc"], commands)
        self.assertEqual(commands[-1], ["get", "workspace", "--out", "json"])

    def test_wrong_checkout_never_runs_checks(self):
        result, commands = self.exercise(wrong_sha=True)
        self.assertNotEqual(result, 0)
        self.assertFalse(any("nix" in command for command in commands))
        self.assertIn(["delete", "workspace", "abc"], commands)

    def test_cleanup_must_succeed_and_prove_absence(self):
        self.assertEqual(self.exercise()[0], 0)
        self.assertNotEqual(self.exercise(cleanup_fails=True)[0], 0)
        self.assertNotEqual(self.exercise(leftover=True)[0], 0)

    def test_invalid_creation_never_deletes_untrusted_name(self):
        result, commands = self.exercise(create_name="--all")
        self.assertNotEqual(result, 0)
        self.assertFalse(any(command[0] == "delete" for command in commands))

    def test_retained_workspace_prevents_new_creation(self):
        result, commands = self.exercise(preexisting=True)
        self.assertNotEqual(result, 0)
        self.assertFalse(any(command[0] in ("create", "delete") for command in commands))


if __name__ == "__main__":
    unittest.main()
