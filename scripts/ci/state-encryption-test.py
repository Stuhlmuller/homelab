#!/usr/bin/env python3
"""Exercise real generated encryption with disposable local state and plans.

PBKDF2's persisted random salt detects metadata-address regressions without AWS.
This proves encryption format/alias behavior, not live KMS permissions.
"""
import json
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

PASSPHRASE = "public-disposable-encryption-fixture-only"
OLD_ALIAS = "key_provider.pbkdf2.main"


def run(directory, *args, succeeds=True):
    result = subprocess.run(args, cwd=directory, capture_output=True, text=True, timeout=90)
    if succeeds:
        if result.returncode:
            raise AssertionError(f"{args}\n{result.stdout}{result.stderr}")
    else:
        if not result.returncode:
            raise AssertionError(f"Unexpected success: {args}")
        if not any(word in (result.stdout + result.stderr).lower()
                   for word in ("decrypt", "encrypt", "metadata")):
            raise AssertionError(f"Failure unrelated to encryption: {result.stderr}")
    return result.stdout


class EncryptionCompatibilityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="state-encryption-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.module = self.directory / "main.tf"
        self.backend = self.directory / "backend.tf"
        self.config = self.directory / "terragrunt.hcl"
        self.module.write_text('resource "terraform_data" "fixture" { input = "one" }\n'
                               'output "fixture" { value = terraform_data.fixture.output }\n')

    def tofu(self, *args, succeeds=True):
        return run(self.directory, "tofu", *args, succeeds=succeeds)

    def old_policy(self, encrypted=True):
        self.config.unlink(missing_ok=True)
        encryption = '''
  encryption {
    key_provider "pbkdf2" "main" { passphrase = "%s" }
    method "aes_gcm" "main" { keys = key_provider.pbkdf2.main }
    state {
      method = method.aes_gcm.main
      enforced = true
    }
    plan {
      method = method.aes_gcm.main
      enforced = true
    }
  }
''' % PASSPHRASE if encrypted else ""
        self.backend.write_text('terraform {\n  backend "local" {}\n' + encryption + '}\n')

    def generated_policy(self, alias=OLD_ALIAS, migration=False):
        alias_setting = f'    encrypted_metadata_alias = "{alias}"\n' if alias else ""
        policy = 'fallback = { method = "unencrypted" }' if migration else "enforced = true"
        generation = self.directory / "generation"
        generation.mkdir(exist_ok=True)
        (generation / "main.tf").write_text("# Backend generation only; no resources or state.\n")
        (generation / "terragrunt.hcl").write_text('''remote_state {
  backend = "local"
  generate = {
    path = "backend.tf"
    if_exists = "overwrite"
  }
  config = {}
  encryption = {
    key_provider = "pbkdf2"
    passphrase = "%s"
    %s
%s  }
}
''' % (PASSPHRASE, policy, alias_setting))
        # v1.2.2 stages source-less units in its cache. Generate in a separate
        # empty module so init never attempts to read the compatibility records.
        cache = generation / ".terragrunt-cache"
        run(generation, "terragrunt", "--log-disable", "run", "--download-dir", str(cache),
            "--", "init", "-backend=false", "-input=false")
        generated_files = list(cache.rglob("backend.tf"))
        self.assertEqual(len(generated_files), 1)
        generated = generated_files[0].read_text()
        self.backend.write_text(generated)
        self.assertIn('key_provider "pbkdf2" "default"', generated)
        self.assertEqual(generated.count("enforced = true"), 0 if migration else 2)
        if migration:
            self.assertEqual(generated.count("fallback {"), 2)
        else:
            self.assertNotIn("fallback", generated)

    def assert_encrypted(self, path):
        record = json.loads(path.read_bytes())
        self.assertIn("encrypted_data", record)
        self.assertIn(OLD_ALIAS, record["meta"])
        self.assertNotIn("terraform_data", path.read_text())

    def test_old_and_generated_state_and_saved_plans_round_trip(self):
        self.old_policy()
        self.tofu("init", "-input=false")
        self.tofu("apply", "-auto-approve", "-input=false")
        self.assert_encrypted(self.directory / "terraform.tfstate")
        self.module.write_text(self.module.read_text().replace('"one"', '"two"'))
        self.tofu("plan", "-out=old.plan", "-input=false")
        self.assert_encrypted(self.directory / "old.plan")
        old_state = (self.directory / "terraform.tfstate").read_bytes()
        for alias in (None, "key_provider.pbkdf2.wrong"):
            with self.subTest(alias=alias):
                self.generated_policy(alias)
                self.tofu("output", "-json", succeeds=False)
                self.tofu("show", "-json", "old.plan", succeeds=False)
        self.generated_policy()
        self.assertEqual(json.loads(self.tofu("output", "-json"))["fixture"]["value"], "one")
        self.assertEqual((self.directory / "terraform.tfstate").read_bytes(), old_state)
        self.assertEqual(json.loads(self.tofu("show", "-json", "old.plan"))
                         ["resource_changes"][0]["change"]["after"]["input"], "two")
        self.tofu("apply", "-input=false", "old.plan")
        self.assert_encrypted(self.directory / "terraform.tfstate")
        self.module.write_text(self.module.read_text().replace('"two"', '"three"'))
        self.tofu("plan", "-out=new.plan", "-input=false")
        self.assert_encrypted(self.directory / "new.plan")
        self.old_policy()
        self.assertEqual(json.loads(self.tofu("output", "-json"))["fixture"]["value"], "two")
        self.assertEqual(json.loads(self.tofu("show", "-json", "new.plan"))
                         ["resource_changes"][0]["change"]["after"]["input"], "three")
        self.tofu("apply", "-input=false", "new.plan")
        self.assertEqual(json.loads(self.tofu("output", "-json"))["fixture"]["value"], "three")
        self.assert_encrypted(self.directory / "terraform.tfstate")

    def test_scoped_plaintext_migration_keeps_reads_read_only_and_writes_encrypted(self):
        self.old_policy(encrypted=False)
        self.tofu("init", "-input=false")
        self.tofu("apply", "-auto-approve", "-input=false")
        self.tofu("plan", "-out=plain.plan", "-input=false")
        plain = (self.directory / "terraform.tfstate").read_bytes()
        lineage = json.loads(plain)["lineage"]
        self.generated_policy(migration=True)
        self.assertEqual(json.loads(self.tofu("output", "-json"))["fixture"]["value"], "one")
        self.assertEqual((self.directory / "terraform.tfstate").read_bytes(), plain)
        self.module.write_text(self.module.read_text().replace('"one"', '"two"'))
        self.tofu("plan", "-out=migration.plan", "-input=false")
        self.assert_encrypted(self.directory / "migration.plan")
        self.assertEqual((self.directory / "terraform.tfstate").read_bytes(), plain)
        self.tofu("apply", "-input=false", "migration.plan")
        self.assert_encrypted(self.directory / "terraform.tfstate")
        self.assertEqual(json.loads(self.tofu("state", "pull"))["lineage"], lineage)
        self.generated_policy()
        self.assertEqual(json.loads(self.tofu("output", "-json"))["fixture"]["value"], "two")
        self.tofu("show", "-json", "plain.plan", succeeds=False)
        self.assertEqual(json.loads(self.tofu("show", "-json", "migration.plan"))
                         ["resource_changes"][0]["address"], "terraform_data.fixture")

    def test_generated_policy_rejects_plaintext_state_and_saved_plan(self):
        self.old_policy(encrypted=False)
        self.tofu("init", "-input=false")
        self.tofu("apply", "-auto-approve", "-input=false")
        self.tofu("plan", "-out=plain.plan", "-input=false")
        self.generated_policy()
        self.tofu("output", "-json", succeeds=False)
        self.tofu("show", "-json", "plain.plan", succeeds=False)


class RootPolicyTest(unittest.TestCase):
    def test_plaintext_fallback_is_limited_to_observed_legacy_units(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="migration-scope-") as directory:
            fixture = Path(directory)
            run(fixture, "git", "init", "-q")
            for name in ("root.hcl", "homelab/account.hcl", "homelab/us-west-2/region.hcl"):
                target = fixture / "IaC" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / "IaC" / name, target)
            legacy_units = {
                "apps/langfuse/blob-storage": "live/langfuse-blob-storage",
                "operator/application-backup-storage": "operator/application-backup-storage",
                "operator/entra-google-workspace-federation": "operator/entra-google-workspace-federation",
                "operator/etcd-backup-storage": "operator/etcd-backup-storage",
                "operator/github-actions-role-policy": "operator/github-actions-role-policy",
                "operator/state-bucket-encryption": "operator/state-bucket-encryption",
                "shared/aws-ssm-parameters": "live/aws-ssm-parameters",
                "shared/kubernetes-secrets/external-secrets-aws-ssm-auth":
                    "live/kubernetes-secrets/external-secrets-aws-ssm-auth",
            }
            ssm_unit = "shared/aws-ssm-parameters"
            strict_units = (
                "apps/langfuse/argocd",
                "operator/application-backup-storage-sibling",
                "operator/etcd-backup-storage-sibling",
                "shared/aws-ssm-parameters-sibling",
                "shared/kubernetes-secrets/sibling",
            )
            for name in (*legacy_units, *strict_units):
                with self.subTest(unit=name):
                    unit = fixture / "IaC/homelab/us-west-2" / name
                    unit.mkdir(parents=True)
                    target = unit / "terragrunt.hcl"
                    if name in (ssm_unit, f"{ssm_unit}-sibling"):
                        shutil.copyfile(
                            root / "IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl",
                            target,
                        )
                    else:
                        target.write_text('include "root" { path = find_in_parent_folders("root.hcl") }\n')
                    data = json.loads(run(unit, "terragrunt", "--log-disable", "render", "--json", "--write=false"))
                    encryption = data["remote_state"]["encryption"]
                    self.assertEqual(encryption["key_provider"], "aws_kms")
                    self.assertEqual(encryption["encrypted_metadata_alias"], "key_provider.aws_kms.main")
                    if name in legacy_units:
                        self.assertEqual(encryption["fallback"], {"method": "unencrypted"})
                        self.assertNotIn("enforced", encryption)
                        self.assertEqual(data["remote_state"]["config"]["key"],
                                         f"IaC/homelab/{legacy_units[name]}/terraform.tfstate")
                    else:
                        self.assertTrue(encryption["enforced"])
                        self.assertNotIn("fallback", encryption)
            account = fixture / "IaC/homelab/account.hcl"
            account.write_text(account.read_text().replace('account_name = "homelab"', 'account_name = "other"'))
            for name in legacy_units:
                with self.subTest(unit=name, account="other"):
                    unit = fixture / "IaC/homelab/us-west-2" / name
                    data = json.loads(run(unit, "terragrunt", "--log-disable", "render", "--json", "--write=false"))
                    encryption = data["remote_state"]["encryption"]
                    self.assertTrue(encryption["enforced"])
                    self.assertNotIn("fallback", encryption)

    def test_shared_root_owns_compatible_encryption_and_backend(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="root-encryption-") as directory:
            fixture = Path(directory)
            run(fixture, "git", "init", "-q")
            for name in ("root.hcl", "homelab/account.hcl", "homelab/us-west-2/region.hcl"):
                target = fixture / "IaC" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / "IaC" / name, target)
            unit = fixture / "IaC/homelab/us-west-2/apps/fixture/argocd"
            unit.mkdir(parents=True)
            (unit / "main.tf").write_text("# Generation only, no cloud resources.\n")
            (unit / "terragrunt.hcl").write_text(
                'include "root" { path = find_in_parent_folders("root.hcl") }\n')
            rendered = json.loads(run(unit, "terragrunt", "--log-disable", "render",
                                      "--json", "--write=false"))
            self.assertEqual(rendered["terragrunt_version_constraint"], ">= 1.2.2")
            self.assertEqual(rendered["remote_state"]["encryption"], {
                "key_provider": "aws_kms", "kms_key_id": "alias/homelab-opentofu",
                "key_spec": "AES_256", "region": "us-east-1", "enforced": True,
                "encrypted_metadata_alias": "key_provider.aws_kms.main"})
            self.assertEqual(rendered["remote_state"]["config"], {
                "bucket": "rstuhlmuller-aws-s3-use1-datalake", "encrypt": True,
                "key": "IaC/homelab/live/argocd-apps/fixture/terraform.tfstate",
                "kms_key_id": "alias/homelab-opentofu", "region": "us-east-1",
                "use_lockfile": True})
            self.assertTrue({"kms_key_id", "kms_region", "kms_key_spec"}.isdisjoint(rendered["inputs"]))
            # The CLI shim captures real generated HCL without executing KMS or
            # an S3 backend. Runtime crypto is tested separately above.
            capture = fixture / "captured-backend.txt"
            shim = fixture / "capture-tofu"
            shim.write_text("#!/usr/bin/env python3\nimport pathlib,sys\n"
                            "if any('version' in a for a in sys.argv):\n"
                            " print('OpenTofu v1.11.8')\n"
                            "else:\n"
                            f" pathlib.Path({str(capture)!r}).write_text(pathlib.Path('backend.tf').read_text())\n")
            shim.chmod(0o755)
            run(unit, "terragrunt", "--log-disable", "run", "--tf-path", str(shim),
                "--download-dir", str(fixture / "cache"), "--", "init", "-backend=false")
            generated = capture.read_text()
            self.assertIn('key_provider "aws_kms" "default"', generated)
            self.assertIn('encrypted_metadata_alias = "key_provider.aws_kms.main"', generated)
            self.assertEqual(generated.count("enforced = true"), 2)
            self.assertEqual(generated.count("encryption {"), 1)
            self.assertNotIn("fallback", generated)
            self.assertNotIn("alias/aws/ssm", generated)
        modules = root / "IaC/terragrunt-catalog/modules"
        for path in modules.rglob("*.tf"):
            self.assertNotRegex(path.read_text(), r'key_provider\s+"aws_kms"')
            if path.parent.name not in ("aws-ssm-parameters", "aws-github-actions-role-policy"):
                self.assertNotRegex(path.read_text(), r'variable "kms_(key_id|region|key_spec)"')


if __name__ == "__main__":
    unittest.main()
