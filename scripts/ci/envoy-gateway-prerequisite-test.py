#!/usr/bin/env python3
"""Keep Envoy Gateway CRD ownership and mirrored image pins separate."""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "clusters/homelab/platform/envoy-gateway"
IMAGES = {
    "envoyGateway": ("gateway", "9d67017c442a70e6ae9f1a358e6c80eb653c67c2e40823d9a991e0daf37ba926"),
    "envoyProxy": ("envoy", "7369b033550a14997e5d698677b7b51f0210a80754f5d084c5caa1a78268267b"),
    "ratelimit": ("ratelimit", "5fdd8e3ae335ab6d64316f8d2fd9a886830075cbbb40a1d8065c869275909162"),
}


def yaml_documents(path):
    result = subprocess.run(
        ["yq", "-o=json", "-I=0", ".", str(path)],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return [json.loads(line) for line in result.stdout.splitlines()]


class EnvoyGatewayPrerequisiteTests(unittest.TestCase):
    def test_single_crd_owner_and_private_class(self):
        crds, = yaml_documents(SOURCE / "crds-values.yaml")
        controller, = yaml_documents(SOURCE / "values.yaml")
        gateway_class, = yaml_documents(SOURCE / "gatewayclass.yaml")
        self.assertEqual(crds, {"crds": {"gatewayAPI": {
            "enabled": True, "channel": "experimental"},
            "envoyGateway": {"enabled": True}}})
        self.assertEqual(controller["crds"], {"enabled": False})
        self.assertEqual(controller["service"], {"type": "ClusterIP"})
        self.assertEqual(controller["deployment"]["annotations"], {
            "argocd.argoproj.io/sync-wave": "1"})
        self.assertEqual(gateway_class["kind"], "GatewayClass")
        self.assertEqual(gateway_class["metadata"]["name"], "envoy-gateway")
        self.assertEqual(gateway_class["metadata"]["annotations"], {
            "argocd.argoproj.io/sync-wave": "2"})
        self.assertEqual(gateway_class["spec"], {
            "controllerName": "gateway.envoyproxy.io/gatewayclass-controller"})
        self.assertNotIn("listeners", gateway_class["spec"])

    def test_every_chart_image_is_bound_to_catalog_digest(self):
        values, = yaml_documents(SOURCE / "values.yaml")
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        sources = {entry["source"] for entry in catalog["images"]}
        self.assertEqual(set(values["global"]["images"]), set(IMAGES))
        for key, (repository, digest) in IMAGES.items():
            image = values["global"]["images"][key]
            self.assertEqual(image, {"image": "harbor.stinkyboi.com/mirror/"
                              f"docker.io/envoyproxy/{repository}:{digest}@sha256:{digest}",
                              "pullPolicy": "IfNotPresent"})
            self.assertTrue(any(source.startswith(f"docker.io/envoyproxy/{repository}:")
                                and source.endswith(f"@sha256:{digest}") for source in sources))


if __name__ == "__main__":
    unittest.main()
