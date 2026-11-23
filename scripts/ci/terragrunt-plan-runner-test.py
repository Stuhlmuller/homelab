#!/usr/bin/env python3
"""Exercise selective PR planning and saved-plan policy coverage without APIs."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


RUNNER = Path(__file__).with_name("terragrunt-plan.sh")
DEPLOYMENT = "IaC/homelab/us-west-2"


class SelectivePlanRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scripts = self.root / "scripts/ci"
        self.scripts.mkdir(parents=True)
        shutil.copyfile(RUNNER, self.scripts / RUNNER.name)
        (self.scripts / "terragrunt-filter-base.sh").write_text("""
prepare_terragrunt_filter_base() {
  TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF=fixture-base
  TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF=fixture-head
}
terragrunt_generate_stack() { :; }
terragrunt_deleted_unit_paths() { :; }
terragrunt_affected_units() { printf '%s\n' "$FIXTURE_SELECTED"; }
terragrunt_unit_affected() { grep -Fxq "$1" <<<"$2"; }
terragrunt_active_unit_affected() { [[ -f "$1/terragrunt.hcl" ]] && terragrunt_unit_affected "$1" "$2"; }
""")
        self.units = (
            "bootstrap/argocd", "operator/application-backup-storage",
            "apps/one/argocd", "apps/two/argocd", "apps/one/azuread",
        )
        for unit in self.units:
            directory = self.root / DEPLOYMENT / unit
            directory.mkdir(parents=True)
            (directory / "terragrunt.hcl").write_text("# generated fixture\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.write_tool("terragrunt", """
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with open(os.environ["FIXTURE_LOG"], "a") as log:
    log.write(json.dumps({"tool": "terragrunt", "args": args}) + "\\n")
if "show" in args:
    print(Path(args[-1]).read_text())
elif "plan" in args:
    if "run" in args:
        filters = [args[i + 1] for i, arg in enumerate(args) if arg == "--filter"]
        if not filters:
            sys.exit("unfiltered run is forbidden in this fixture")
        units = [Path(unit) for unit in filters]
    else:
        units = [Path(".")]
    if os.environ.get("FIXTURE_MISSING_PLAN") != "true":
        for unit in units:
            destination = unit / ".terragrunt-cache/module/plan.out"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps({"fixture_unit": str(unit)}))
else:
    sys.exit("unexpected Terragrunt operation")
""")
        self.write_tool("conftest", """
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
plans = [path for path in args if path.endswith("plan.json")]
if not plans:
    sys.exit("policy must receive saved plans")
contents = [json.loads(Path(path).read_text()) for path in plans]
with open(os.environ["FIXTURE_LOG"], "a") as log:
    log.write(json.dumps({"tool": "conftest", "plans": plans, "contents": contents}) + "\\n")
sys.exit(int(os.environ.get("FIXTURE_POLICY_EXIT", "0")))
""")
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("ARM_", "ACTIONS_ID_TOKEN_", "TG_", "HOMELAB_"))
        }
        self.environment.update({
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "FIXTURE_LOG": str(self.root / "calls.jsonl"),
            "TG_PROVIDER_CACHE_DIR": str(self.root / "providers"),
        })

    def write_tool(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def run_plan(self, units=(), **environment):
        self.environment.update(environment)
        self.environment["FIXTURE_SELECTED"] = "\n".join(
            f"{DEPLOYMENT}/{unit}" for unit in units
        )
        result = subprocess.run(
            ["bash", str(self.scripts / RUNNER.name)], cwd=self.root,
            env=self.environment, text=True, capture_output=True, timeout=15,
            check=False,
        )
        log = self.root / "calls.jsonl"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    def test_empty_selection_never_runs_terragrunt(self):
        result, calls = self.run_plan()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

    def test_selected_app_saved_plan_reaches_policy_and_is_cleaned(self):
        result, calls = self.run_plan(["apps/one/argocd"])
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = [call for call in calls if "run" in call.get("args", [])]
        self.assertEqual(len(runs), 1)
        args = runs[0]["args"]
        self.assertEqual(args[args.index("--filter") + 1], "./one/argocd")
        policies = [call for call in calls if call["tool"] == "conftest"]
        self.assertEqual(len(policies), 1)
        self.assertEqual(policies[0]["plans"], [f"{DEPLOYMENT}/apps/one/argocd/plan.json"])
        self.assertEqual(policies[0]["contents"], [{"fixture_unit": "one/argocd"}])
        self.assertEqual(list(self.root.rglob("plan.out")), [])
        self.assertEqual(list(self.root.rglob("plan.json")), [])

    def test_missing_selected_plan_fails_before_policy(self):
        result, calls = self.run_plan(["apps/one/argocd"], FIXTURE_MISSING_PLAN="true")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(any(call["tool"] == "conftest" for call in calls))

    def test_selected_azuread_requires_credentials_even_when_old_scope_is_empty(self):
        result, calls = self.run_plan(["apps/one/azuread"])
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("AzureAD credentials are required", result.stderr)
        self.assertEqual(calls, [])

    def test_policy_failure_fails_plan_and_cleans_artifacts(self):
        result, calls = self.run_plan(["apps/one/argocd"], FIXTURE_POLICY_EXIT="1")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertTrue(any(call["tool"] == "conftest" for call in calls))
        self.assertEqual(list(self.root.rglob("plan.out")), [])
        self.assertEqual(list(self.root.rglob("plan.json")), [])


if __name__ == "__main__":
    unittest.main()
