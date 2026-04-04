from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".codex" / "skills"


class SkillTests(unittest.TestCase):
    def test_project_skill_directories_exist(self) -> None:
        for name in (
            "survey-homelab",
            "validate-homelab",
            "bootstrap-homelab",
            "deploy-homelab",
            "unlock-opentofu-state",
        ):
            self.assertTrue((SKILLS_DIR / name / "SKILL.md").is_file(), name)

    def test_skill_frontmatter_matches_folder_name(self) -> None:
        for skill_file in SKILLS_DIR.glob("*/SKILL.md"):
            content = skill_file.read_text()
            match = re.match(r"^---\n(.*?)\n---\n", content, re.S)
            self.assertIsNotNone(match, skill_file)
            self.assertIn(f"name: {skill_file.parent.name}", match.group(1))
            self.assertRegex(match.group(1), r"^description: .+|[\n]description: .+")

    def test_skills_reference_expected_repo_entrypoints(self) -> None:
        expectations = {
            "survey-homelab": ["./scripts/survey-cluster.sh"],
            "validate-homelab": [
                "make validate",
                "./scripts/validate-aws-ssm.sh",
                "./scripts/validate-aws-kms.sh",
                "./scripts/validate-live-cluster.sh",
                "./scripts/validate-live-workloads.sh",
            ],
            "bootstrap-homelab": [
                "./scripts/bootstrap-rolling.sh",
                "make reconcile-tailscale",
                "ansible/playbooks/reconcile-tailscale.yml",
            ],
            "deploy-homelab": [
                "./scripts/deploy-live.sh",
                "./scripts/bootstrap-rolling.sh",
                "terragrunt run --all --tf-path tofu plan",
            ],
            "unlock-opentofu-state": [
                "./scripts/unlock-terragrunt-unit.sh",
                "make unlock-state",
            ],
        }

        for skill_name, required_snippets in expectations.items():
            content = (SKILLS_DIR / skill_name / "SKILL.md").read_text()
            for snippet in required_snippets:
                self.assertIn(snippet, content, f"{skill_name}: {snippet}")

    def test_repo_docs_reference_project_local_skills(self) -> None:
        readme = (ROOT / "README.md").read_text()
        agents = (ROOT / "AGENTS.md").read_text()

        self.assertIn(".codex/skills/", readme)
        self.assertIn("deploy-homelab", readme)
        self.assertIn(".codex/skills/", agents)
        self.assertIn("unlock-opentofu-state", agents)

    def test_skill_validator_is_wired_into_repo_validation(self) -> None:
        validate_script = (ROOT / "scripts/validate.sh").read_text()
        makefile = (ROOT / "Makefile").read_text()

        self.assertIn("./scripts/validate-skills.sh", validate_script)
        self.assertIn("validate-skills:", makefile)
        self.assertIn("./scripts/validate-skills.sh", makefile)


if __name__ == "__main__":
    unittest.main()
