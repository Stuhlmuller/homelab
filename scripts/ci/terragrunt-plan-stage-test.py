#!/usr/bin/env python3
"""Ensure private plan output can produce only fixed stage labels."""
from pathlib import Path
import os
import subprocess
import tempfile
import textwrap
import unittest

HELPER = Path(__file__).with_name("terragrunt-plan-stage.sh")
WORKFLOW = HELPER.parents[2] / ".github/workflows/terragrunt-plan.yml"
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

    def test_workflow_tail_executes_only_the_verified_helper(self):
        # Execute the actual failure tail; no Nix, credentials, or live commands.
        workflow = WORKFLOW.read_text()
        tail = textwrap.dedent(workflow.split("\n          EOF\n", 1)[1]
                               .split("\n  terragrunt-plan-skipped:", 1)[0])
        withheld_error = ("::error::Live plan failed; detailed output was withheld "
                          "because this is a public repository. Reproduce it locally.\n")
        secret = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_EMIT"
        original = HELPER.read_text()
        variants = (
            original,
            ': > executed\ncat\n',
            ': > executed\ncat >&2\n',
            ': > executed\nif [[ ${GITHUB_ACTIONS:-} == true ]]; then cat; fi\n',
            None,
        )
        for helper_source in variants:
            with self.subTest(helper_source=helper_source), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                helper = root / "scripts/ci/terragrunt-plan-stage.sh"
                helper.parent.mkdir(parents=True)
                if helper_source is not None:
                    helper.write_text(helper_source)
                private_log = root / "private.log"
                private_log.write_text(f"{secret}\n::group::Kubernetes API check\n{secret}\n")
                result = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", 'private_log="$1"\nif true\n' + tail,
                     "failure-tail-test", str(private_log)],
                    cwd=root, env=dict(os.environ, CI="true", GITHUB_ACTIONS="true"),
                    text=True, capture_output=True, timeout=5, check=False)
                expected = withheld_error
                if helper_source == original:
                    expected = "Live plan last recognized stage: api; details withheld.\n" + expected
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, "")
                self.assertFalse((root / "executed").exists())


if __name__ == "__main__":
    unittest.main()
