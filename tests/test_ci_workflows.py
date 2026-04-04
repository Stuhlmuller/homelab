from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class WorkflowTests(unittest.TestCase):
    def test_validate_workflow_runs_repo_gate_and_pr_checks(self) -> None:
        content = (ROOT / ".github/workflows/validate.yml").read_text()
        self.assertIn('name: "Validate"', content)
        self.assertIn("pull_request:", content)
        self.assertIn("push:", content)
        self.assertIn("Run validation harness", content)
        self.assertIn("make validate", content)
        self.assertIn("Run PR-focused pre-commit checks", content)
        self.assertIn("checkov_diff", content)
        self.assertIn("checkov_secrets", content)
        self.assertIn("zizmor", content)
        self.assertIn("Lint GitHub Actions", content)
        self.assertIn("./actionlint", content)

    def test_plan_workflow_uses_single_required_job_for_all_prs(self) -> None:
        content = (ROOT / ".github/workflows/plan.yml").read_text()
        self.assertIn('name: "Homelab Plan"', content)
        self.assertIn("concurrency:", content)
        self.assertIn("jobs:\n  plan:", content)
        self.assertNotIn("\n  fork-pr:", content)
        self.assertIn("Update PR description", content)
        self.assertIn("update-pr-body", content)
        self.assertIn("pull-requests: write", content)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", content)
        self.assertIn("github.event.pull_request.head.repo.full_name != github.repository", content)
        self.assertIn("if: always() && github.event.pull_request.head.repo.full_name == github.repository", content)

    def test_deploy_workflow_uses_safe_wrapper(self) -> None:
        content = (ROOT / ".github/workflows/deploy.yml").read_text()
        self.assertIn('name: "Homelab Deploy"', content)
        self.assertIn("concurrency:", content)
        self.assertIn("./scripts/deploy-live.sh --skip-bootstrap", content)
        self.assertIn("aws-actions/configure-aws-credentials@", content)


if __name__ == "__main__":
    unittest.main()
