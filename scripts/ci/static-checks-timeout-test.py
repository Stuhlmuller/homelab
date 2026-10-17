#!/usr/bin/env python3
"""Verify the shared CI transport setting reaches the actual provider command."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Timeout(unittest.TestCase):
    def test_ci_override_and_local_preservation(self):
        with tempfile.TemporaryDirectory(prefix="static-timeout-") as folder:
            root = Path(folder)
            for name in ("scripts/ci", "IaC/operator/github-actions-role-policy",
                         "IaC/modules/aws-github-actions-role-policy",
                         "IaC/.catalog/units/live/aws-ssm-parameters", "bin"):
                (root / name).mkdir(parents=True)
            for name in ("scripts/ci/static-checks.sh",
                         "IaC/modules/aws-github-actions-role-policy/main.tf",
                         "IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl"):
                shutil.copyfile(ROOT / name, root / name)
            (root / "scripts/ci/nix-cache-signature-test.py").write_text("")
            (root / "scripts/ci/terragrunt-filter-base.sh").write_text(
                "terragrunt_generate_stack() { :; }\n")
            recorded = root / "timeout"
            provider = root / "bin/terragrunt"
            provider.write_text(f"#!/bin/sh\nprintenv TF_REGISTRY_CLIENT_TIMEOUT >'{recorded}'\nexit 77\n")
            provider.chmod(0o700)
            for ci, expected in (("true", "60"), ("false", "5"), ("", "5")):
                with self.subTest(ci=ci):
                    environment = {**os.environ, "GITHUB_ACTIONS": ci,
                                   "TF_REGISTRY_CLIENT_TIMEOUT": "5",
                                   "PATH": f"{root / 'bin'}:{os.environ['PATH']}"}
                    result = subprocess.run(
                        ["bash", "scripts/ci/static-checks.sh", "--offline-verified"],
                        cwd=root, env=environment, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 77, result.stderr.decode())
                    self.assertEqual(recorded.read_text().strip(), expected)


if __name__ == "__main__":
    unittest.main()
