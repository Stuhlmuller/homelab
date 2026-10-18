#!/usr/bin/env python3
"""Read-only proof of the signed tailnet resolver and its private DNS answers."""
import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scripts/config/tailscale-private-dns.json"
SIGNER_SPEC = importlib.util.spec_from_file_location("signer", ROOT / "scripts/tailscale-ingress-sign.py")
SIGNER = importlib.util.module_from_spec(SIGNER_SPEC)
SIGNER_SPEC.loader.exec_module(SIGNER)
MESH = ipaddress.ip_network("100.64.0.0/10")


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(f"Read-only check failed: {args[0]}")
    return result.stdout


def service(namespace, name):
    return json.loads(run("kubectl", "-n", namespace, "get", "service", name, "-o", "json"))


def selected_services():
    items = json.loads(run("kubectl", "get", "services", "--all-namespaces", "-l",
                           "homelab.rst.io/private-dns=approved", "-o", "json"))["items"]
    return {(item["metadata"]["namespace"], item["metadata"]["name"]) for item in items}


def published_ip(value):
    addresses = {entry["ip"] for entry in value.get("status", {}).get("loadBalancer", {}).get("ingress", [])
                 if entry.get("ip")}
    if len(addresses) != 1:
        raise RuntimeError("Service must publish exactly one tailnet IPv4")
    address = addresses.pop()
    if ipaddress.ip_address(address) not in MESH:
        raise RuntimeError("Service address must be one Tailscale IPv4")
    return address


def declared_names(value, initial):
    if value.get("metadata", {}).get("labels", {}).get("homelab.rst.io/private-dns") != "approved":
        raise RuntimeError("Traefik Service lacks private DNS approval")
    raw = value.get("metadata", {}).get("annotations", {}).get("coredns.io/hostname", "")
    names = [item.strip() for item in raw.split(",")]
    if not names or len(names) != len(set(names)) or any(
        not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*stinkyboi\.com|\*\.cordium\.stinkyboi\.com", item)
        for item in names
    ):
        raise RuntimeError("Approved hostname annotation is missing, duplicate, or outside the zone")
    if initial and set(names) != set(json.loads(INVENTORY.read_text())["hostnames"]):
        raise RuntimeError("Initial handoff requires the reviewed 27-name migration set")
    return names


def dns_answer(server, hostname, kind, tcp=False):
    args = ["dig", "@" + server, hostname, kind, "+noall", "+comments", "+answer", "+time=3", "+tries=1"]
    if tcp:
        args.append("+tcp")
    output = run(*args)
    header = re.search(r";; ->>HEADER<<-.*status: ([A-Z]+),", output)
    flags = re.search(r";; flags: ([a-z ]+);", output)
    if not header or not flags:
        raise RuntimeError(f"Malformed DNS response for {hostname} {kind}")
    records = set()
    for line in output.splitlines():
        if not line or line.startswith(";"):
            continue
        fields = line.split(None, 4)
        if len(fields) != 5 or not fields[1].isdigit() or fields[2] != "IN":
            raise RuntimeError(f"Malformed DNS answer for {hostname} {kind}")
        records.add((fields[3], fields[4]))
    return header.group(1), set(flags.group(1).split()), records


def verify(server, initial=False):
    if selected_services() != {("traefik", "traefik-private")}:
        raise RuntimeError("Only traefik/traefik-private may publish approved DNS names")
    dns = service("tailnet-dns", "tailnet-dns")
    spec = dns.get("spec", {})
    annotations = dns.get("metadata", {}).get("annotations", {})
    if (spec.get("type") != "LoadBalancer" or spec.get("loadBalancerClass") != "tailscale"
            or annotations.get("tailscale.com/hostname") != "homelab-dns"
            or annotations.get("tailscale.com/tags") != "tag:homelab-ingress"
            or {(port.get("port"), port.get("protocol")) for port in spec.get("ports", [])}
            != {(53, "TCP"), (53, "UDP")}):
        raise RuntimeError("DNS Service must expose only its declared tailnet DNS ports")
    if server != published_ip(dns):
        raise RuntimeError("Supplied resolver IP differs from the live DNS Service")
    peer = SIGNER.inspect_target(SIGNER.TARGETS[3], SIGNER.local_signer())
    if not peer["signed"] or peer["dns"] != "homelab-dns." + SIGNER.TAILNET:
        raise RuntimeError("DNS proxy must be online and signed under Tailnet Lock")

    traefik = service("traefik", "traefik-private")
    target = published_ip(traefik)
    names = declared_names(traefik, initial)
    for name in names:
        query = name.replace("*.", "dns-preflight.", 1)
        for tcp in (False, True):
            status, flags, records = dns_answer(server, query, "A", tcp)
            if status != "NOERROR" or "aa" not in flags or "ra" in flags or records != {("A", target)}:
                raise RuntimeError(f"Private A answer differs from Traefik or fell through: {query}")
            status, flags, records = dns_answer(server, query, "AAAA", tcp)
            if status != "NOERROR" or "aa" not in flags or "ra" in flags or records:
                raise RuntimeError(f"Private AAAA must be authoritative NODATA: {query}")
    for name, kind in (("stinkyboi.com", "MX"), ("stinkyboi.com", "TXT"),
                       ("mastodon.stinkyboi.com", "A")):
        public_status, _, public_records = dns_answer("1.1.1.1", name, kind)
        if kind != "A" and (public_status != "NOERROR" or not public_records):
            raise RuntimeError(f"Public {kind} baseline is unavailable: {name}")
        for tcp in (False, True):
            status, flags, records = dns_answer(server, name, kind, tcp)
            # CoreDNS cache sets AA on hits but preserves RA from recursive forwards.
            if status != public_status or records != public_records or "ra" not in flags:
                raise RuntimeError(f"Public fallthrough differs from baseline: {name} {kind}")
    print(f"Verified signed DNS proxy {peer['dns']} at {server}; {len(names)} approved names over UDP/TCP")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, help="Observed tailnet IPv4 of the DNS Service")
    parser.add_argument("--initial-handoff", action="store_true", help="Require the fixed 27-name migration set")
    args = parser.parse_args(argv)
    try:
        verify(args.server, args.initial_handoff)
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError,
            SIGNER.GUARDS.Failure) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
