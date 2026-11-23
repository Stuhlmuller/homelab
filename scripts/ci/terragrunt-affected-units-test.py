#!/usr/bin/env python3
"""Selection regressions, including native Git filters and generated sidecars."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).with_name("terragrunt-affected-units.py")
SPEC = importlib.util.spec_from_file_location("plan_units", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PREFIX = str(MODULE.DEPLOYMENT)
TEMPLATE = "IaC/terragrunt-catalog/units/fixture"


class SelectionTest(unittest.TestCase):
    def test_invalid_discovery_path_fails(self):
        for path in ("../elsewhere", "/tmp/unit", "unit|*"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                MODULE.affected_units([{"type": "unit", "path": path}])


class NativeSelectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_command("git", "init", "-qb", "main")
        self.write(".gitignore", "**/argocd/\n")
        self.write(f"{TEMPLATE}/terragrunt.hcl", 'inputs = { value = values.value }\n')
        self.write(f"{TEMPLATE}/main.tf", 'variable "value" { type = string }\n')
        for app in ("one", "two"):
            self.write(f"{PREFIX}/apps/{app}/stack.hcl", 'inputs = { value = "before" }\n')
            self.write(f"{PREFIX}/apps/{app}/terragrunt.stack.hcl", '''unit "app" {
  source = "${get_repo_root()}/IaC/terragrunt-catalog/units/fixture"
  path = "argocd"
  no_dot_terragrunt_stack = true
  values = read_terragrunt_config("${get_terragrunt_dir()}/stack.hcl").inputs
}
''')
        self.commit()
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

    def affected_units(self):
        self.run_command("terragrunt", "--working-dir", "IaC", "stack", "generate")
        return self.run_command("python3", "-I", str(HELPER)).splitlines()

    def test_native_filter_selects_only_app_with_changed_inputs(self):
        self.write(f"{PREFIX}/apps/one/stack.hcl", 'inputs = { value = "after" }\n')
        self.commit()
        self.assertEqual(self.affected_units(), [f"{PREFIX}/apps/one/argocd"])

    def test_unrelated_change_has_no_affected_units(self):
        self.write("README.md", "unrelated change\n")
        self.commit()
        self.assertEqual(self.affected_units(), [])

    def test_native_template_change_selects_generated_instances(self):
        self.write(f"{TEMPLATE}/terragrunt.hcl", 'inputs = { value = upper(values.value) }\n')
        self.commit()
        self.assertEqual(set(self.affected_units()), {
            TEMPLATE, f"{PREFIX}/apps/one/argocd", f"{PREFIX}/apps/two/argocd",
        })

    def test_native_filter_reports_deleted_unit(self):
        self.run_command("git", "rm", "-r", f"{PREFIX}/apps/one")
        self.commit()
        self.assertEqual(self.affected_units(), [f"{PREFIX}/apps/one/argocd"])

    def test_retirement_preserves_saved_plan_and_excludes_active_unit(self):
        self.run_command("git", "rm", "-r", f"{PREFIX}/apps/one")
        self.write(f"{PREFIX}/apps/two/stack.hcl", 'inputs = { value = "after" }\n')
        self.commit()
        self.assertEqual(set(self.affected_units()), {
            f"{PREFIX}/apps/one/argocd", f"{PREFIX}/apps/two/argocd",
        })
        args = (
            "terragrunt", "run", "--all", "--non-interactive", "--filter-affected",
            "--filter", f"!./{PREFIX}/apps/two/argocd", "--filter-allow-destroy",
            "--out-dir", str(self.root / "binary"), "--log-level", "warn",
        )
        self.run_command(*args, "--json-out-dir", str(self.root / "json"), "--", "plan")
        self.assertEqual(list((self.root / "binary").rglob("tfplan.tfplan")), [
            self.root / "binary" / "@main" / PREFIX / "apps/one/argocd/tfplan.tfplan",
        ])
        self.assertEqual(list((self.root / "json").rglob("tfplan.json")), [
            self.root / "json" / "@main" / PREFIX / "apps/one/argocd/tfplan.json",
        ])
        self.run_command(*args, "--", "apply")

    def test_ci_prepares_main_and_head_for_native_discovery(self):
        base = self.run_command("git", "rev-parse", "main").strip()
        self.write(f"{PREFIX}/apps/one/stack.hcl", 'inputs = { value = "after" }\n')
        self.commit()
        self.run_command("git", "update-ref", "refs/remotes/origin/feature", "HEAD")
        self.run_command("git", "update-ref", "refs/remotes/origin/main", "HEAD")
        self.run_command("git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/feature")
        self.run_command("git", "branch", "--force", "main", "HEAD")
        shell = (
            'set -euo pipefail; source "$1"; prepare_terragrunt_filter_base; '
            'terragrunt_generate_stack; terragrunt_affected_units'
        )
        selected = self.run_command(
            "env", "CI=true", f"TERRAGRUNT_FILTER_BASE_SHA={base}",
            "TERRAGRUNT_FILTER_HEAD_SHA=HEAD", "bash", "-c", shell, "fixture", str(HELPER.with_name("terragrunt-filter-base.sh")),
        )
        self.assertEqual(selected.splitlines(), [f"{PREFIX}/apps/one/argocd"])

    def test_native_discovery_failure_is_fatal(self):
        self.write(f"{PREFIX}/apps/one/stack.hcl", 'inputs = { value = "after" }\n')
        self.commit()
        self.run_command("terragrunt", "--working-dir", "IaC", "stack", "generate")
        with tempfile.TemporaryDirectory() as binaries:
            stub = Path(binaries) / "terragrunt"
            stub.write_text("#!/bin/sh\nexit 42\n")
            stub.chmod(0o755)
            result = subprocess.run(["python3", "-I", str(HELPER)],
                                    cwd=self.root, env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
