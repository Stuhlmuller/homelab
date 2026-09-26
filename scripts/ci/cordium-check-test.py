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
    def exercise(self, *, remote_exit=0, wrong_sha=False, cleanup_fails=False, leftover=False, create_name="abc", preexisting=False, delayed=False, near_deadline=False, expired=False, mode="checks"):
        commands = []
        timeouts = []
        clock = [0.0]
        lists = 0

        def run(command, **kwargs):
            nonlocal lists
            args = command[5:]
            commands.append(args)
            timeouts.append(kwargs["timeout"])
            clock[0] += 1
            output = ""
            if args[:2] == ["get", "workspace"] and args[2] == "--out":
                lists += 1
                items = [{"metadata": {"name": "abc"}}] if (preexisting or (leftover and lists > 1) or (delayed and lists == 2)) else []
                output = json.dumps({"items": items})
            elif args[:2] == ["create", "workspace"]:
                self.assertNotIn("--start", args)
                output = json.dumps({"metadata": {"name": create_name}})
            elif args[0] == "get":
                if near_deadline:
                    clock[0] = 36 * 60 - 3 * 60 - 10
                output = json.dumps({"status": {"state": "RUNNING"}})
            elif args[0] == "exec" and "rev-parse" in args:
                output = ("b" * 40 if wrong_sha else SHA) + "\n"
            elif args[0] == "exec":
                if near_deadline:
                    clock[0] += kwargs["timeout"]
                    raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                if remote_exit:
                    raise subprocess.CalledProcessError(remote_exit, command)
            elif args[0] == "delete" and cleanup_fails:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, output, "")

        previous = signal.getsignal(signal.SIGTERM)
        output = io.StringIO()
        try:
            def sleep(seconds):
                clock[0] += seconds
            with patch.object(sys, "argv", ["cordium-check.py", "--checkout", SHA, "--homedir", "/tmp/test-login", "--deadline", str(1700000000 + (120 if expired else 36 * 60)), "--mode", mode]), patch.object(runner.subprocess, "run", side_effect=run), patch.object(runner.time, "time", return_value=1700000000), patch.object(runner.time, "monotonic", side_effect=lambda: clock[0]), patch.object(runner.time, "sleep", side_effect=sleep), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                result = runner.main()
        finally:
            signal.signal(signal.SIGTERM, previous)
        self.timeouts = timeouts
        self.output = output.getvalue()
        return result, commands

    def test_fixed_failure_runs_only_after_sha_verification_and_reports_cleanup(self):
        result, commands = self.exercise(mode="force-failure", remote_exit=42)
        self.assertEqual(result, 42)
        expected = ["exec", "abc", "--no-stdin", "--workdir", "/workspace/repo", "--",
                    "/bin/sh", "-c", "exit 42"]
        verification = next(i for i, command in enumerate(commands) if "rev-parse" in command)
        self.assertGreater(commands.index(expected), verification)
        self.assertFalse(any("nix" in command for command in commands))
        self.assertIn("Expected remote exit 42 and disposable workspace deletion verified.", self.output)

    def test_failure_evidence_requires_exact_exit_and_successful_cleanup(self):
        for options in ({"remote_exit": 0}, {"remote_exit": 1}, {"remote_exit": 42, "cleanup_fails": True},
                        {"remote_exit": 42, "leftover": True}, {"remote_exit": 42, "wrong_sha": True}):
            result, commands = self.exercise(mode="force-failure", **options)
            self.assertNotEqual(result, 0)
            self.assertNotIn("Expected remote exit 42 and disposable workspace deletion verified.", self.output)
            if options.get("wrong_sha"):
                self.assertFalse(any("/bin/sh" in command for command in commands))

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

    def test_asynchronous_deletion_is_verified(self):
        result, commands = self.exercise(delayed=True)
        self.assertEqual(result, 0)
        self.assertEqual(commands.count(["get", "workspace", "--out", "json"]), 3)

    def test_retained_workspace_prevents_new_creation(self):
        result, commands = self.exercise(preexisting=True)
        self.assertNotEqual(result, 0)
        self.assertFalse(any(command[0] in ("create", "delete") for command in commands))

    def test_remote_checks_cannot_consume_cleanup_reserve(self):
        result, commands = self.exercise(near_deadline=True)
        self.assertNotEqual(result, 0)
        check = next(i for i, command in enumerate(commands) if "nix" in command)
        deletion = next(i for i, command in enumerate(commands) if command[0] == "delete")
        self.assertLessEqual(self.timeouts[check], 10)
        self.assertGreaterEqual(self.timeouts[deletion], 60)
        self.assertEqual(commands[-1], ["get", "workspace", "--out", "json"])

    def test_exhausted_setup_budget_never_creates_workspace(self):
        result, commands = self.exercise(expired=True)
        self.assertNotEqual(result, 0)
        self.assertEqual(commands, [])

    def test_remote_gate_has_a_twenty_minute_cap(self):
        result, commands = self.exercise()
        self.assertEqual(result, 0)
        check = next(i for i, command in enumerate(commands) if "nix" in command)
        self.assertEqual(self.timeouts[check], 20 * 60)

    def test_workflow_steps_leave_outer_job_margin(self):
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/cordium-check.yml"
        job = json.loads(subprocess.check_output(["yq", "-o=json", ".jobs.check", str(workflow)], text=True))
        budgets = [step["timeout-minutes"] for step in job["steps"]]
        self.assertTrue(all(budget > 0 for budget in budgets))
        self.assertLess(sum(budgets), job["timeout-minutes"])


if __name__ == "__main__":
    unittest.main()
