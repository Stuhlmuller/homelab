#!/usr/bin/env python3
"""The plan-role publisher must preview and reject wrong operator outputs."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/aws-plan-role-configure.sh"
ROLE_ARN = "arn:aws:iam::123456789012:role/Github-TF-Plan"


class PlanRolePublisher(unittest.TestCase):
    def run_helper(self, role_arn: str, execute: bool = False) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            log = bin_dir / "gh.log"
            generated = bin_dir / "generated"
            (bin_dir / "terragrunt").write_text(
                "#!/bin/sh\n"
                "if [ \"$*\" = '--working-dir IaC/homelab/us-west-2/operator stack generate' ]; then "
                "touch \"$TEST_GENERATED\"; exit 0; fi\n"
                "[ -f \"$TEST_GENERATED\" ] || exit 1\n"
                "[ \"$*\" = '--working-dir IaC/homelab/us-west-2/operator/github-actions-role-policy output -raw plan_role_arn' ] || exit 1\n"
                "printf '%s\\n' \"$TEST_ROLE_ARN\"\n"
            )
            (bin_dir / "gh").write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >>\"$TEST_GH_LOG\"\n"
                "if [ \"$1 $2\" = 'variable get' ]; then printf '%s\\n' \"$TEST_ROLE_ARN\"; fi\n"
            )
            for name in ("terragrunt", "gh"):
                (bin_dir / name).chmod(0o755)
            env = os.environ.copy()
            env.update({"PATH": f"{bin_dir}:{env['PATH']}", "TEST_ROLE_ARN": role_arn,
                        "TEST_GH_LOG": str(log), "TEST_GENERATED": str(generated)})
            args = ["bash", str(HELPER)] + (["--execute"] if execute else [])
            result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True,
                                    text=True, check=False)
            return result, log.read_text() if log.exists() else ""

    def test_preview_is_read_only(self) -> None:
        result, calls = self.run_helper(ROLE_ARN)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Would publish", result.stdout)
        self.assertEqual(calls, "")

    def test_execute_sets_only_plan_environment_variable(self) -> None:
        result, calls = self.run_helper(ROLE_ARN, execute=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("variable set AWS_PLAN_ROLE_TO_ASSUME_HOMELAB --repo Stuhlmuller/homelab --env homelab-plan", calls)
        self.assertIn("variable get AWS_PLAN_ROLE_TO_ASSUME_HOMELAB --repo Stuhlmuller/homelab --env homelab-plan", calls)

    def test_wrong_role_is_rejected_before_github(self) -> None:
        result, calls = self.run_helper("arn:aws:iam::123456789012:role/Github-TF-State", execute=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dedicated Github-TF-Plan", result.stderr)
        self.assertEqual(calls, "")


if __name__ == "__main__":
    unittest.main()
