#!/usr/bin/env python3
"""Validate the reviewed private DNS source and its pinned Helm render."""

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "clusters/homelab/apps/traefik/values.yaml"
ROUTES = ROOT / "clusters/homelab/apps/traefik/routes.yaml"
DNS_VALUES = ROOT / "clusters/homelab/platform/tailnet-dns/values.yaml"
INVENTORY = ROOT / "scripts/config/tailscale-private-dns.json"
CHART = "oci://codeberg.org/k8s-gateway/charts/k8s-gateway"
CHART_DIGEST = "sha256:b02209df03b08706179875b6e1887cb6064a589b591a0ce1e809a354811e37a7"
IMAGE = ("harbor.stinkyboi.com/mirror/codeberg.org/k8s-gateway/k8s_gateway:1.9.0@"
         "sha256:0b556f261d46873d7d2e86e5d345bb99db30de6b3869b83e32d273a466e980e4")
CORDIUM_RULE = r"^[^.]+\.cordium\.stinkyboi\.com$"
HOST = re.compile(r"Host\(`([^`]+)`\)")
HOST_REGEXP = re.compile(r"HostRegexp\(`([^`]+)`\)")
NAME = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*stinkyboi\.com")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_yaml(path):
    return json.loads(subprocess.check_output(
        ["yq", "ea", "-o=json", "-I=0", "select(document_index == 0)", str(path)], text=True))


def approved_names(values, routes, inventory, *, initial=False):
    services = values["service"]
    selected = [name for name, service in services.items()
                if service.get("labels", {}).get("homelab.rst.io/private-dns") == "approved"]
    require(selected == ["private"], "only the private Traefik Service may publish DNS")
    private = services["private"]
    require(private.get("type") == "LoadBalancer" and private.get("loadBalancerClass") == "tailscale",
            "DNS source must be the Tailscale LoadBalancer")
    declaration = private.get("annotations", {}).get("coredns.io/hostname")
    require(isinstance(declaration, str), "private Service hostname annotation is missing")
    names = [name.strip() for name in declaration.split(",")]
    require(all(names) and len(names) == len(set(names)), "blank or duplicate private DNS name")
    require(all(NAME.fullmatch(name) or name == "*.cordium.stinkyboi.com" for name in names),
            "private DNS name is outside the approved zone or wildcard scope")
    require(not set(names) & set(inventory["retired_hostnames"]), "retired name is republished")

    routed = []
    for router in routes["http"]["routers"].values():
        if "websecure" not in router.get("entryPoints", []):
            continue
        rule = router["rule"]
        hosts = HOST.findall(rule)
        regexps = [value.replace("\\\\", "\\") for value in HOST_REGEXP.findall(rule)]
        require(all(value == CORDIUM_RULE for value in regexps), "unreviewed private HostRegexp")
        require(hosts or regexps, "private HTTPS router has no host")
        routed.extend(hosts)
        routed.extend("*.cordium.stinkyboi.com" for _ in regexps)
    require(len(routed) == len(set(routed)), "duplicate private HTTPS route name")
    require(set(names) == set(routed), "private Service DNS names differ from HTTPS route names")
    if initial:
        require(set(names) == set(inventory["hostnames"]) and len(names) == len(inventory["hostnames"]) == 27,
                "first migration must match the fixed 27-name inventory")
    return set(names)


def expect_reject(values, routes, inventory, message):
    try:
        approved_names(values, routes, inventory)
    except ValueError:
        return
    raise AssertionError(message)


def mutation_checks(values, routes, inventory):
    added_values, added_routes = copy.deepcopy(values), copy.deepcopy(routes)
    added_values["service"]["private"]["annotations"]["coredns.io/hostname"] += ",probe.stinkyboi.com"
    added_routes["http"]["routers"]["probe"] = {
        "entryPoints": ["websecure"], "rule": "Host(`probe.stinkyboi.com`)"}
    approved_names(added_values, added_routes, inventory)
    try:
        approved_names(added_values, added_routes, inventory, initial=True)
    except ValueError:
        pass
    else:
        raise AssertionError("future addition passed the one-time migration check")

    renamed_values, renamed_routes = copy.deepcopy(values), copy.deepcopy(routes)
    renamed_values["service"]["private"]["annotations"]["coredns.io/hostname"] = (
        renamed_values["service"]["private"]["annotations"]["coredns.io/hostname"]
        .replace("affine.stinkyboi.com", "new-affine.stinkyboi.com"))
    renamed_routes["http"]["routers"]["affine"]["rule"] = "Host(`new-affine.stinkyboi.com`)"
    approved_names(renamed_values, renamed_routes, inventory)

    removed_values, removed_routes = copy.deepcopy(values), copy.deepcopy(routes)
    removed_values["service"]["private"]["annotations"]["coredns.io/hostname"] = (
        removed_values["service"]["private"]["annotations"]["coredns.io/hostname"]
        .replace("affine.stinkyboi.com,", ""))
    del removed_routes["http"]["routers"]["affine"]
    approved_names(removed_values, removed_routes, inventory)

    expect_reject(added_values, routes, inventory, "DNS name without private route passed")
    added_values["service"]["private"]["annotations"]["coredns.io/hostname"] += ",probe.stinkyboi.com"
    expect_reject(added_values, added_routes, inventory, "duplicate DNS name passed")

    for name in ("n8n-webhook.stinkyboi.com", "outside.example.com"):
        changed_values, changed_routes = copy.deepcopy(values), copy.deepcopy(routes)
        changed_values["service"]["private"]["annotations"]["coredns.io/hostname"] += "," + name
        changed_routes["http"]["routers"]["probe"] = {
            "entryPoints": ["websecure"], "rule": f"Host(`{name}`)"}
        expect_reject(changed_values, changed_routes, inventory, f"{name} passed")

    public_only_values, public_only_routes = copy.deepcopy(values), copy.deepcopy(routes)
    public_only_values["service"]["private"]["annotations"]["coredns.io/hostname"] += ",public-only.stinkyboi.com"
    public_only_routes["http"]["routers"]["public-only"] = {
        "entryPoints": ["funnel"], "rule": "Host(`public-only.stinkyboi.com`)"}
    expect_reject(public_only_values, public_only_routes, inventory, "public-only route passed")

    # A Compass discovery Ingress cannot authorize a new name without a Traefik route.
    compass_values = copy.deepcopy(values)
    compass_values["service"]["private"]["annotations"]["coredns.io/hostname"] += ",discovery-only.stinkyboi.com"
    expect_reject(compass_values, routes, inventory, "Compass-only name passed")

    second_service = copy.deepcopy(values)
    second_service["service"]["other"] = {"labels": {"homelab.rst.io/private-dns": "approved"}}
    expect_reject(second_service, routes, inventory, "second selected Service passed")
    require(re.fullmatch(CORDIUM_RULE, "team.cordium.stinkyboi.com") is not None
            and re.fullmatch(CORDIUM_RULE, "two.team.cordium.stinkyboi.com") is None,
            "Cordium wildcard must match one label")


def rendered_contract():
    dns_values = load_yaml(DNS_VALUES)
    servers = dns_values["servers"]
    require(len(servers) == 2 and all(s["servicePort"] == 53 for s in servers),
            "both resolver views must expose DNS port 53")
    command = ["helm", "template", "tailnet-dns", CHART, "--version", "4.0.0",
               "--namespace", "tailnet-dns", "-f", str(DNS_VALUES)]
    chart = subprocess.run(command, text=True, capture_output=True, check=True)
    require(CHART_DIGEST in chart.stderr, "chart 4.0.0 OCI digest changed")
    rendered = chart.stdout
    documents = json.loads(subprocess.check_output(
        ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=rendered, text=True))
    resources = {(doc["kind"], doc["metadata"]["name"]): doc for doc in documents}
    require(all(doc["metadata"].get("namespace", "tailnet-dns") == "tailnet-dns" for doc in documents),
            "resolver chart changed the cluster DNS namespace")
    service = resources["Service", "tailnet-dns"]
    require(service["spec"]["type"] == "LoadBalancer"
            and service["spec"]["loadBalancerClass"] == "tailscale"
            and service["metadata"]["annotations"] == {
                "tailscale.com/hostname": "homelab-dns", "tailscale.com/tags": "tag:homelab-ingress"},
            "DNS Service must use its unique hostname and operator-owned ingress tag")
    require({(p["protocol"], p["port"], p["targetPort"]) for p in service["spec"]["ports"]}
            == {("UDP", 53, 1053), ("TCP", 53, 1053)}, "DNS requires UDP and TCP 53")

    deployment = resources["Deployment", "tailnet-dns-k8s-gateway"]
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    require(deployment["spec"]["replicas"] == 2 and container["image"] == IMAGE,
            "resolver replicas or pinned Harbor image changed")
    require(pod["securityContext"]["runAsNonRoot"] is True
            and container["securityContext"]["readOnlyRootFilesystem"] is True
            and container["securityContext"]["capabilities"]["drop"] == ["ALL"],
            "resolver Pod security changed")
    require("readinessProbe" in container and "livenessProbe" in container,
            "resolver probes are required")

    corefile = resources["ConfigMap", "tailnet-dns-k8s-gateway"]["data"]["Corefile"]
    blocks = corefile.split(".:1053 {")
    require(len(blocks) == 3 and "view private-addresses" in blocks[1]
            and "expr type() in ['A', 'AAAA']" in blocks[1]
            and "view " not in blocks[2] and "k8s_gateway" not in blocks[2],
            "A/AAAA private view or public non-address forwarding changed")
    require("k8s_gateway stinkyboi.com" in blocks[1]
            and "resources Service" in blocks[1]
            and "serviceLabelSelectors homelab.rst.io/private-dns=approved" in blocks[1]
            and "loadBalancerAddressPreference ip" in blocks[1]
            and "fallthrough" in blocks[1]
            and "ttl 30" in blocks[1]
            and all("forward . 1.1.1.1 1.0.0.1" in block and "cache 30" in block
                    for block in blocks[1:]), "private source or public forwarding changed")
    role = resources["ClusterRole", "tailnet-dns-k8s-gateway"]
    allowed = {"customresourcedefinitions", "services", "namespaces", "endpointslices"}
    granted = {resource for rule in role["rules"] for resource in rule["resources"]}
    require(granted <= allowed and "services" in granted
            and all(set(rule["verbs"]) <= {"get", "list", "watch"} for rule in role["rules"]),
            "resolver gained Ingress, HTTPRoute, node or DNS record permissions")


def main():
    args = set(sys.argv[1:])
    require(args <= {"--declarations", "--initial-migration"},
            "usage: tailnet-dns-test.py [--declarations] [--initial-migration]")
    values = load_yaml(VALUES)
    routes = load_yaml(ROUTES)
    inventory = json.loads(INVENTORY.read_text())
    label_sources = {path for path in (ROOT / "clusters/homelab").rglob("*")
                     if path.suffix in {".yaml", ".yml"}
                     and "homelab.rst.io/private-dns:" in path.read_text()}
    require(label_sources == {VALUES}, "another cluster source declares the private DNS selector")
    approved_names(values, routes, inventory, initial="--initial-migration" in args)
    mutation_checks(values, routes, inventory)
    if "--declarations" not in args:
        rendered_contract()
    print("Private DNS publication and resolver contract passed")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Private DNS contract failed: {error}") from error
