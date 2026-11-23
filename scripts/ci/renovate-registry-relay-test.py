#!/usr/bin/env python3
"""Check the excluded hosted Renovate registry candidate's network boundary."""

import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
TRAEFIK = ROOT / "clusters/homelab/apps/traefik"
CANDIDATE = TRAEFIK / "renovate-registry-candidate"
NAME = "renovate-registry-relay"


def yaml_json(source):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(source)], text=True))


class RegistryRelay(unittest.TestCase):
    def test_candidate_stays_excluded_and_scaled_down(self):
        active_resources = {(TRAEFIK / resource).resolve() for resource in
                            yaml_json(TRAEFIK / "kustomization.yaml")["resources"]}
        self.assertNotIn(CANDIDATE, active_resources)
        stage = yaml_json(CANDIDATE / "deployment.yaml")
        self.assertEqual(stage["spec"]["replicas"], 0)
        pod = stage["spec"]["template"]["spec"]
        self.assertIs(pod["automountServiceAccountToken"], False)
        self.assertEqual(pod["serviceAccountName"], NAME)
        relay, tailscale = pod["containers"]
        for container in (relay, tailscale):
            self.assertRegex(container["image"], r"^harbor\.stinkyboi\.com/mirror/.+@sha256:[0-9a-f]{64}$")
        self.assertIn("--entrypoints.relay.address=127.0.0.1:8443", relay["args"])
        self.assertIn("--entrypoints.health.address=127.0.0.1:8080", relay["args"])
        self.assertIn("--ping.entrypoint=health", relay["args"])
        self.assertIn("--tun=userspace-networking", tailscale["args"])
        for probe in ("livenessProbe", "readinessProbe"):
            self.assertIn("--entrypoints.health.address=127.0.0.1:8080", relay[probe]["exec"]["command"])
            self.assertIn("--socket=/run/tailscale/tailscaled.sock", tailscale[probe]["exec"]["command"])
        self.assertNotIn("state-api", {mount["name"] for mount in relay["volumeMounts"]})
        self.assertIn("state-api", {mount["name"] for mount in tailscale["volumeMounts"]})
        start = (CANDIDATE / "activate.sh").read_text()
        self.assertIn("--accept-dns=false --accept-routes=false", start)
        self.assertIn("--tcp=443 tcp://127.0.0.1:8443", start)
        self.assertNotIn("funnel", start)

    def test_relay_preserves_tls_to_only_registry(self):
        route = yaml_json(CANDIDATE / "routes.yaml")["tcp"]
        self.assertEqual(route, {
            "routers": {"harbor": {"entryPoints": ["relay"], "rule": "HostSNI(`harbor.stinkyboi.com`)",
                                  "service": "harbor", "tls": {"passthrough": True}}},
            "services": {"harbor": {"loadBalancer": {
                "servers": [{"address": "traefik-registry.traefik.svc.cluster.local:443"}]}}},
        })
        values = yaml_json(TRAEFIK / "values.yaml")
        self.assertEqual(values["service"]["registry"]["ports"], {"https": {"port": 443, "targetPort": 9443}})

    def test_only_exact_service_account_and_state_secret_are_admitted(self):
        rendered = subprocess.check_output(["kustomize", "build", str(CANDIDATE)], text=True)
        result = subprocess.check_output(["yq", "ea", "-o=json", "-I=0", "[.]", "-"],
                                         input=rendered, text=True)
        resources = {item["kind"]: item for item in json.loads(result)}
        self.assertNotIn("Service", resources)
        self.assertNotIn("Secret", resources)
        rule, = resources["AuthorizationPolicy"]["spec"]["rules"]
        self.assertEqual(rule, {
            "from": [{"source": {"principals": [f"cluster.local/ns/traefik/sa/{NAME}"]}}],
            "to": [{"operation": {"ports": ["9443"]}}],
        })
        self.assertEqual(resources["Role"]["rules"], [{
            "apiGroups": [""], "resources": ["secrets"], "resourceNames": [f"{NAME}-state"],
            "verbs": ["get", "update", "patch"],
        }])


if __name__ == "__main__":
    unittest.main()
