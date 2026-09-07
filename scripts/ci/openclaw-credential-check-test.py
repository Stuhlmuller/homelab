#!/usr/bin/env python3
"""Check the production credential-policy evaluator under optimized Python."""
from pathlib import Path
import subprocess
import sys
import unittest

CHECK = Path(__file__).with_name("openclaw-credential-check.py")
PROBE = r"""
import ast
import json
from pathlib import Path
import subprocess
import sys

# Load the real evaluator without repeating the full render/fixture suite.
source = Path(sys.argv[1])
tree = ast.parse(source.read_text(), filename=str(source))
verify = next(node for node in tree.body
              if isinstance(node, ast.FunctionDef) and node.name == "verify")
namespace = {"json": json, "subprocess": subprocess, "count": 0}
exec(compile(ast.Module(body=[verify], type_ignores=[]), str(source), "exec"), namespace)
try:
    namespace["verify"](sys.argv[2], {}, sys.argv[3] == "true")
except (RuntimeError, AssertionError):
    print("rejected")
else:
    print("accepted")
"""


class CredentialEvaluatorTests(unittest.TestCase):
    def probe(self, optimized, expression, accepted):
        command = [sys.executable] + (["-O"] if optimized else [])
        result = subprocess.run(
            command + ["-c", PROBE, str(CHECK), expression, str(accepted).lower()],
            check=True, capture_output=True, text=True, timeout=35,
        )
        return result.stdout.strip()

    def test_policy_mismatches_fail_with_and_without_optimization(self):
        for optimized in (False, True):
            for expression, accepted in (("false", True), ("true", False)):
                with self.subTest(optimized=optimized, expression=expression):
                    self.assertEqual(self.probe(optimized, expression, accepted), "rejected")

    def test_matching_policy_outcomes_remain_valid(self):
        for optimized in (False, True):
            for expression, accepted in (("true", True), ("false", False)):
                with self.subTest(optimized=optimized, expression=expression):
                    self.assertEqual(self.probe(optimized, expression, accepted), "accepted")


if __name__ == "__main__":
    unittest.main()
