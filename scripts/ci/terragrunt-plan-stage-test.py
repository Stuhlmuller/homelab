#!/usr/bin/env python3
"""Ensure private plan output can produce only fixed stage labels."""
from pathlib import Path
import subprocess
import unittest

HELPER = Path(__file__).with_name("terragrunt-plan-stage.sh")
MARKERS = {
    "": "nix",
    "::group::Kubeconfig setup": "kubeconfig",
    "::group::Kubernetes API check": "api",
    "::group::Argo CD bootstrap plan": "bootstrap",
    "::group::Argo CD Application registration plan": "app",
    "::group::AzureAD application registration plan": "azuread",
    "::group::Terraform plan Conftest policies": "policy",
}


class PrivatePlanStageTest(unittest.TestCase):
    def assert_stage(self, private_output, stage):
        result = subprocess.run(["bash", str(HELPER)], input=private_output,
                                text=True, capture_output=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout,
                         f"Live plan last recognized stage: {stage}; details withheld.\n")

    def test_only_fixed_labels_leave_private_output(self):
        secret = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_EMIT"
        for marker, stage in MARKERS.items():
            # Even an exact marker in secret output can disclose only a label.
            self.assert_stage(f"{secret}\n{marker}\n::error::{secret}\n{secret}", stage)
        for marker in list(MARKERS)[1:]:
            for forged in (marker + secret, secret + marker,
                           "\x1b[31m" + marker, marker + "$(echo " + secret + ")"):
                self.assert_stage(forged, "nix")
        self.assert_stage("\n".join(MARKERS), "policy")


if __name__ == "__main__":
    unittest.main()
