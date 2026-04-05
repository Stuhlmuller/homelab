from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutTests(unittest.TestCase):
    def test_expected_top_level_directories_exist(self) -> None:
        for name in ("ansible", "docs", "nomad", "scripts", "terraform", "tests"):
            self.assertTrue((ROOT / name).exists(), name)

    def test_inventory_contains_all_three_nodes(self) -> None:
        content = (ROOT / "ansible/inventories/production/hosts.yml").read_text()
        for host in ("10.1.0.200", "10.1.0.201", "10.1.0.202"):
            self.assertIn(host, content)

    def test_nomad_jobs_have_matching_terragrunt_units(self) -> None:
        jobs = {
            path.parent.name
            for path in (ROOT / "nomad/jobs").glob("*/job.nomad.hcl")
        }
        units = {
            path.parent.name
            for path in (ROOT / "terraform/live/homelab/jobs").glob(
                "*/terragrunt.hcl"
            )
        }
        self.assertEqual(jobs, units)

    def test_terraform_root_references_nomad_provider(self) -> None:
        content = (ROOT / "terraform/root.hcl").read_text()
        self.assertIn('get_env("NOMAD_ADDR", "http://10.1.0.200:4646")', content)
        self.assertIn('address = "${local.nomad_addr}"', content)

    def test_readme_references_monorepo_layout(self) -> None:
        content = (ROOT / "README.md").read_text()
        self.assertIn("Homelab Monorepo", content)
        self.assertIn("ansible/", content)
        self.assertIn("terraform/", content)


if __name__ == "__main__":
    unittest.main()
