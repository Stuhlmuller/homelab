#!/usr/bin/env python3
"""Keep GitHub plan and production secrets bound to separate Octelium users."""

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/octelium-ci-credential.sh"
PLAN_IDENTITY = [
    "--credential-name", "homelab-ci-plan",
    "--user", "homelab-ci-plan",
    "--policy", "homelab-ci-kubernetes-api-plan-access",
]


class CredentialTargets(unittest.TestCase):
    def run_helper(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(HELPER), "--dry-run", *args],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_default_targets_production_only(self) -> None:
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("environments: homelab-production", result.stdout)
        self.assertNotIn("homelab-plan", result.stdout)

    def test_plan_requires_plan_identity(self) -> None:
        result = self.run_helper(*PLAN_IDENTITY, "--env", "homelab-plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("environments: homelab-plan", result.stdout)
        self.assertNotIn("homelab-production", result.stdout)

        result = self.run_helper("--env", "homelab-plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dedicated plan User", result.stderr)

    def test_plan_identity_cannot_replace_production_secret(self) -> None:
        result = self.run_helper(*PLAN_IDENTITY)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected apply User", result.stderr)


if __name__ == "__main__":
    unittest.main()
