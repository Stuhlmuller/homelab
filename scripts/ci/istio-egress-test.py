#!/usr/bin/env python3
"""Keep the staged Istio egress rule caller and destination exact."""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "clusters/homelab/platform/istio-egress"
UNIT = ROOT / "IaC/live/argocd-apps/platform-istio-egress"


def documents(path):
    result = subprocess.run(
        ["yq", "-o=json", "-I=0", ".", str(path)],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return [json.loads(line) for line in result.stdout.splitlines()]


class IstioEgressTests(unittest.TestCase):
    def test_openrouter_route_and_caller(self):
        kustomization, = documents(SOURCE / "kustomization.yaml")
        self.assertEqual(kustomization["resources"], [
            "namespace.yaml", "waypoint.yaml", "openrouter.yaml"])
        namespace, = documents(SOURCE / "namespace.yaml")
        waypoint, = documents(SOURCE / "waypoint.yaml")
        service, policy = documents(SOURCE / "openrouter.yaml")
        self.assertEqual(namespace["metadata"]["labels"]["istio.io/dataplane-mode"], "ambient")
        self.assertEqual(namespace["metadata"]["labels"]["istio.io/use-waypoint"], "waypoint")
        self.assertEqual(waypoint["spec"]["gatewayClassName"], "istio-waypoint")
        self.assertEqual(waypoint["metadata"]["labels"]["istio.io/waypoint-for"], "service")
        self.assertEqual(waypoint["spec"]["listeners"], [
            {"name": "mesh", "port": 15008, "protocol": "HBONE"}])
        self.assertEqual(service["spec"], {
            "hosts": ["openrouter.ai"], "location": "MESH_EXTERNAL",
            "ports": [{"number": 443, "name": "tls", "protocol": "TLS"}],
            "resolution": "DNS"})
        litellm, = documents(ROOT / "clusters/homelab/apps/litellm/values.yaml")
        self.assertEqual(litellm["serviceAccount"]["name"], "litellm")
        self.assertEqual(litellm["podAnnotations"]["ambient.istio.io/dns-capture"], "true")
        self.assertEqual(litellm["proxy_config"]["model_list"][0]["litellm_params"]["api_base"],
                         "https://openrouter.ai/api/v1")
        self.assertEqual(policy["spec"], {
            "targetRefs": [{"group": "networking.istio.io", "kind": "ServiceEntry",
                            "name": "openrouter"}],
            "action": "ALLOW",
            "rules": [{"from": [{"source": {"principals": [
                "cluster.local/ns/ai/sa/litellm"]}}],
                "to": [{"operation": {"ports": ["443"]}}]}]})
        self.assertEqual(waypoint["metadata"]["namespace"], "istio-egress")
        self.assertEqual(service["metadata"]["namespace"], "istio-egress")
        self.assertEqual(policy["metadata"]["namespace"], "istio-egress")

    def test_registration_stays_disabled_until_prerequisites(self):
        result = subprocess.run(
            ["terragrunt", "--working-dir", str(UNIT), "--log-disable",
             "render", "--json", "--write=false", "--no-color"],
            capture_output=True, text=True, check=True, timeout=30)
        rendered = json.loads(result.stdout)
        self.assertEqual(rendered["locals"]["stack_values"]["dependencies"],
                         ["istio", "platform-gateway-api-crds"])
        app = rendered["inputs"]["manifest"]
        self.assertEqual(app["metadata"]["name"], "platform-istio-egress")
        self.assertEqual(app["spec"]["destination"]["namespace"], "istio-egress")
        self.assertEqual(app["spec"]["sources"], [{
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": "clusters/homelab/platform/istio-egress", "targetRevision": "main"}])
        self.assertFalse(app["spec"]["syncPolicy"]["automated"]["enabled"])
        self.assertFalse(app["spec"]["syncPolicy"]["automated"]["prune"])
        project, = documents(ROOT / "clusters/homelab/argocd/self-management/appproject.yaml")
        self.assertIn({"server": "https://kubernetes.default.svc", "namespace": "istio-egress"},
                      project["spec"]["destinations"])


if __name__ == "__main__":
    unittest.main()
