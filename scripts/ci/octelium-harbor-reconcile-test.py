#!/usr/bin/env python3
"""Exercise the bounded Harbor native-catalog reconciliation contract."""
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("harbor_reconcile", ROOT / "scripts/octelium-harbor-reconcile.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
DESIRED = {
    "kind": "Service", "metadata": {"name": "harbor.default"},
    "spec": {"isPublic": True, "isAnonymous": True, "mode": "WEB", "port": 80,
             "config": {"upstream": {"url": "https://istio-ingressgateway.istio-system.svc.cluster.local:443"},
                        "http": {"header": {"authorizationMode": "PASS", "host": {"value": "harbor.stinkyboi.com"}}}}},
}


class ReconciliationTests(unittest.TestCase):
    def exercise(self, execute=True, missing=False, failed_read=False, wrong_identity=False,
                 failed_apply=False, no_convergence=False):
        calls = []
        def run(*command, **kwargs):
            calls.append(command)
            self.assertEqual(kwargs.get("env"), {"carrier": "scoped"})
            if "get" in command:
                self.assertEqual(command[3:6], ("service", "harbor.default", "-o"))
                if failed_read:
                    raise subprocess.CalledProcessError(1, command, stderr="PermissionDenied")
                if missing and len(calls) == 1:
                    raise subprocess.CalledProcessError(1, command, output="gRPC error NotFound: absent")
                value = json.loads(json.dumps(DESIRED))
                if wrong_identity:
                    value["metadata"]["name"] = "unrelated.default"
                return subprocess.CompletedProcess(command, 0, json.dumps(value), "")
            self.assertIn("apply", command)
            document = json.loads(pathlib.Path(command[-1]).read_text())
            self.assertEqual(document, DESIRED)
            output = "No applied changes in Cluster Core resources"
            if failed_apply:
                output = "gRPC error PermissionDenied: no permission"
            elif no_convergence:
                output = "Applied Service"
            return subprocess.CompletedProcess(command, 0, output, "")
        with tempfile.TemporaryDirectory() as temporary, patch.object(MODULE, "run", side_effect=run):
            MODULE.reconcile(["octeliumctl", "--domain=stinkyboi.com"], {"carrier": "scoped"},
                             DESIRED, pathlib.Path(temporary), execute)
        return calls

    def test_preview_is_read_only(self):
        self.assertEqual(len(self.exercise(execute=False)), 1)

    def test_create_and_repeated_apply_verify(self):
        self.assertEqual(len(self.exercise(missing=True)), 4)

    def test_read_errors_do_not_create(self):
        with self.assertRaises(RuntimeError):
            self.exercise(failed_read=True)

    def test_identity_mismatch_fails(self):
        with self.assertRaises(RuntimeError):
            self.exercise(wrong_identity=True)

    def test_native_apply_failure_fails(self):
        with self.assertRaises(RuntimeError):
            self.exercise(failed_apply=True)

    def test_nonconvergent_apply_fails(self):
        with self.assertRaises(RuntimeError):
            self.exercise(no_convergence=True)

    def test_authorization_headers_must_pass(self):
        value = json.loads(json.dumps(DESIRED))
        value["spec"]["config"]["http"]["header"]["authorizationMode"] = "REMOVE"
        self.assertFalse(MODULE.valid_contract(value))

    def test_execution_guard_rejects_dirty_and_wrong_sha(self):
        with self.assertRaises(RuntimeError):
            MODULE.verify_reviewed_main("main")
        with patch.object(MODULE, "run", return_value=subprocess.CompletedProcess([], 0, "?? unsafe.py\n", "")):
            with self.assertRaises(RuntimeError):
                MODULE.verify_reviewed_main("a" * 40)
        with patch.object(MODULE, "run", side_effect=[
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "a" * 40, ""),
            subprocess.CompletedProcess([], 0, "b" * 40 + " refs/heads/main", ""),
        ]):
            with self.assertRaises(RuntimeError):
                MODULE.verify_reviewed_main("a" * 40)


if __name__ == "__main__":
    unittest.main()
