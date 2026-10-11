#!/usr/bin/env python3
"""Validate the fixed DNS inventory and gate execution on reviewed mesh ingress."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import runpy
import socket
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "scripts/config/tailscale-private-dns.json"
TARGET = "homelab-ingress.tail67beb.ts.net"
MESH = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))


def run(*command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"Preflight command failed: {command[0]}; private output withheld")
    return result.stdout


def inventory():
    value = json.loads(INVENTORY.read_text())
    if set(value) != {"ingress_hostname", "hostnames", "retired_hostnames"} or value["ingress_hostname"] != TARGET:
        raise RuntimeError("Unexpected private DNS target or inventory fields")
    for key in ("hostnames", "retired_hostnames"):
        if not isinstance(value[key], list) or not value[key]:
            raise RuntimeError("DNS inventory requires explicit nonempty hostname lists")
        for host in value[key]:
            if not isinstance(host, str) or not re.fullmatch(r"(?:[a-z0-9-]+\.)?stinkyboi\.com|\*\.cordium\.stinkyboi\.com", host):
                raise RuntimeError("DNS inventory includes a hostname outside the reviewed scope")
    names = value["hostnames"] + value["retired_hostnames"]
    if len(names) != len(set(names)):
        raise RuntimeError("DNS inventory includes duplicate or conflicting names")
    return value


def verify_main(expected):
    spec = importlib.util.spec_from_file_location("native", ROOT / "scripts/octelium-nofx-reconcile.py")
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    native.verify_reviewed_main(expected)
    for path in ("scripts/tailscale-private-dns.sh", "scripts/tailscale-private-dns-check.py",
                 "scripts/config/tailscale-private-dns.json"):
        native.run("git", "-C", str(ROOT), "cat-file", "-e", f"HEAD:{path}")


def mesh_address(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in MESH)


def probe(host, address=None, path="/", protocol=None):
    command = ["curl", "--disable", "--silent", "--show-error", "--noproxy", "*", "--proto", "=https",
               "--connect-timeout", "10", "--max-time", "20",
               "--dump-header", "-", "--output", "/dev/null", "--write-out", "\n%{http_code}"]
    if address:
        endpoint = f"[{address}]" if ":" in address else address
        command += ["--connect-to", f"{host}:443:{endpoint}:443"]
    if protocol:
        command += ["--http2", "--header", f"content-type: {protocol}", "--header", "TE: trailers",  # codespell:ignore te
                    "--header", "x-grpc-web: 1", "--data-binary", ""]
    command += [f"https://{host}{path}"]
    with tempfile.TemporaryDirectory(prefix="homelab-api-probe-") as temporary:
        body = Path(temporary) / "body"
        command[command.index("--output") + 1] = str(body)
        headers, status = run(*command).rsplit("\n", 1)
        if protocol:
            validate = runpy.run_path(str(ROOT / "scripts/octelium-api-response.py"))["unauthenticated"]
            if int(status) != 200 or not validate(headers.encode(), body.read_bytes(), native=protocol == "application/grpc"):
                raise RuntimeError("Octelium API native and browser HTTP/2 authentication probes must pass")
    return int(status), [line.strip().lower() for line in headers.splitlines()]


def mesh_addresses():
    service = json.loads(run("kubectl", "-n", "traefik", "get", "service", "traefik-private", "-o", "json"))
    spec = service.get("spec", {})
    annotations = service.get("metadata", {}).get("annotations", {})
    ingress = service.get("status", {}).get("loadBalancer", {}).get("ingress", [])
    if (spec.get("type") != "LoadBalancer" or spec.get("loadBalancerClass") != "tailscale"
            or annotations.get("tailscale.com/hostname") != "homelab-ingress"
            or {item.get("hostname", "").rstrip(".") for item in ingress} - {"", TARGET}
            or not any(item.get("hostname", "").rstrip(".") == TARGET for item in ingress)
            or not any(port.get("port") == 443 and port.get("targetPort") == 8443 for port in spec.get("ports", []))):
        raise RuntimeError("Traefik Service must publish the declared Tailscale hostname and HTTPS port")
    published = {item["ip"] for item in ingress if item.get("ip")}
    if not published or not all(mesh_address(address) for address in published):
        raise RuntimeError("Tailscale Service must publish only nonempty mesh addresses")
    binary = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    status = json.loads(run(binary if Path(binary).is_file() else "tailscale", "status", "--json"))
    if (status.get("BackendState") != "Running" or not status.get("Self", {}).get("Online")
            or status.get("CurrentTailnet", {}).get("MagicDNSSuffix") != "tail67beb.ts.net"):
        raise RuntimeError("The current operator Tailscale profile must be online in the declared tailnet")
    peers = [peer for peer in status.get("Peer", {}).values()
             if peer.get("DNSName", "").rstrip(".") == TARGET and peer.get("Online")]
    if len(peers) != 1 or not published <= set(peers[0].get("TailscaleIPs", [])):
        raise RuntimeError("Service addresses must belong to the unique online homelab-ingress Tailscale peer")
    addresses = {"A": [], "AAAA": []}
    for address in sorted(published):
        addresses["AAAA" if ":" in address else "A"].append(str(ipaddress.ip_address(address)))
    if any(len(items) > 1 for items in addresses.values()):
        raise RuntimeError("The single ingress peer must publish at most one address per family")
    return addresses


def declared_routes():
    config = json.loads(run("kubectl", "-n", "traefik", "get", "configmap", "traefik-routes", "-o", "json"))
    for name in ("routes.yaml", "tls.yaml"):
        if config.get("data", {}).get(name) != (ROOT / "clusters/homelab/apps/traefik" / name).read_text():
            raise RuntimeError("Deployed Traefik routes/TLS config differ from the reviewed checkout")


def affine_suspended():
    source = json.loads(run("yq", "-o=json", ".", str(ROOT / "clusters/homelab/apps/affine/deployment.yaml")))
    if (source.get("kind") != "Deployment" or source.get("metadata", {}).get("name") != "affine"
            or type(source.get("spec", {}).get("replicas")) is not int or source["spec"]["replicas"] != 0):
        return False
    live = json.loads(run("kubectl", "-n", "affine", "get", "deployment", "affine", "-o", "json"))
    return (live.get("metadata", {}).get("name") == "affine"
            and live.get("metadata", {}).get("namespace") == "affine"
            and type(live.get("spec", {}).get("replicas")) is int and live["spec"]["replicas"] == 0
            and live.get("status", {}).get("replicas", 0) == 0)


def routes(value, address=None):
    for hostname in value["hostnames"]:
        if hostname == "octelium-api.stinkyboi.com":
            for protocol in ("application/grpc", "application/grpc-web+proto"):
                probe(hostname, address, "/octelium.api.main.user.v1.MainService/GetStatus", protocol)
        else:
            wildcard = hostname.startswith("*.")
            test_host = hostname.replace("*.", "dns-preflight.", 1) if wildcard else hostname
            path = "/v2/" if hostname == "harbor.stinkyboi.com" else "/"
            status, headers = probe(test_host, address, path)
            accepted = 200 <= status < 400 or status in (401, 403) or (wildcard and status == 404)
            if hostname == "affine.stinkyboi.com" and status in (502, 503):
                accepted = affine_suspended()
            if not accepted:
                raise RuntimeError(f"Traefik TLS/upstream readiness failed for {hostname}: HTTP {status}")
            if hostname == "harbor.stinkyboi.com" and (status != 401 or not any(
                    line.startswith('www-authenticate: bearer realm="https://harbor.stinkyboi.com/service/token"')
                    for line in headers)):
                raise RuntimeError("Harbor registry authentication realm must retain its canonical HTTPS hostname")
        print(f"Verified mesh TLS route: {hostname}", file=sys.stderr)


def authoritative_servers():
    names = run("dig", "+short", "+time=3", "+tries=1", "NS", "stinkyboi.com").split()
    if not names or any(not name.endswith(".ns.cloudflare.com.") for name in names):
        raise RuntimeError("Expected the declared Cloudflare authoritative nameservers")
    return names


def answers(server, host, kind):
    output = run("dig", "+noall", "+answer", "+time=3", "+tries=1", "+norecurse", "@" + server, host, kind)
    result = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[2] != "IN" or not fields[1].isdigit():
            raise RuntimeError("Unexpected authoritative DNS response")
        result.append((fields[3], fields[4], int(fields[1])))
    return result


def previous_ttl(value):
    # API ttl=1 means automatic; measure served TTLs instead of assuming its duration.
    ttl = 0
    for server in authoritative_servers():
        for hostname in value["hostnames"] + value["retired_hostnames"]:
            for kind in ("A", "AAAA", "CNAME"):
                ttl = max([ttl] + [record[2] for record in answers(server, hostname, kind)])
    return ttl


def verify_dns(value, addresses):
    servers = authoritative_servers()
    expected = set(addresses["A"] + addresses["AAAA"])
    for hostname in value["hostnames"]:
        test_host = hostname.replace("*.", "dns-preflight.", 1)
        for server in servers:
            for kind in ("A", "AAAA"):
                records = answers(server, test_host, kind)
                if any(record[0] != kind for record in records) or {record[1] for record in records} != set(addresses[kind]):
                    raise RuntimeError(f"Authoritative {kind} answers do not match the ingress Service for {hostname}")
        resolved = {item[4][0] for item in socket.getaddrinfo(test_host, 443, type=socket.SOCK_STREAM)}
        if resolved != expected:
            raise RuntimeError(f"Client DNS for {hostname} has not converged; keep the tunnel and retry --verify-dns")
    # These requests intentionally use normal DNS and canonical SNI, with no connect-to override.
    routes(value)
    print("Authoritative DNS, client resolution, and canonical HTTPS routes verified", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Require reviewed main and live readiness before DNS writes")
    parser.add_argument("--check", action="store_true", help="Read-only live route readiness check")
    parser.add_argument("--verify-dns", action="store_true", help="Verify authoritative and normal client DNS/TLS after cutover")
    parser.add_argument("--addresses-json", action="store_true", help="Return verified controller addresses and observed previous TTL for the DNS operator")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    value = inventory()
    if args.execute:
        verify_main(args.expected_sha)
    addresses = mesh_addresses()
    if args.execute or args.check or args.verify_dns:
        declared_routes()
    if args.execute or args.check:
        for address in addresses["A"] + addresses["AAAA"]:
            routes(value, address)
    if args.verify_dns:
        verify_dns(value, addresses)
    if args.addresses_json:
        print(json.dumps({"addresses": addresses, "previous_ttl": previous_ttl(value)}))
    elif not (args.execute or args.check or args.verify_dns):
        print("Verified controller-owned mesh addresses: " + json.dumps(addresses))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
