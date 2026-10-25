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
            for name in ("scripts/ci", "IaC/homelab/us-west-2/operator/github-actions-role-policy",
                         "IaC/terragrunt-catalog/modules/aws-github-actions-role-policy",
                         "IaC/terragrunt-catalog/units/live/aws-ssm-parameters", "bin"):
                (root / name).mkdir(parents=True)
            for name in ("scripts/ci/static-checks.sh",
                         "IaC/terragrunt-catalog/modules/aws-github-actions-role-policy/main.tf",
                         "IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl"):
                shutil.copyfile(ROOT / name, root / name)
            for name in ("nix-cache-signature-test.py", "openclaw-retirement-test.py",
                         "openclaw-retirement-status-test.py",
                         "openclaw-enterprise-operations-test.py",
                         "openclaw-enterprise-resume-test.py",
                         "openclaw-enterprise-journal-operator-test.py",
                         "openclaw-enterprise-operator-image-test.py",
                         "openclaw-enterprise-full-sync-test.py",
                         "openclaw-enterprise-access-test.py",
                         "renovate-config-test.js",
                         "renovate-cache-corruption-drill-test.mjs",
                         "renovate-cache-capacity-drill-test.py",
                         "renovate-acceptance-app-test.py",
                         "renovate-acceptance-observer-test.js",
                         "renovate-acceptance-inventory-test.js",
                         "renovate-acceptance-review-test.py",
                         "renovate-acceptance-schedule-test.py",
                         "renovate-acceptance-schedule-job-test.py",
                         "renovate-acceptance-schedule-collector-test.js",
                         "renovate-acceptance-schedule-assemble-test.py",
                         "renovate-acceptance-report-test.js",
                         "renovate-acceptance-pr-proof-test.js",
                         "renovate-acceptance-source-review-test.js",
                         "renovate-acceptance-secret-boundary-test.py",
                         "renovate-acceptance-final-report-test.py",
                         "renovate-acceptance-ledger-cleanup-test.py",
                         "tailnet-dns-test.py",
                         "openclaw-enterprise-foundation-test.py",
                         "openclaw-enterprise-postgres-test.py",
                         "openclaw-enterprise-chart-hooks-test.py",
                         "openclaw-enterprise-registration-test.py",
                         "openclaw-enterprise-lifecycle-test.py",
                         "openclaw-enterprise-startup-test.py",
                         "openclaw-enterprise-quiesce-test.py",
                         "openclaw-enterprise-bind-installation-test.py",
                         "openclaw-enterprise-test.py",
                         "openclaw-enterprise-active-test.py",
                         "openclaw-enterprise-recovery-test.py",
                         "platform-maintenance-test.py",
                         "platform-maintenance-stage-test.py",
                         "platform-maintenance-credentials-test.py",
                         "network-policy-canary-node-test.py",
                         "network-policy-enforcement-test.py",
                         "network-policy-qualification-test.py",
                         "network-policy-ownership-test.py",
                         "network-policy-cleanup-test.py",
                         "envoy-gateway-prerequisite-test.py",
                         "envoy-gateway-registration-test.py",
                         "network-policy-registration-test.py"):
                (root / "scripts/ci" / name).write_text("")
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
