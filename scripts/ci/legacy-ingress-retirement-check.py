#!/usr/bin/env python3
"""Audit the old app ingress before cutover; --retired verifies source cleanup."""

import argparse
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
APPS = frozenset("""affine argocd bazarr compass deluge dispatcharr grafana harbor
kiali langfuse litellm multica n8n nofx policy-bot prowlarr radarr sonarr""".split())
ISTIO = "https://istio-ingressgateway.istio-system.svc.cluster.local:443"
BAZARR = "http://bazarr.media.svc.cluster.local:6767"
CLUSTER_BACKEND = re.compile(
    r"http://[a-z0-9-]+\.[a-z0-9-]+\.svc\.cluster\.local:[1-9][0-9]{0,4}"
)


def yaml(path=None, source=None):
    command = ["yq", "-o=json", ".", str(ROOT / path) if path else "-"]
    return json.loads(subprocess.run(command, input=source, text=True,
                                     capture_output=True, check=True).stdout)


def catalog():
    result = subprocess.run(["yq", "ea", "-o=json", "-I=0", "[.]",
                             str(ROOT / "docs/examples/octelium/homelab-services.yaml")],
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def yaml_documents(path):
    result = subprocess.run(["yq", "ea", "-o=json", "-I=0", "[.]", str(path)],
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retired", action="store_true",
                        help="Fail until every legacy app source and the wildcard gateway are gone")
    args = parser.parse_args()

    routes = yaml("clusters/homelab/apps/traefik/routes.yaml")["http"]
    dns = set(yaml("clusters/homelab/apps/traefik/values.yaml")["service"]["private"]
              ["annotations"]["coredns.io/hostname"].split(","))
    services = {row["metadata"]["name"]: row for row in catalog()
                if row.get("kind") == "Service"}
    tunnel = yaml(source=yaml("clusters/homelab/apps/octelium-public/configmap.yaml")
                  ["data"]["config.yaml"])["ingress"]
    tunnel_hosts = {row.get("hostname") for row in tunnel}
    virtual_hosts = set()
    for path in (ROOT / "clusters/homelab").rglob("virtualservice*.yaml"):
        for resource in yaml_documents(path):
            if resource.get("kind") == "VirtualService":
                virtual_hosts.update(resource.get("spec", {}).get("hosts", []))

    errors = []
    pending = []
    for app in sorted(APPS):
        host = f"{app}.stinkyboi.com"
        router = routes["routers"].get(app, {})
        backend = routes["services"].get(app, {}).get("loadBalancer", {}).get("servers", [])
        if (router.get("rule") != f"Host(`{host}`)" or
                router.get("entryPoints") != ["websecure"] or
                router.get("service") != app or host not in dns or
                len(backend) != 1 or not CLUSTER_BACKEND.fullmatch(backend[0].get("url", "")) or
                any(part in backend[0]["url"] for part in ("istio-ingressgateway", "octelium-ingress"))):
            errors.append(f"{app}: direct private Traefik route or DNS missing")
        old = services.get(app)
        if old is not None:
            expected = BAZARR if app == "bazarr" else ISTIO
            if (old.get("spec", {}).get("mode") != "WEB" or
                    old["spec"].get("isPublic") is not True or
                    old["spec"].get("config", {}).get("upstream", {}).get("url") != expected):
                errors.append(f"{app}: unexpected Octelium Service shape")
            pending.append(f"{app}: Octelium catalog")
        if host in tunnel_hosts:
            pending.append(f"{app}: Cloudflared host")
        if host in virtual_hosts:
            pending.append(f"{app}: Istio VirtualService")

    gateway = yaml("clusters/homelab/apps/istio/tailnet-gateway.yaml")
    if any("*.stinkyboi.com" in server.get("hosts", []) for server in gateway["spec"]["servers"]):
        pending.append("Istio Gateway: broad wildcard host")
    if args.retired:
        errors.extend(pending)
    for item in errors:
        print(f"FAIL: {item}")
    if not errors:
        print(f"PASS: {len(APPS)} direct private app routes; " +
              ("legacy app ingress absent" if args.retired else f"{len(pending)} legacy source entries remain"))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
