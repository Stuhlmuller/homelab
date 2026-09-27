#!/usr/bin/env python3
"""Verify desktop auth bypasses Octelium only on Multica API paths."""

import json
from pathlib import Path
import subprocess


root = Path(__file__).resolve().parents[2]


def yaml_file(path):
    return json.loads(subprocess.run(
        ["yq", "-o=json", ".", path], check=True, capture_output=True, text=True,
    ).stdout)


def yaml_text(value):
    return json.loads(subprocess.run(
        ["yq", "-o=json", "."], input=value, check=True, capture_output=True, text=True,
    ).stdout)


public = yaml_file(root / "clusters/homelab/apps/octelium-public/configmap.yaml")
ingress = yaml_text(public["data"]["config.yaml"])["ingress"]
multica = [rule for rule in ingress if rule.get("hostname") == "multica.stinkyboi.com"]
assert multica[0] == {
    "hostname": "multica.stinkyboi.com",
    "path": r"^/(api|auth|ws)(/.*)?$",
    "service": "https://istio-ingressgateway.istio-system.svc.cluster.local:443",
    "originRequest": {
        "originServerName": "multica.stinkyboi.com",
        "httpHostHeader": "multica.stinkyboi.com",
    },
}
assert multica[1]["service"] == "http://octelium-ingress-dataplane.octelium.svc.cluster.local:8080"
deployment = yaml_file(root / "clusters/homelab/apps/octelium-public/deployment.yaml")
assert deployment["spec"]["template"]["metadata"]["annotations"][
    "homelab.rst.io/cloudflared-config-revision"
] == "multica-desktop-auth-2026-09-27"

virtual_service = yaml_file(root / "clusters/homelab/apps/multica/virtualservice.yaml")
api, frontend = virtual_service["spec"]["http"]
assert [match["uri"]["prefix"] for match in api["match"]] == ["/api", "/auth", "/ws"]
assert api["route"][0]["destination"] == {
    "host": "multica-backend.ai.svc.cluster.local",
    "port": {"number": 8080},
}
assert "retries" not in api
assert frontend["route"][0]["destination"]["host"] == "multica-frontend.ai.svc.cluster.local"

policies = json.loads(subprocess.run(
    ["yq", "ea", "-o=json", "-I=0", "[.]", root / "clusters/homelab/apps/multica/authorizationpolicy.yaml"],
    check=True, capture_output=True, text=True,
).stdout)
backend = next(policy for policy in policies if policy["metadata"]["name"] == "multica-backend-allow-required-clients")
principals = backend["spec"]["rules"][0]["from"][0]["source"]["principals"]
assert "cluster.local/ns/istio-system/sa/istio-ingressgateway" in principals

print("Multica desktop auth route checks passed")
