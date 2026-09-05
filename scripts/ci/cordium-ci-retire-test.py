#!/usr/bin/env python3
"""Verify the fixed retirement scope and fail-closed rollback checks."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("retire", pathlib.Path(__file__).resolve().parents[1] / "cordium-ci-retire.py")
retire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retire)


class Retirement(unittest.TestCase):
    def exercise(self, *, declared=False, stuck=False, unavailable=False, execute=True):
        deleted = []

        def run(command, **_kwargs):
            output, error, code = "", "", 0
            if command[0] == "yq":
                output = json.dumps([{"kind": kind, "metadata": {"name": name}} for kind, name in retire.TARGETS] if declared else [])
            else:
                operation, kind, name = command[5:8]
                if unavailable:
                    code, error = 1, "rpc error: code = Unavailable"
                elif operation == "delete":
                    deleted.append((kind, name))
                elif (kind, name) in deleted and not stuck:
                    code, error = 1, "rpc error: code = NotFound desc = not found"
                else:
                    output = json.dumps({"metadata": {"name": name}})
            return subprocess.CompletedProcess(command, code, output, error)

        argv = ["retire", "--homedir", "/tmp/operator"] + (["--execute"] if execute else [])
        with patch.object(sys, "argv", argv), patch.object(retire.subprocess, "run", side_effect=run), patch.object(pathlib.Path, "exists", return_value=False):
            try:
                retire.main()
                success = True
            except RuntimeError:
                success = False
        return success, deleted

    def test_only_fixed_targets_are_deleted_and_verified(self):
        success, deleted = self.exercise()
        self.assertTrue(success)
        self.assertEqual(deleted, [(kind.lower(), name) for kind, name in retire.TARGETS])

    def test_catalog_removal_is_required(self):
        self.assertEqual(self.exercise(declared=True), (False, []))

    def test_dry_run_never_deletes(self):
        self.assertEqual(self.exercise(execute=False), (True, []))

    def test_unavailable_is_not_absent_and_stuck_delete_fails(self):
        self.assertEqual(self.exercise(unavailable=True), (False, []))
        self.assertFalse(self.exercise(stuck=True)[0])


if __name__ == "__main__":
    unittest.main()
