#!/usr/bin/env python3
"""Exercise shared app generation and deployment selection without remote state."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILTERS = ROOT / "scripts/ci/terragrunt-filter-base.sh"


def run(*args, cwd, input=None):
    result = subprocess.run(args, cwd=cwd, input=input, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(f"{' '.join(map(str, args))}\n{result.stdout}{result.stderr}")
    return result.stdout.strip()


def unit(name, group="argocd-apps", values="defaults = local.argocd_defaults"):
    return f'''unit "{name}" {{
  source = "./.catalog/units/live/argocd-app"
  path = "live/{group}/{name}"
  no_dot_terragrunt_stack = true
  values = {{
    {values}
  }}
}}
'''


class StackSelectionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "IaC").mkdir()
        (self.root / "IaC/root.hcl").write_text("inputs = {}\n")
        self.stack = self.root / "IaC/terragrunt.stack.hcl"
        self.locals = 'locals { argocd_defaults = { project = "homelab" } }\n'
        self.apps = unit("kept") + unit("retired")
        self.azure = unit("identity", "azuread-applications", "name = \"identity\"")
        self.operator = unit("operator", "../operator", "name = \"operator\"")
        # Operator paths are explicit too, but never workflow retirement targets.
        self.operator = self.operator.replace("live/../operator/", "operator/")
        self.stack.write_text(self.locals + self.apps + self.azure + self.operator)
        run("git", "init", "-q", cwd=self.root)
        self.base = self.commit()

    def commit(self):
        run("git", "add", ".", cwd=self.root)
        run("git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-qm", "fixture", cwd=self.root)
        return run("git", "rev-parse", "HEAD", cwd=self.root)

    def shell(self, command, head="HEAD"):
        return run("bash", "-euo", "pipefail", "-c", '''
source "$1"
TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF="$2"
TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF="$3"
APPLY_BASE_SHA="$2"
APPLY_HEAD_SHA="$3"
eval "$4"
''', "fixture", str(FILTERS), self.base, head, command, cwd=self.root)

    def test_current_stack_is_checked_before_commit(self):
        self.stack.write_text(self.stack.read_text() + unit("new-app"))
        paths = self.shell("terragrunt_stack_unit_paths < IaC/terragrunt.stack.hcl").splitlines()
        self.assertIn("IaC/live/argocd-apps/new-app", paths)
        self.assertNotIn("IaC/live/argocd-apps/new-app",
                         self.shell("terragrunt_stack_unit_paths_at_ref HEAD").splitlines())

    def test_shared_argocd_defaults_select_apps_without_azure_or_retirement(self):
        self.stack.write_text(self.stack.read_text().replace('project = "homelab"',
                                                            'project = "homelab-workloads"'))
        head = self.commit()
        self.assertEqual(self.shell("terragrunt_changed_filter 'IaC/live/argocd-apps/*'", head), "*")
        self.assertEqual(self.shell("terragrunt_deleted_unit_paths", head), "")
        self.shell("! terragrunt_azuread_stack_changed", head)

    def test_removing_unit_retires_only_that_workflow_owned_state(self):
        self.stack.write_text(self.locals + unit("kept") + self.azure)
        head = self.commit()
        self.assertEqual(self.shell("terragrunt_deleted_unit_paths", head),
                         "IaC/live/argocd-apps/retired")
        self.shell("! terragrunt_azuread_stack_changed", head)

    def test_azure_changes_still_require_azure_credentials(self):
        self.stack.write_text(self.stack.read_text().replace('name = "identity"',
                                                            'name = "changed-identity"'))
        self.shell("terragrunt_azuread_stack_changed", self.commit())


class SharedAppTemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve() / "IaC"
        cls.root.mkdir()
        cls.addClassCleanup(cls.temporary.cleanup)
        # Keep real backend key derivation; render does not initialize the backend.
        shutil.copyfile(ROOT / "IaC/root.hcl", cls.root / "root.hcl")
        shutil.copyfile(ROOT / "IaC/kubernetes-provider.hcl", cls.root / "kubernetes-provider.hcl")
        shutil.copytree(ROOT / "IaC/.catalog/units/live/argocd-app",
                        cls.root / ".catalog/units/live/argocd-app")
        defaults = (ROOT / "IaC/terragrunt.stack.hcl").read_text().split('\nunit "', 1)[0]
        overrides = '''defaults = local.argocd_defaults
    dependencies = ["sparse-app"]
    metadata = {
      labels = { "app.kubernetes.io/part-of" = "fixture" }
      annotations = { "example.invalid/reviewed" = "true" }
    }
    spec = {
      project = "homelab-workloads"
      destination = { namespace = "shared" }
      sources = [{
        repoURL = "https://charts.example.invalid"
        chart = "fixture"
        targetRevision = "1.2.3"
      }]
      syncPolicy = {
        automated = { enabled = false, prune = false }
        retry = { limit = "1", backoff = { duration = "1m" } }
        syncOptions = ["ServerSideApply=true"]
      }
      ignoreDifferences = [{ kind = "Secret", jsonPointers = ["/data"] }]
    }'''
        (cls.root / "terragrunt.stack.hcl").write_text(
            defaults + "\n" + unit("sparse-app") + unit("override-app", values=overrides))
        run("terragrunt", "--log-disable", "stack", "generate", cwd=cls.root)

    def render(self, name):
        return json.loads(run("terragrunt", "--log-disable", "render", "--json",
                              "--write=false", "--no-color",
                              cwd=self.root / "live/argocd-apps" / name))

    def test_sparse_app_inherits_a_complete_application_and_stable_state_path(self):
        rendered = self.render("sparse-app")
        manifest = rendered["inputs"]["manifest"]
        self.assertEqual(manifest["apiVersion"], "argoproj.io/v1alpha1")
        self.assertEqual(manifest["kind"], "Application")
        self.assertEqual(manifest["metadata"], {
            "name": "sparse-app", "namespace": "argocd",
            "labels": {"app.kubernetes.io/managed-by": "terragrunt",
                       "app.kubernetes.io/part-of": "homelab"},
        })
        self.assertEqual(manifest["spec"]["destination"], {
            "name": "", "server": "https://kubernetes.default.svc", "namespace": "sparse-app",
        })
        self.assertEqual(manifest["spec"]["sources"], [{
            "repoURL": "https://github.com/Stuhlmuller/homelab.git", "targetRevision": "main",
            "path": "clusters/homelab/apps/sparse-app",
        }])
        self.assertEqual(manifest["spec"]["syncPolicy"]["automated"], {
            "allowEmpty": False, "enabled": True, "prune": True, "selfHeal": True,
        })
        self.assertEqual(rendered["remote_state"]["config"]["key"],
                         "IaC/homelab/live/argocd-apps/sparse-app/terraform.tfstate")
        self.assertFalse((self.root / ".terragrunt-stack/live/argocd-apps/sparse-app").exists())

    def test_overrides_preserve_siblings_and_replace_lists(self):
        rendered = self.render("override-app")
        manifest = rendered["inputs"]["manifest"]
        self.assertEqual(manifest["metadata"]["labels"], {
            "app.kubernetes.io/managed-by": "terragrunt", "app.kubernetes.io/part-of": "fixture",
        })
        self.assertEqual(manifest["metadata"]["annotations"], {"example.invalid/reviewed": "true"})
        self.assertEqual(manifest["spec"]["project"], "homelab-workloads")
        self.assertEqual(manifest["spec"]["destination"], {
            "name": "", "server": "https://kubernetes.default.svc", "namespace": "shared",
        })
        self.assertEqual(manifest["spec"]["sources"], [{
            "repoURL": "https://charts.example.invalid", "chart": "fixture", "targetRevision": "1.2.3",
        }])
        self.assertEqual(manifest["spec"]["syncPolicy"], {
            "automated": {"allowEmpty": False, "enabled": False, "prune": False, "selfHeal": True},
            "retry": {"limit": "1", "backoff": {"duration": "1m", "factor": "2", "maxDuration": "2m"}},
            "syncOptions": ["ServerSideApply=true"],
        })
        self.assertEqual(manifest["spec"]["ignoreDifferences"],
                         [{"kind": "Secret", "jsonPointers": ["/data"]}])
        self.assertEqual(rendered["dependencies"]["paths"],
                         [str(self.root / "live/argocd-apps/override-app/../sparse-app")])


if __name__ == "__main__":
    unittest.main()
