#!/usr/bin/env python3
"""Use real Terragrunt rendering to reject material changes masked as refactors."""
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CHECK = runpy.run_path(str(Path(__file__).with_name("terragrunt-app-equivalence.py")))


class EquivalenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="app-equivalence-test-")
        cls.root = Path(cls.temporary.name)
        shutil.copytree(ROOT / "IaC", cls.root / "IaC", ignore=shutil.ignore_patterns(
            ".terragrunt-cache", ".terraform", ".terragrunt-stack", "*.tfstate*"))
        (cls.root / "scripts/ci").mkdir(parents=True)
        shutil.copyfile(ROOT / "scripts/ci/terragrunt-current-main.sh", cls.root / "scripts/ci/terragrunt-current-main.sh")
        subprocess.run(["git", "init", "-q"], cwd=cls.root, check=True)
        cls.stack = cls.root / "IaC/homelab/us-west-2/apps/mastodon/stack.hcl"
        cls.baseline = CHECK["contract"](cls.root, "mastodon")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def changed(self, path, transform):
        original = path.read_text()
        try:
            path.write_text(transform(original))
            return CHECK["contract"](self.root, "mastodon")
        finally:
            path.write_text(original)

    def test_equivalent_dependency_spelling(self):
        result = self.changed(self.stack, lambda s: s.replace('../../istio/argocd', '../../istio/./argocd'))
        self.assertEqual(self.baseline, result)

    def test_manifest_change_is_material(self):
        result = self.changed(self.stack, lambda s: s.replace('https://mastodon.stinkyboi.com', 'https://changed.invalid'))
        self.assertNotEqual(self.baseline, result)

    def test_dependency_edge_change_is_material(self):
        result = self.changed(self.stack, lambda s: s.replace('../../istio/argocd', '../../traefik/argocd'))
        self.assertNotEqual(self.baseline, result)

    def test_backend_change_is_material(self):
        result = self.changed(self.root / 'IaC/root.hcl', lambda s: s.replace('rstuhlmuller-aws-s3-use1-datalake', 'changed-bucket'))
        self.assertNotEqual(self.baseline, result)

    def test_provider_change_is_material(self):
        result = self.changed(self.root / 'IaC/kubernetes-provider.hcl', lambda s: s.replace('provider "kubernetes" {', 'provider "kubernetes" {\n  alias = "changed"'))
        self.assertNotEqual(self.baseline, result)

    def test_module_change_is_material(self):
        result = self.changed(self.root / 'IaC/terragrunt-catalog/modules/argocd-application-kubernetes/main.tf',
                              lambda s: s + '\noutput "changed" { value = true }\n')
        self.assertNotEqual(self.baseline, result)

    def test_unsupported_external_inputs_fail_closed(self):
        module = self.root / "IaC/terragrunt-catalog/modules/argocd-application-kubernetes/extra.tf.json"
        try:
            module.write_text('{"variable": {"hidden": {"type": "string"}}}')
            with self.assertRaises(ValueError):
                CHECK["contract"](self.root, "mastodon")
        finally:
            module.unlink()
        with self.assertRaises(ValueError):
            self.changed(self.root / 'IaC/kubernetes-provider.hcl', lambda s: s.replace('provider "kubernetes" {', 'variable "hidden" {}\nprovider "kubernetes" {'))
        with self.assertRaises(ValueError):
            self.changed(self.root / 'IaC/kubernetes-provider.hcl', lambda s: s.replace('provider "kubernetes" {', 'locals { hidden = file("shared.json") }\nprovider "kubernetes" {'))
        with self.assertRaises(ValueError):
            self.changed(self.root / 'IaC/root.hcl', lambda s: s.replace('terraform {', 'terraform {\nextra_arguments "hidden" {\n commands = ["plan"]\n arguments = ["-var-file=hidden.tfvars"]\n }'))

    def test_workload_files_and_failed_reads_cannot_claim_equivalence(self):
        path = 'IaC/homelab/us-west-2/apps/mastodon/stack.hcl'
        self.assertFalse(CHECK['equivalent']('mastodon', [path, 'clusters/homelab/apps/mastodon/workloads.yaml'], 'HEAD'))
        self.assertFalse(CHECK['equivalent']('mastodon', [path], 'missing-ref', root=self.root))



if __name__ == '__main__':
    unittest.main()
