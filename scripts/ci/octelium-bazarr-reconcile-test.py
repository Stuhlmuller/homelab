#!/usr/bin/env python3
"""Offline checks for the single-Service Bazarr catalog operator path."""
import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/octelium-bazarr-reconcile.py"
SPEC = importlib.util.spec_from_file_location("bazarr_reconcile", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
DESIRED = MODULE.declared_service()


class ReconciliationTests(unittest.TestCase):
    def exercise(self, execute=True, missing=False, read_error=None, apply_error=False,
                 convergence=True, readback=None):
        calls = []
        def run(*command, **kwargs):
            calls.append(command)
            self.assertEqual(kwargs.get("env"), {"carrier": "scoped"})
            if "get" in command:
                self.assertEqual(command[3:], ("service", "bazarr.default", "-o", "json"))
                if read_error:
                    if read_error == "nonzero":
                        raise subprocess.CalledProcessError(1, command, stderr="Unauthenticated")
                    return subprocess.CompletedProcess(command, 0, "Could not get Service: Unauthenticated", "")
                if missing and len(calls) == 1:
                    return subprocess.CompletedProcess(command, 0, "gRPC error NotFound: absent", "")
                value = readback if readback is not None and len(calls) > 1 else DESIRED
                return subprocess.CompletedProcess(command, 0, json.dumps(value), "")
            self.assertEqual(command[2:5], ("apply", "--include", "Service"))
            document = pathlib.Path(command[-1])
            self.assertEqual(json.loads(document.read_text()), DESIRED)
            self.assertEqual(document.stat().st_mode & 0o777, 0o600)
            output = "No applied changes in Cluster Core resources" if convergence else "Applied Service"
            if apply_error:
                output = "gRPC error PermissionDenied: rejected"
            return subprocess.CompletedProcess(command, 0, output, "")
        with tempfile.TemporaryDirectory() as temporary, patch.object(MODULE, "run", side_effect=run):
            try:
                MODULE.reconcile(["octeliumctl", "--domain=stinkyboi.com"], {"carrier": "scoped"},
                                 DESIRED, pathlib.Path(temporary), execute)
            finally:
                if not execute or read_error:
                    self.assertFalse(any("apply" in command for command in calls))
                    self.assertEqual(list(pathlib.Path(temporary).iterdir()), [])
        return calls

    def test_preview_and_single_service_convergence(self):
        self.assertEqual(len(self.exercise(execute=False)), 1)
        self.assertEqual(len(self.exercise(execute=False, missing=True)), 1)
        self.assertEqual(len(self.exercise(missing=True)), 4)

    def test_errors_and_failed_readback_fail_closed(self):
        for options in ({"read_error": "nonzero"}, {"read_error": "exit-zero"},
                        {"apply_error": True}, {"convergence": False}):
            with self.subTest(options=options), self.assertRaises(RuntimeError):
                self.exercise(**options)
        drift = copy.deepcopy(DESIRED)
        drift["spec"]["isAnonymous"] = True
        with self.assertRaises(RuntimeError):
            self.exercise(readback=drift)

    def test_contract_rejects_auth_and_routing_drift(self):
        for keys, value in [
            (("metadata", "name"), "nofx.default"), (("spec", "isPublic"), False),
            (("spec", "isAnonymous"), True), (("spec", "mode"), "TCP"), (("spec", "port"), 443),
            (("spec", "authorization", "policies"), []),
            (("spec", "config", "upstream", "url"), "https://wrong.invalid"),
        ]:
            candidate = copy.deepcopy(DESIRED)
            destination = candidate
            for key in keys[:-1]:
                destination = destination[key]
            destination[keys[-1]] = value
            self.assertFalse(MODULE.valid_contract(candidate), keys)
        self.assertFalse(MODULE.valid_contract(None))

    def test_execution_guard_and_isolated_entrypoint(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python3 -I", result.stderr)
        with self.assertRaises(RuntimeError):
            MODULE.verify_reviewed_main("main")
        def completed(output):
            return subprocess.CompletedProcess([], 0, output, "")
        for responses in ([completed("?? unsafe.py\n")],
                          [completed(""), completed("b" * 40), completed("a" * 40 + " refs/heads/main")],
                          [completed(""), completed("a" * 40), completed("b" * 40 + " refs/heads/main")]):
            with patch.object(MODULE, "run", side_effect=responses), self.assertRaises(RuntimeError):
                MODULE.verify_reviewed_main("a" * 40)
        with patch.object(MODULE, "run", side_effect=[
            completed(""), completed("a" * 40), completed("a" * 40 + " refs/heads/main"),
            subprocess.CalledProcessError(1, ["git", "cat-file"]),
        ]), self.assertRaises(subprocess.CalledProcessError):
            MODULE.verify_reviewed_main("a" * 40)


if __name__ == "__main__":
    unittest.main()
