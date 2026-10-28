#!/usr/bin/env python3
"""Keep staged Istio Helm image values bound to the reviewed mirror catalog."""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERLAYS = ROOT / "clusters/homelab/apps/istio/upgrade-1.28.10"
CATALOG = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())["images"]


def image(repository, version):
    prefix = f"{repository}:{version}-distroless@sha256:"
    matches = [entry["source"] for entry in CATALOG if entry["source"].startswith(prefix)]
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0][len(prefix):]):
        raise AssertionError(f"missing or ambiguous reviewed Istio image: {repository}:{version}")
    return f"harbor.stinkyboi.com/mirror/{matches[0]}"


class IstioImageOverlays(unittest.TestCase):
    def test_exact_staged_values_match_reviewed_catalog(self):
        pilot = image("docker.io/istio/pilot", "1.28.10")
        cni = image("docker.io/istio/install-cni", "1.28.10")
        ztunnel = image("docker.io/istio/ztunnel", "1.28.10")
        old_proxy = image("docker.io/istio/proxyv2", "1.27.3")
        new_proxy = image("docker.io/istio/proxyv2", "1.28.10")
        expected = {
            "istiod-images.json": {"image": pilot, "global": {"proxy": {"image": old_proxy}}},
            "istiod-final-images.json": {"image": pilot, "global": {"proxy": {"image": new_proxy}}},
            "cni-images.json": {"image": cni},
            "ztunnel-images.json": {"image": ztunnel},
            "gateway-images.json": {
                "podAnnotations": {"sidecar.istio.io/proxyImage": new_proxy}
            },
        }
        self.assertEqual({path.name for path in OVERLAYS.glob("*.json")}, set(expected))
        for name, values in expected.items():
            with self.subTest(name=name):
                self.assertEqual(json.loads((OVERLAYS / name).read_text()), values)


if __name__ == "__main__":
    unittest.main()
