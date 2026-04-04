from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class TerraformTests(unittest.TestCase):
    def test_live_tree_contains_jobs_variables_and_volumes(self) -> None:
        base = ROOT / "terraform" / "live" / "homelab"
        for relative in ["jobs", "variables", "volumes"]:
            self.assertTrue((base / relative).is_dir(), relative)

    def test_local_modules_exist(self) -> None:
        modules = ROOT / "terraform" / "modules"
        for module in ["nomad_job", "nomad_variable", "nomad_csi_volume_registration"]:
            self.assertTrue((modules / module / "main.tf").is_file(), module)

    def test_terragrunt_root_exists(self) -> None:
        self.assertTrue((ROOT / "terraform" / "root.hcl").is_file())

    def test_dokploy_variable_unit_exists(self) -> None:
        self.assertTrue(
            (
                ROOT
                / "terraform"
                / "live"
                / "homelab"
                / "variables"
                / "dokploy"
                / "config"
                / "terragrunt.hcl"
            ).is_file()
        )

    def test_paperclip_variable_unit_exists(self) -> None:
        self.assertTrue(
            (
                ROOT
                / "terraform"
                / "live"
                / "homelab"
                / "variables"
                / "paperclip"
                / "config"
                / "terragrunt.hcl"
            ).is_file()
        )

    def test_root_passes_kms_key_id(self) -> None:
        content = (ROOT / "terraform" / "root.hcl").read_text()
        self.assertIn('get_env("TG_KMS_KEY_ID"', content)
        self.assertIn('alias/homelab-opentofu', content)
        self.assertIn("kms_key_id   = local.kms_key_id", content)
        self.assertIn("aws_region   = local.aws_region", content)
        self.assertIn('provider "aws"', content)
        self.assertIn('get_env("TG_AWS_REGION"', content)

    def test_all_modules_enable_opentofu_encryption(self) -> None:
        modules = ROOT / "terraform" / "modules"
        for module in ["nomad_job", "nomad_variable", "nomad_csi_volume_registration"]:
            content = (modules / module / "main.tf").read_text()
            variables = (modules / module / "variables.tf").read_text()
            self.assertIn("encryption {", content, module)
            self.assertIn('key_provider "aws_kms" "main"', content, module)
            self.assertIn("region     = var.aws_region", content, module)
            self.assertIn('variable "aws_region"', variables, module)
            self.assertIn("enforced = true", content, module)

    def test_nomad_variable_module_reads_ssm_parameters(self) -> None:
        content = (ROOT / "terraform" / "modules" / "nomad_variable" / "main.tf").read_text()
        self.assertIn('source  = "hashicorp/aws"', content)
        self.assertIn('data "aws_ssm_parameter" "this"', content)
        self.assertIn("with_decryption = var.ssm_with_decryption", content)
        self.assertIn("items     = local.resolved_items", content)
