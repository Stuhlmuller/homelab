#!/usr/bin/env python3
"""Check bounded native identity reconciliation and fail-closed previews."""
import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("catalog", pathlib.Path(__file__).resolve().parents[1] / "cordium-ci-reconcile.py")
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def fixtures():
    return [{"kind": kind, "metadata": {"name": name}, "spec": {"fixture": name}} for kind, name in catalog.TARGETS]


class Reconciliation(unittest.TestCase):
    def exercise(self, *, execute=True, absent=False, unavailable=False, wrong_identity=False,
                 apply_error=False, no_convergence=False, spec_drift=False):
        desired = fixtures()
        applied = []

        def get(command, **kwargs):
            self.assertEqual(kwargs["timeout"], 45)
            self.assertEqual(command[1], "get")
            self.assertEqual(command[-2:], ["-o", "json"])
            item = copy.deepcopy(next(item for item in desired if item["metadata"]["name"] == command[3]))
            if unavailable:
                return subprocess.CompletedProcess(command, 1, "", "rpc error: code = Unavailable")
            if absent and not applied:
                return subprocess.CompletedProcess(command, 1, "gRPC error NotFound: absent", "")
            if wrong_identity:
                item["metadata"]["name"] = "unrelated-user"
            if spec_drift and applied:
                item["spec"]["unexpectedAuthorization"] = True
            return subprocess.CompletedProcess(command, 0, json.dumps(item), "")

        def apply(*command, **_kwargs):
            self.assertEqual(command[1:3], ("apply", "--include"))
            self.assertNotIn("--prune", command)
            path = pathlib.Path(command[-1])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            item = json.loads(path.read_text())
            self.assertEqual(command[3], item["kind"])
            applied.append((item["kind"], item["metadata"]["name"]))
            output = "No applied changes in Cluster Core resources" if len(applied) > 3 and not no_convergence else "Updated"
            if apply_error:
                output = "Could not update User"
            return subprocess.CompletedProcess(command, 0, output, "")

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(catalog.subprocess, "run", side_effect=get), \
                patch.object(catalog.native, "run", side_effect=apply), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                catalog.reconcile(["octeliumctl"], {}, desired, pathlib.Path(directory), execute)
                success = True
            except RuntimeError:
                success = False
        return success, applied

    def test_preview_never_applies_even_when_missing(self):
        self.assertEqual(self.exercise(execute=False), (True, []))
        self.assertEqual(self.exercise(execute=False, absent=True), (True, []))

    def test_only_three_resources_apply_twice_in_safe_order(self):
        for absent in (False, True):
            self.assertEqual(self.exercise(absent=absent), (True, list(catalog.TARGETS) * 2))

    def test_unavailable_and_wrong_identity_prevent_all_writes(self):
        self.assertEqual(self.exercise(unavailable=True), (False, []))
        self.assertEqual(self.exercise(wrong_identity=True), (False, []))

    def test_partial_native_errors_and_missing_convergence_fail(self):
        self.assertEqual(self.exercise(apply_error=True), (False, [catalog.TARGETS[0]]))
        self.assertFalse(self.exercise(no_convergence=True)[0])
        self.assertFalse(self.exercise(spec_drift=True)[0])

    def test_catalog_selector_excludes_every_other_resource(self):
        records = fixtures() + [{"kind": "Credential", "metadata": {"name": "unrelated"}, "spec": {}},
                                {"kind": "User", "metadata": {"name": "homelab-owner"}, "spec": {}}]
        with patch.object(catalog.native, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(records), "")), \
                patch.object(pathlib.Path, "is_file", return_value=True):
            self.assertEqual(catalog.declared_resources(), fixtures())

    def test_missing_duplicate_and_retired_definitions_fail(self):
        for records in (fixtures()[:-1], fixtures() + [fixtures()[0]], [fixtures()[0]] * 3):
            with patch.object(catalog.native, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(records), "")), \
                    self.assertRaises(RuntimeError):
                catalog.declared_resources()
        with patch.object(catalog.native, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(fixtures()), "")), \
                patch.object(pathlib.Path, "is_file", return_value=False), self.assertRaises(RuntimeError):
            catalog.declared_resources()

    def test_main_requires_reviewed_commit_before_catalog_or_transport(self):
        with patch("sys.argv", ["reconcile", "--execute", "--expected-sha", "a" * 40]), \
                patch.object(catalog.native, "verify_reviewed_main", side_effect=RuntimeError("main changed")), \
                patch.object(catalog, "declared_resources") as declared, \
                patch.object(catalog.native, "native_transport") as transport:
            with self.assertRaisesRegex(RuntimeError, "main changed"):
                catalog.main()
            declared.assert_not_called()
            transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
