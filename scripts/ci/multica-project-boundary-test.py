#!/usr/bin/env python3
"""Check Multica project wiring, overlay, and exact pinned OCI chart."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "clusters/homelab/argocd/self-management/workloads-appproject.yaml"
STACK = ROOT / "IaC/homelab/us-west-2/apps/multica/stack.hcl"
APP = ROOT / "clusters/homelab/apps/multica"
CATALOG = ROOT / "scripts/config/harbor-helm-charts.json"
CHART_REF = "oci://ghcr.io/multica-ai/charts/multica"
CHART_VERSION = "0.4.29"
CHART_SHA256 = "e2d74f3cece74b1dd69dfb006f9f427af004a93faca5700c3e44a3e98f842cdd"
RENDER_CHART = "--chart" in sys.argv
if RENDER_CHART:
    sys.argv.remove("--chart")
OVERLAY_KINDS = {
    "AuthorizationPolicy", "ConfigMap", "Deployment", "ExternalSecret",
    "NetworkPolicy", "PersistentVolumeClaim", "Service", "ServiceAccount",
    "VirtualService",
}
CHART_KINDS = {"ConfigMap", "Deployment", "PersistentVolumeClaim", "Service"}


def safe(project, stack, objects, chart_objects=None):
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
    source = f'''{{
        repoURL        = "ghcr.io/multica-ai/charts"
        chart          = "multica"
        path           = "."
        targetRevision = "{CHART_VERSION}"
        helm = {{
          releaseName = "multica"
          valueFiles  = ["$values/clusters/homelab/apps/multica/values.yaml"]
        }}
      }}'''
    if ('project = "homelab-workloads"' not in stack or
            " ".join(stack.split()).count(" ".join(source.split())) != 1):
        return False
    if not objects or not all(obj.get("kind") in OVERLAY_KINDS and
                              obj.get("metadata", {}).get("namespace") == "ai" for obj in objects):
        return False
    # Helm's release namespace supplies the default for omitted object namespaces.
    return chart_objects is None or (bool(chart_objects) and all(
        obj.get("kind") in CHART_KINDS and
        obj.get("metadata", {}).get("namespace") in (None, "ai") for obj in chart_objects))


def render_chart():
    catalog = json.loads(CATALOG.read_text())
    matching = [row for row in catalog["charts"] if row.get("chart") == "multica"]
    if matching != [{"chart": "multica", "version": CHART_VERSION,
                     "repository": "ghcr.io/multica-ai/charts", "sha256": CHART_SHA256}]:
        raise AssertionError("reviewed Multica chart catalog identity changed")
    with tempfile.TemporaryDirectory(prefix="multica-chart-check-") as temporary:
        directory = Path(temporary)
        registry = directory / "registry.json"
        registry.write_text('{"auths":{}}\n')
        env = {**os.environ, "DOCKER_CONFIG": str(directory)}
        subprocess.run(["helm", "pull", CHART_REF, "--version", CHART_VERSION,
                        "--destination", str(directory), "--registry-config", str(registry)],
                       env=env, check=True, capture_output=True, timeout=90)
        package = directory / f"multica-{CHART_VERSION}.tgz"
        if hashlib.sha256(package.read_bytes()).hexdigest() != CHART_SHA256:
            raise AssertionError("Multica chart package differs from reviewed digest")
        rendered = subprocess.check_output([
            "helm", "template", "multica", str(package), "--namespace", "ai",
            "--include-crds", "--values", str(APP / "values.yaml")],
            text=True, timeout=90)
    return json.loads(subprocess.check_output(
        ["yq", "eval-all", "-o=json", "-I=0", "[.]", "-"],
        input=rendered, text=True))


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
        cls.chart_objects = render_chart() if RENDER_CHART else None

    def test_namespaced_multica_contract(self):
        self.assertTrue(safe(self.project, self.stack, self.objects, self.chart_objects))

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
        self.assertFalse(safe(self.project, self.stack, self.objects, [
            {"kind": "ClusterRole", "metadata": {"name": "multica", "namespace": "ai"}}]))
        self.assertFalse(safe(self.project, self.stack, self.objects, [
            {"kind": "CSIDriver", "metadata": {"name": "multica", "namespace": "ai"}}]))
        self.assertFalse(safe(self.project, self.stack.replace('project = "homelab-workloads"', 'project = "homelab"'), self.objects))
        self.assertFalse(safe(self.project, self.stack.replace('targetRevision = "0.4.29"', 'targetRevision = "0.4.30"'), self.objects))


if __name__ == "__main__":
    unittest.main()
