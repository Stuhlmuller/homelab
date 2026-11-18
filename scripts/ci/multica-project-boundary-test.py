#!/usr/bin/env python3
"""Check Multica project wiring and its repository-owned overlay boundary.

The separate OCI chart needs a complete render before protected project apply.
"""

import copy
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "clusters/homelab/argocd/self-management/workloads-appproject.yaml"
STACK = ROOT / "IaC/homelab/us-west-2/apps/multica/stack.hcl"
APP = ROOT / "clusters/homelab/apps/multica"
CLUSTER_KINDS = {
    "APIService", "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition",
    "IngressClass", "MutatingWebhookConfiguration", "Namespace", "PersistentVolume",
    "PriorityClass", "StorageClass", "ValidatingWebhookConfiguration",
}


def safe(project, stack, objects):
    spec = project.get("spec", {})
    if project.get("kind") != "AppProject" or project.get("metadata", {}).get("name") != "homelab-workloads":
        return False
    if spec.get("clusterResourceWhitelist") != []:
        return False
    if set(spec.get("sourceRepos", [])) != {
        "https://github.com/Stuhlmuller/homelab.git",
        "https://bjw-s-labs.github.io/helm-charts",
        "ghcr.io/multica-ai/charts",
    }:
        return False
    if not any(destination.get("namespace") == "ai" and
               destination.get("server") == "https://kubernetes.default.svc"
               for destination in spec.get("destinations", [])):
        return False
    if 'project = "homelab-workloads"' not in stack or 'repoURL        = "ghcr.io/multica-ai/charts"' not in stack:
        return False
    return bool(objects) and all(obj.get("kind") not in CLUSTER_KINDS and
                                 obj.get("metadata", {}).get("namespace") == "ai" for obj in objects)


class MulticaProjectBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(PROJECT)], text=True))
        cls.stack = STACK.read_text()
        rendered = subprocess.check_output(["kubectl", "kustomize", str(APP)], text=True)
        cls.objects = json.loads(subprocess.check_output(
            ["yq", "eval-all", "-o=json", "-I=0", "[.]", "-"],
            input=rendered, text=True))

    def test_namespaced_multica_contract(self):
        self.assertTrue(safe(self.project, self.stack, self.objects))

    def test_rejects_project_or_render_expansion(self):
        project = copy.deepcopy(self.project)
        project["spec"]["clusterResourceWhitelist"].append({"group": "", "kind": "PersistentVolume"})
        self.assertFalse(safe(project, self.stack, self.objects))
        project = copy.deepcopy(self.project)
        project["spec"]["sourceRepos"].append("*")
        self.assertFalse(safe(project, self.stack, self.objects))
        objects = copy.deepcopy(self.objects)
        objects.append({"kind": "ClusterRole", "metadata": {"name": "multica", "namespace": "ai"}})
        self.assertFalse(safe(self.project, self.stack, objects))
        self.assertFalse(safe(self.project, self.stack.replace('project = "homelab-workloads"', 'project = "homelab"'), self.objects))


if __name__ == "__main__":
    unittest.main()
