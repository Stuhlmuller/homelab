#!/usr/bin/env python3
"""Selection regressions, including native Git filters and generated sidecars."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).with_name("terragrunt-plan-units.py")
SPEC = importlib.util.spec_from_file_location("plan_units", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PREFIX = str(MODULE.DEPLOYMENT)
ALLOWED = {"apps/one/argocd", "apps/two/argocd", "apps/two/azuread",
           "bootstrap/argocd", "operator/application-backup-storage"}


class SelectionTest(unittest.TestCase):
    def test_one_app_sidecar_selects_only_its_units(self):
        self.assertEqual(MODULE.select_units(ALLOWED, [f"{PREFIX}/apps/one/stack.hcl"], []),
                         ["apps/one/argocd"])
        self.assertEqual(MODULE.select_units(ALLOWED, [f"{PREFIX}/apps/two/terragrunt.stack.hcl"], []),
                         ["apps/two/argocd", "apps/two/azuread"])

    def test_shared_inputs_force_coverage(self):
        for path in ("IaC/root.hcl", "IaC/stack-defaults.hcl",
                     "IaC/terragrunt-catalog/modules/argocd/main.tf",
                     "IaC/terragrunt-catalog/units/live/argocd-app/terragrunt.hcl",
                     "flake.lock", "policy/terraform.rego", str(HELPER.relative_to(HELPER.parents[2]))):
            with self.subTest(path=path):
                self.assertEqual(MODULE.select_units(ALLOWED, [path], []), sorted(ALLOWED))

    def test_discovered_stacks_expand_and_private_units_are_excluded(self):
        discovered = [{"type": "stack", "path": f"{PREFIX}/apps/two"},
                      {"type": "unit", "path": f"{PREFIX}/shared/aws-ssm-parameters"},
                      {"type": "unit", "path": f"{PREFIX}/apps/langfuse/blob-storage"},
                      {"type": "unit", "path": f"{PREFIX}/apps/removed/argocd"}]
        self.assertEqual(MODULE.select_units(ALLOWED, [], discovered),
                         ["apps/two/argocd", "apps/two/azuread"])

    def test_unrelated_changes_and_deleted_apps_do_not_plan_everything(self):
        self.assertEqual(MODULE.select_units(ALLOWED, ["README.md"], []), [])
        self.assertEqual(MODULE.select_units(ALLOWED, [f"{PREFIX}/apps/retired/stack.hcl"], []), [])

    def test_invalid_discovery_path_fails(self):
        with self.assertRaises(ValueError):
            MODULE.select_units(ALLOWED, [], [{"type": "unit", "path": "../elsewhere"}])


class NativeSelectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_command("git", "init", "-qb", "main")
        self.write(".gitignore", "**/argocd/\n")
        self.write("IaC/template/terragrunt.hcl", 'inputs = { value = values.value }\n')
        for app in ("one", "two"):
            self.write(f"{PREFIX}/apps/{app}/stack.hcl", 'inputs = { value = "before" }\n')
            self.write(f"{PREFIX}/apps/{app}/terragrunt.stack.hcl", '''unit "app" {
  source = "../../../../template"
  path = "argocd"
  no_dot_terragrunt_stack = true
  values = read_terragrunt_config("${get_terragrunt_dir()}/stack.hcl").inputs
}
''')
        self.commit()
        self.base = self.run_command("git", "rev-parse", "HEAD").strip()
        self.run_command("git", "switch", "-qc", "feature")

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def run_command(self, *args):
        result = subprocess.run(args, cwd=self.root, text=True, capture_output=True,
                                env={key: value for key, value in os.environ.items()
                                     if not key.startswith(("TG_", "TERRAGRUNT_"))}, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def commit(self):
        self.run_command("git", "add", ".")
        self.run_command("git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                         "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")

    def test_native_filter_sidecar_and_stack_changes_select_one_app(self):
        for filename in ("stack.hcl", "terragrunt.stack.hcl"):
            with self.subTest(filename=filename):
                target = self.root / PREFIX / "apps/one" / filename
                target.write_text(target.read_text() + "\n# changed\n")
                self.commit()
                self.run_command("terragrunt", "--working-dir", "IaC", "stack", "generate")
                selected = self.run_command("python3", "-I", str(HELPER), "--base", self.base, "--head", "HEAD")
                self.assertEqual(selected.splitlines(), [f"{PREFIX}/apps/one/argocd"])
                # Ensure this exercised revision discovery, not the dirty fallback.
                self.assertEqual(self.run_command("git", "status", "--porcelain"), "")

    def test_native_discovery_failure_is_fatal(self):
        self.write(f"{PREFIX}/apps/one/stack.hcl", 'inputs = { value = "after" }\n')
        self.commit()
        self.run_command("terragrunt", "--working-dir", "IaC", "stack", "generate")
        with tempfile.TemporaryDirectory() as binaries:
            stub = Path(binaries) / "terragrunt"
            stub.write_text("#!/bin/sh\nexit 42\n")
            stub.chmod(0o755)
            result = subprocess.run(["python3", "-I", str(HELPER), "--base", self.base, "--head", "HEAD"],
                                    cwd=self.root, env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
