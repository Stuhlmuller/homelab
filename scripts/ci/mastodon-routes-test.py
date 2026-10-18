#!/usr/bin/env python3
"""Keep Mastodon's public route away from private apps and datastores."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/mastodon"


def documents(name):
    return json.loads(subprocess.check_output([
        "yq", "eval-all", "-o=json", ". as $doc ireduce ([]; . + [$doc])",
        str(APP / name),
    ], text=True))


class Routes(unittest.TestCase):
    def test_public_route_only_reaches_mastodon(self):
        spec = documents("virtualservice.yaml")[0]["spec"]
        self.assertEqual(spec["hosts"], ["mastodon.stinkyboi.com"])
        self.assertEqual(spec["gateways"], ["istio-system/tailnet-gateway"])
        streaming, web = spec["http"]
        self.assertEqual(streaming["match"], [
            {"uri": {"exact": "/api/v1/streaming"}},
            {"uri": {"prefix": "/api/v1/streaming/"}},
        ])
        for route, service, port in [
            (streaming, "mastodon-streaming", 4000), (web, "mastodon-web", 3000),
        ]:
            self.assertEqual(route["route"], [{"destination": {
                "host": f"{service}.mastodon.svc.cluster.local", "port": {"number": port},
            }}])
        self.assertNotIn("match", web)

    def test_streaming_trust_avoids_unsafe_ipv6_subnets(self):
        environment = documents("configmap.yaml")[0]["data"]["streaming.env"]
        entries = dict(line.split("=", 1) for line in environment.splitlines() if "=" in line)
        self.assertEqual(entries["TRUSTED_PROXY_IP"], "loopback,uniquelocal")

    def test_gateway_cannot_reach_datastore_ports(self):
        peer, default, allowed = documents("authorizationpolicy.yaml")
        self.assertEqual(peer["spec"]["mtls"]["mode"], "STRICT")
        self.assertEqual(default["spec"], {})
        gateway, workload = allowed["spec"]["rules"]
        self.assertEqual(gateway["from"], [{"source": {"principals": [
            "cluster.local/ns/istio-system/sa/istio-ingressgateway",
        ]}}])
        self.assertEqual(gateway["to"], [{"operation": {"ports": ["3000", "4000"]}}])
        self.assertEqual(workload["from"], [{"source": {"principals": [
            "cluster.local/ns/mastodon/sa/mastodon",
        ]}}])


if __name__ == "__main__":
    unittest.main()
