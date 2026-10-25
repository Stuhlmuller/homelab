#!/usr/bin/env python3
"""Check the generated, dormant Envoy Gateway Application boundary."""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "IaC/homelab/us-west-2/apps/platform-envoy-gateway/argocd"


class EnvoyGatewayRegistrationTests(unittest.TestCase):
    def test_project_permits_only_declared_source_and_namespace(self):
        result = subprocess.run(
            ["yq", "-o=json", "-I=0", ".",
             str(ROOT / "clusters/homelab/argocd/self-management/appproject.yaml")],
            capture_output=True, text=True, check=True, timeout=15,
        )
        project, = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertIn("docker.io/envoyproxy", project["spec"]["sourceRepos"])
        self.assertIn({"server": "https://kubernetes.default.svc",
                       "namespace": "envoy-gateway-system"}, project["spec"]["destinations"])
        for resource in ({"group": "apiextensions.k8s.io", "kind": "CustomResourceDefinition"},
                         {"group": "gateway.networking.k8s.io", "kind": "GatewayClass"},
                         {"group": "admissionregistration.k8s.io",
                          "kind": "ValidatingAdmissionPolicy"},
                         {"group": "admissionregistration.k8s.io",
                          "kind": "ValidatingAdmissionPolicyBinding"}):
            self.assertIn(resource, project["spec"]["clusterResourceWhitelist"])

    def test_generated_application_is_single_owner_and_disabled(self):
        result = subprocess.run(
            ["terragrunt", "--working-dir", str(UNIT), "--log-disable",
             "render", "--json", "--write=false", "--no-color"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        app = json.loads(result.stdout)["inputs"]["manifest"]
        self.assertEqual(app["metadata"]["name"], "platform-envoy-gateway")
        self.assertEqual(app["spec"]["project"], "homelab")
        self.assertEqual(app["spec"]["destination"]["namespace"], "envoy-gateway-system")
        sync = app["spec"]["syncPolicy"]
        self.assertFalse(sync["automated"]["enabled"])
        self.assertFalse(sync["automated"]["prune"])
        self.assertIn("ServerSideApply=true", sync["syncOptions"])
        sources = app["spec"]["sources"]
        self.assertEqual(len(sources), 4)
        self.assertEqual([(source["repoURL"], source["chart"], source["targetRevision"])
                          for source in sources if "chart" in source], [
            ("docker.io/envoyproxy", "gateway-crds-helm", "v1.9.2"),
            ("docker.io/envoyproxy", "gateway-helm", "v1.9.2"),
        ])
        self.assertEqual([(source["path"], source["targetRevision"])
                          for source in sources if "chart" not in source], [
            (".", "main"), ("clusters/homelab/platform/envoy-gateway", "main"),
        ])
        self.assertEqual(sources[2]["directory"]["include"],
                         ".argocd-values-ref-placeholder.yaml")
        self.assertEqual(sources[2]["ref"], "values")
        self.assertEqual(sources[0]["helm"]["valueFiles"],
                         ["$values/clusters/homelab/platform/envoy-gateway/crds-values.yaml"])
        self.assertEqual(sources[1]["helm"]["valueFiles"],
                         ["$values/clusters/homelab/platform/envoy-gateway/values.yaml"])


if __name__ == "__main__":
    unittest.main()
