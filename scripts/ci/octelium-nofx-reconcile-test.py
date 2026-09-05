#!/usr/bin/env python3
"""Verify the fixed Service scope and failure/convergence gates."""
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("nofx", pathlib.Path(__file__).resolve().parents[1] / "octelium-nofx-reconcile.py")
nofx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nofx)


class Reconciliation(unittest.TestCase):
    def exercise(self, *, execute=True, apply_error=False, no_convergence=False, anonymous=False, wrong_identity=False):
        applied = []
        reads = 0
        desired = {"kind": "Service", "metadata": {"name": "nofx"}, "spec": {"isAnonymous": False}}

        def run(*command, **_kwargs):
            nonlocal reads
            if "get" in command:
                reads += 1
                output = json.dumps({"metadata": {"name": "other.default" if wrong_identity else "nofx.default"},
                                     "spec": {"isAnonymous": reads == 1 or anonymous,
                                              "authorization": {"policies": ["homelab-human-web-access"]}}})
            else:
                self.assertEqual(command[1:4], ("apply", "--include", "Service"))
                value = json.loads(pathlib.Path(command[-1]).read_text())
                self.assertEqual(value["metadata"]["name"], "nofx.default")
                self.assertIs(value["spec"]["isAnonymous"], False)
                applied.append(value)
                output = "Could not update Service" if apply_error else (
                    "Updated Service" if no_convergence or len(applied) == 1 else "No applied changes in Cluster Core resources")
            return subprocess.CompletedProcess(command, 0, output, "")

        with tempfile.TemporaryDirectory() as directory, patch.object(nofx, "run", side_effect=run):
            try:
                nofx.reconcile(["octeliumctl"], {}, desired, pathlib.Path(directory), execute)
                success = True
            except RuntimeError:
                success = False
        return success, len(applied)

    def test_read_only_never_applies(self):
        self.assertEqual(self.exercise(execute=False), (True, 0))

    def test_fixed_service_converges_and_is_verified(self):
        self.assertEqual(self.exercise(), (True, 2))

    def test_reported_errors_and_unconverged_state_fail(self):
        self.assertEqual(self.exercise(apply_error=True), (False, 1))
        self.assertFalse(self.exercise(no_convergence=True)[0])
        self.assertFalse(self.exercise(anonymous=True)[0])

    def test_wrong_identity_prevents_apply(self):
        self.assertEqual(self.exercise(wrong_identity=True), (False, 0))

    def test_reviewed_commit_is_required(self):
        with self.assertRaises(RuntimeError):
            nofx.verify_reviewed_main(None)
        with patch.object(nofx, "run", return_value=subprocess.CompletedProcess([], 0, "b" * 40, "")):
            with self.assertRaises(RuntimeError):
                nofx.verify_reviewed_main("a" * 40)


if __name__ == "__main__":
    unittest.main()
