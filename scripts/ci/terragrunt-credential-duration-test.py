#!/usr/bin/env python3
"""Keep the protected apply job within its requested AWS session lifetime."""
import copy
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/terragrunt-apply.yml"
ROLE = ROOT / "IaC/terragrunt-catalog/modules/aws-github-actions-role-policy/main.tf"


def validate_duration(job, maximum):
    credentials = [step for step in job["steps"]
                   if "aws-actions-configure-aws-credentials@" in step.get("uses", "")]
    assert len(credentials) == 1, "expected exactly one AWS credential step"
    timeout = job.get("timeout-minutes")
    duration = credentials[0].get("with", {}).get("role-duration-seconds")
    assert type(timeout) is int and timeout > 0, "job timeout must be explicit integer minutes"
    assert type(duration) is int, "AWS duration must be explicit integer seconds"
    assert 900 <= duration <= maximum, "AWS duration exceeds the declared IAM role bounds"
    assert timeout * 60 <= duration, "AWS credentials expire before the job timeout"


class CredentialDurationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(WORKFLOW)], text=True))
        cls.job = workflow["jobs"]["terragrunt-apply"]
        maximum = re.findall(r"^\s+max_session_duration\s*=\s*(\d+)\b", ROLE.read_text(), re.M)
        assert len(maximum) == 1, "expected exactly one declared IAM session maximum"
        cls.maximum = int(maximum[0])

    def test_repository_duration_covers_job(self):
        validate_duration(self.job, self.maximum)

    def test_unsafe_workflow_changes_fail(self):
        for field, value in [("role-duration-seconds", None), ("role-duration-seconds", 3600),
                             ("role-duration-seconds", self.maximum + 1),
                             ("role-duration-seconds", "${{ inputs.duration }}"),
                             ("timeout-minutes", None), ("timeout-minutes", 121),
                             ("timeout-minutes", "${{ inputs.timeout }}")]:
            with self.subTest(field=field, value=value):
                job = copy.deepcopy(self.job)
                step = next(step for step in job["steps"]
                            if "aws-actions-configure-aws-credentials@" in step.get("uses", ""))
                target = job if field == "timeout-minutes" else step["with"]
                if value is None:
                    target.pop(field, None)
                else:
                    target[field] = value
                with self.assertRaises(AssertionError):
                    validate_duration(job, self.maximum)


if __name__ == "__main__":
    unittest.main()
