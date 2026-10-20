#!/usr/bin/env python3
"""Check the generated, disabled Enterprise Applications and project boundary."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = None
if len(sys.argv) == 3 and sys.argv[1] == "--upstream-root":
    UPSTREAM = Path(sys.argv[2])
    sys.argv[1:] = []

SYSTEM = "openclaw-system"
AGENTS = "openclaw-agents"
ENVOY = "envoy-gateway-system"
CLUSTER_KINDS = {"Namespace", "ClusterRole", "ClusterRoleBinding"}
NAMESPACED_KINDS = {
    ("", "ConfigMap"), ("", "PersistentVolumeClaim"),
    ("", "Service"), ("", "ServiceAccount"),
    ("apps", "Deployment"), ("apps", "StatefulSet"), ("batch", "Job"),
    ("cert-manager.io", "Certificate"), ("cert-manager.io", "Issuer"),
    ("external-secrets.io", "ExternalSecret"),
    ("gateway.envoyproxy.io", "EnvoyProxy"),
    ("gateway.envoyproxy.io", "SecurityPolicy"),
    ("gateway.networking.k8s.io", "Gateway"),
    ("networking.k8s.io", "NetworkPolicy"),
    ("rbac.authorization.k8s.io", "Role"),
    ("rbac.authorization.k8s.io", "RoleBinding"),
}


def run(*args):
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True,
                          text=True, timeout=60).stdout


def docs(text):
    return [item for item in json.loads(subprocess.run(
        ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=text,
        check=True, capture_output=True, text=True, timeout=30).stdout)
        if isinstance(item, dict)]


def kind(item):
    version = item["apiVersion"]
    return (version.split("/")[0] if "/" in version else "", item["kind"])


def namespace(item):
    if item["kind"] in CLUSTER_KINDS:
        return None
    return item["metadata"].get("namespace", SYSTEM)


class Registration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project, = docs((ROOT / "clusters/homelab/argocd/self-management/"
                             "openclaw-enterprise-appproject.yaml").read_text())
        cls.apps = {}
        for name in ("openclaw-enterprise-foundation", "openclaw-enterprise"):
            rendered = json.loads(run("terragrunt", "--working-dir",
                                      f"IaC/live/argocd-apps/{name}", "--log-disable",
                                      "render", "--json", "--write=false", "--no-color"))
            cls.apps[name] = rendered

    def test_project_is_exactly_scoped_to_rendered_sources_and_kinds(self):
        spec = self.project["spec"]
        self.assertEqual(self.project["metadata"]["name"], "openclaw-enterprise")
        self.assertEqual(set(spec["sourceRepos"]), {
            "https://github.com/Stuhlmuller/homelab.git",
            "https://github.com/openclaw/openclaw-enterprise.git"})
        self.assertEqual({item["namespace"] for item in spec["destinations"]},
                         {SYSTEM, AGENTS, ENVOY})
        self.assertTrue(all(item["server"] == "https://kubernetes.default.svc"
                            for item in spec["destinations"]))
        self.assertEqual({(item["group"], item["kind"])
                          for item in spec["clusterResourceWhitelist"]}, {
            ("", "Namespace"),
            ("rbac.authorization.k8s.io", "ClusterRole"),
            ("rbac.authorization.k8s.io", "ClusterRoleBinding")})
        self.assertEqual({(item["group"], item["kind"])
                          for item in spec["namespaceResourceWhitelist"]},
                         NAMESPACED_KINDS)

    def test_generated_apps_are_disabled_and_require_full_manual_sync(self):
        config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        for name, rendered in self.apps.items():
            app = rendered["inputs"]["manifest"]
            spec = app["spec"]
            self.assertEqual(app["metadata"]["name"], name)
            self.assertEqual(spec["project"], "openclaw-enterprise")
            self.assertEqual(spec["destination"]["namespace"], SYSTEM)
            sync = spec["syncPolicy"]
            self.assertEqual(sync["automated"], {
                "allowEmpty": False, "enabled": False,
                "prune": False, "selfHeal": False})
            self.assertEqual(sync["syncOptions"],
                             ["CreateNamespace=false", "ServerSideApply=true"])
            self.assertEqual(int(sync["retry"]["limit"]), 0)
            self.assertNotIn("ApplyOutOfSyncOnly", json.dumps(sync))
            self.assertNotIn("Skip", json.dumps(sync))
        foundation = self.apps["openclaw-enterprise-foundation"]["inputs"]["manifest"]
        self.assertEqual(foundation["spec"]["sources"], [{
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": "clusters/homelab/apps/openclaw-enterprise-foundation",
            "targetRevision": "main"}])
        enterprise = self.apps["openclaw-enterprise"]["inputs"]["manifest"]
        chart, values, local = enterprise["spec"]["sources"]
        self.assertEqual(chart["repoURL"].removesuffix(".git"),
                         config["source"]["repository"])
        self.assertEqual(chart["path"], config["source"]["chartPath"])
        self.assertEqual(chart["targetRevision"], config["source"]["revision"])
        self.assertEqual(chart["helm"], {"releaseName": "oce", "valueFiles": [
            "$values/clusters/homelab/apps/openclaw-enterprise/values.yaml"]})
        self.assertEqual(values, {
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": ".", "targetRevision": "main", "ref": "values",
            "directory": {"include": ".argocd-values-ref-placeholder.yaml"}})
        self.assertEqual(local, {
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": "clusters/homelab/apps/openclaw-enterprise",
            "targetRevision": "main"})
        dependencies = [Path(path).resolve().name for path in
                        self.apps["openclaw-enterprise"]["dependencies"]["paths"]]
        self.assertEqual(dependencies,
                         ["openclaw-enterprise-foundation", "platform-envoy-gateway"])

    def test_effective_sources_do_not_own_tenant_workloads(self):
        foundation = docs(run("kubectl", "kustomize",
                              "clusters/homelab/apps/openclaw-enterprise-foundation"))
        local = docs(run("kubectl", "kustomize",
                         "clusters/homelab/apps/openclaw-enterprise"))
        tenant = {(item["kind"], item["metadata"]["name"]) for item in foundation + local
                  if namespace(item) == AGENTS}
        self.assertEqual(tenant, {
            ("ExternalSecret", "occ-model-api-key"),
            ("RoleBinding", "openclaw-enterprise-api-configuration"),
            ("RoleBinding", "openclaw-enterprise-api-secrets"),
            ("RoleBinding", "openclaw-enterprise-worker")})
        rendered = foundation + local
        if UPSTREAM:
            self.assertEqual(run("git", "-C", str(UPSTREAM), "rev-parse", "HEAD").strip(),
                             json.loads((ROOT / "scripts/config/openclaw-enterprise.json")
                                        .read_text())["source"]["revision"])
            chart = docs(run("helm", "template", "oce",
                             str(UPSTREAM / "deploy/helm/openclaw-enterprise"),
                             "--namespace", SYSTEM, "--values",
                             "clusters/homelab/apps/openclaw-enterprise/values.yaml"))
            self.assertFalse([item for item in chart if namespace(item) == AGENTS])
            rendered += chart
            self.assertEqual({kind(item) for item in rendered if namespace(item) is None},
                             {(entry["group"], entry["kind"]) for entry in
                              self.project["spec"]["clusterResourceWhitelist"]})
            self.assertEqual({kind(item) for item in rendered if namespace(item) is not None},
                             NAMESPACED_KINDS)
            self.assertEqual({namespace(item) for item in rendered if namespace(item)},
                             {SYSTEM, AGENTS, ENVOY})
        for item in rendered:
            allowed = (self.project["spec"]["clusterResourceWhitelist"]
                       if namespace(item) is None else
                       self.project["spec"]["namespaceResourceWhitelist"])
            self.assertIn({"group": kind(item)[0], "kind": kind(item)[1]}, allowed)


if __name__ == "__main__":
    unittest.main()
