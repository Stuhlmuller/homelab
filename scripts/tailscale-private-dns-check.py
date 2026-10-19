#!/usr/bin/env python3
"""Validate the fixed DNS migration inventory and gate public retirement."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import hashlib
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
MIGRATION_NAMES_SHA256 = "4c4ce2ef575a18a2e18e6cc782a12228fc92fb4f3908c1ccc6a80da52f730b59"
OCE_NAMES = ["console.oce.stinkyboi.com", "*.agents.oce.stinkyboi.com"]
CRITICAL_PATHS = {"fleet_setup_denied", "harbor_node_pulls", "native_api", "cordium_reconnect", "public_callbacks"}
APEX = "stinkyboi.com"
ADDRESS_TYPES = {"A", "AAAA", "CNAME"}


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
            if not isinstance(host, str) or not (re.fullmatch(
                    r"(?:[a-z0-9-]+\.)?stinkyboi\.com|\*\.cordium\.stinkyboi\.com", host)
                    or host in OCE_NAMES):
                raise RuntimeError("DNS inventory includes a hostname outside the reviewed scope")
    names = value["hostnames"] + value["retired_hostnames"]
    if len(names) != len(set(names)):
        raise RuntimeError("DNS inventory includes duplicate or conflicting names")
    migration = value["hostnames"][:27]
    digest = hashlib.sha256("\n".join(sorted(migration)).encode()).hexdigest()
    if digest != MIGRATION_NAMES_SHA256 or value["hostnames"][27:] != OCE_NAMES:
        raise RuntimeError("The public retirement inventory must retain the fixed 27-name migration set and reviewed OCE names")
    return value


def retirement_names(value):
    names = value["hostnames"][:27]
    if len(names) != 27 or names.count(APEX) != 1 or len(set(names)) != 27:
        raise RuntimeError("Public retirement requires the fixed 27-name private inventory")
    retired = [name for name in names if name != APEX]
    if len(retired) != 26 or set(retired) & set(value["retired_hostnames"]):
        raise RuntimeError("Public retirement requires exactly 26 approved non-apex names")
    return retired


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


def deployment_suspended(namespace, name):
    live = json.loads(run("kubectl", "-n", namespace, "get", "deployment", name, "-o", "json"))
    return (live.get("metadata", {}).get("name") == name
            and live.get("metadata", {}).get("namespace") == namespace
            and type(live.get("spec", {}).get("replicas")) is int and live["spec"]["replicas"] == 0
            and live.get("status", {}).get("replicas", 0) == 0)


def affine_suspended():
    source = json.loads(run("yq", "-o=json", ".", str(ROOT / "clusters/homelab/apps/affine/deployment.yaml")))
    if (source.get("kind") != "Deployment" or source.get("metadata", {}).get("name") != "affine"
            or type(source.get("spec", {}).get("replicas")) is not int or source["spec"]["replicas"] != 0):
        return False
    return deployment_suspended("affine", "affine")


def openclaw_suspended():
    source = json.loads(run("yq", "-o=json", ".", str(ROOT / "clusters/homelab/apps/openclaw/values.yaml")))
    controllers = source.get("controllers") if isinstance(source, dict) else None
    controller = controllers.get("openclaw") if isinstance(controllers, dict) else None
    if not isinstance(controller, dict) or type(controller.get("replicas")) is not int or controller["replicas"] != 0:
        return False
    return deployment_suspended("ai", "openclaw")


def routes(value, address=None):
    for hostname in value["hostnames"]:
        if hostname == "octelium-api.stinkyboi.com":
            for protocol in ("application/grpc", "application/grpc-web+proto"):
                probe(hostname, address, "/octelium.api.main.user.v1.MainService/GetStatus", protocol)
        else:
            wildcard = hostname.startswith("*.")
            child = "agent-" + "0" * 32 if hostname == OCE_NAMES[1] else "dns-preflight"
            test_host = hostname.replace("*.", child + ".", 1) if wildcard else hostname
            path = "/v2/" if hostname == "harbor.stinkyboi.com" else "/"
            status, headers = probe(test_host, address, path)
            accepted = 200 <= status < 400 or status in (401, 403) or (wildcard and hostname != OCE_NAMES[1] and status == 404)
            if hostname == "affine.stinkyboi.com" and status in (500, 502, 503):
                accepted = affine_suspended()
            elif hostname == "openclaw.stinkyboi.com" and status == 502:
                accepted = openclaw_suspended()
            if not accepted:
                raise RuntimeError(f"Traefik TLS/upstream readiness failed for {hostname}: HTTP {status}")
            if hostname == "harbor.stinkyboi.com" and (status != 401 or not any(
                    line.startswith('www-authenticate: bearer realm="https://harbor.stinkyboi.com/service/token"')
                    for line in headers)):
                raise RuntimeError("Harbor registry authentication realm must retain its canonical HTTPS hostname")
        print(f"Verified mesh TLS route: {hostname}", file=sys.stderr)


def authoritative_servers():
    output = run("dig", "+noall", "+comments", "+authority", "+time=3", "+tries=1",
                 "+norecurse", "@a.gtld-servers.net", APEX, "NS")
    authority_count = re.search(r"\bAUTHORITY:\s*(\d+)", output)
    flags = re.search(r";; flags:\s*([^;]+);", output)
    if (not re.search(r"status:\s*NOERROR\b", output) or not authority_count or not flags
            or "qr" not in flags.group(1).split() or "tc" in flags.group(1).split()):
        raise RuntimeError("Public parent delegation could not be inspected")
    names = []
    authority = False
    for line in output.splitlines():
        if line.startswith(";; AUTHORITY SECTION:"):
            authority = True
        elif line.startswith(";;") or not line.strip():
            continue
        elif authority:
            fields = line.split()
            if (len(fields) != 5 or fields[0].rstrip(".").lower() != APEX or not fields[1].isdigit()
                    or fields[2] != "IN" or fields[3] != "NS"):
                raise RuntimeError("Unexpected public parent delegation response")
            names.append(fields[4].lower())
    if len(names) < 2 or len(names) != int(authority_count.group(1)) or len(names) != len(set(names)) or any(
            not re.fullmatch(r"[a-z0-9-]+\.ns\.cloudflare\.com\.", name) for name in names):
        raise RuntimeError("Expected complete Cloudflare parent delegation")
    return sorted(names)


def verify_zone_nameservers(api_names):
    if (not isinstance(api_names, list) or len(api_names) < 2
            or any(not isinstance(name, str) or not re.fullmatch(
                r"[a-z0-9-]+\.ns\.cloudflare\.com\.?", name.lower()) for name in api_names)):
        raise RuntimeError("Cloudflare zone nameservers are incomplete")
    normalized = [name.lower().rstrip(".") + "." for name in api_names]
    if len(normalized) != len(set(normalized)) or set(normalized) != set(authoritative_servers()):
        raise RuntimeError("Selected Cloudflare zone nameservers differ from public parent delegation")


def answers(server, host, kind):
    return [(record[1], record[2], record[3]) for record in public_answers(server, host, kind)]


def previous_ttl(value):
    # API ttl=1 means automatic; measure served TTLs instead of assuming its duration.
    ttl = 0
    for server in authoritative_servers():
        for hostname in retirement_names(value):
            for kind in ("A", "AAAA", "CNAME"):
                ttl = max([ttl] + [record[2] for record in answers(server, hostname, kind)])
    return ttl


def public_answers(server, hostname, kind):
    output = run("dig", "+noall", "+comments", "+answer", "+authority", "+time=3", "+tries=1",
                 "+norecurse", "@" + server, hostname, kind)
    header = re.search(r"status:\s*(\w+)", output)
    flags = re.search(r";; flags:\s*([^;]+);", output)
    answer_count = re.search(r"\bANSWER:\s*(\d+)", output)
    if (not header or header.group(1) not in ("NOERROR", "NXDOMAIN") or not flags
            or "aa" not in flags.group(1).split() or "tc" in flags.group(1).split() or not answer_count):
        raise RuntimeError(f"Incomplete authoritative DNS inspection for {hostname}")
    section = ""
    answer = []
    for line in output.splitlines():
        if line.startswith(";; ANSWER SECTION:"):
            section = "answer"
        elif line.startswith(";; AUTHORITY SECTION:"):
            section = "authority"
        elif line.startswith(";;") or not line.strip():
            continue
        elif section == "answer":
            fields = line.split()
            if len(fields) < 5 or fields[2] != "IN" or not fields[1].isdigit():
                raise RuntimeError(f"Unexpected authoritative answer for {hostname}")
            answer.append((fields[0].rstrip(".").lower(), fields[3], fields[4], int(fields[1])))
    if answer and answer[0][0] != hostname:
        raise RuntimeError(f"Unexpected authoritative answer owner for {hostname}")
    if len(answer) != int(answer_count.group(1)):
        raise RuntimeError(f"Incomplete authoritative answer for {hostname}")
    return answer


def inspect_public_zone(value, zone_records, current):
    names = retirement_names(value)
    targets = set(names)
    wildcard_child = "dns-preflight.cordium.stinkyboi.com"
    inspected = names + [wildcard_child]
    if not isinstance(zone_records, list) or not isinstance(current, list):
        raise RuntimeError("Complete public-zone and selected-record snapshots are required")
    seen_ids = set()
    selected = set()
    for record in zone_records:
        if (not isinstance(record, dict) or set(record) != {"id", "name", "type"}
                or not isinstance(record["id"], str) or not record["id"] or record["id"] in seen_ids
                or not isinstance(record["name"], str) or not record["name"]
                or not isinstance(record["type"], str) or record["type"] not in ADDRESS_TYPES | {"NS"}):
            raise RuntimeError("Incomplete or duplicate public-zone record metadata")
        seen_ids.add(record["id"])
        owner = record["name"]
        kind = record["type"]
        if owner in targets and kind in ADDRESS_TYPES:
            selected.add((record["id"], owner, kind))
        if owner not in targets and owner.endswith(".cordium.stinkyboi.com"):
            raise RuntimeError(f"Out-of-scope public Cordium child blocks retirement: {owner}")
        if (kind == "NS" and owner != APEX
                and any(host == owner or host.endswith("." + owner)
                        or (owner.startswith("*.") and host.endswith(owner[1:]))
                        for host in inspected)):
            raise RuntimeError(f"Public child-zone delegation blocks retirement: {owner}")
        if (kind in ADDRESS_TYPES and owner.startswith("*.") and owner not in targets
                and any(host.endswith(owner[1:]) for host in inspected)):
            raise RuntimeError(f"Out-of-scope public wildcard blocks retirement: {owner}")
    selected_current = set()
    for record in current:
        if (not isinstance(record, dict) or record.get("name") not in targets
                or not isinstance(record.get("type"), str) or record["type"] not in ADDRESS_TYPES
                or not isinstance(record.get("id"), str)):
            raise RuntimeError("Selected public record snapshot is invalid")
        selected_current.add((record["id"], record["name"], record["type"]))
    if selected != selected_current or len(selected_current) != len(current):
        raise RuntimeError("Public-zone inventory differs from selected exact-owner records")
    by_name = {name: set() for name in names}
    for record in current:
        by_name[record["name"]].add(record["type"])
    for server in authoritative_servers():
        for host in inspected:
            source = "*.cordium.stinkyboi.com" if host == wildcard_child else host
            for kind in ADDRESS_TYPES:
                response = public_answers(server, host, kind)
                if response and not by_name[source]:
                    raise RuntimeError(f"Unexpected effective public answer source for {host}")
    return len(names)


def validate_retirement_evidence(evidence, value, expected_sha):
    if not isinstance(evidence, dict) or set(evidence) != {
            "reviewed_main_sha", "resolver_ip", "owner_tailnet_dns_confirmed", "normal_client_dns_confirmed",
            "critical_paths_confirmed", "off_tailnet", "previous_ttl_seconds", "checked_names", "baseline_records"}:
        raise RuntimeError("Retirement evidence must contain the complete reviewed cutover fields")
    if evidence["reviewed_main_sha"] != expected_sha or not re.fullmatch(r"[0-9a-f]{40}", expected_sha or ""):
        raise RuntimeError("Retirement evidence must match the reviewed main SHA")
    try:
        resolver = ipaddress.ip_address(evidence["resolver_ip"])
    except (ValueError, TypeError):
        raise RuntimeError("Retirement evidence requires a valid resolver IPv4") from None
    if resolver.version != 4 or resolver not in MESH[0]:
        raise RuntimeError("Retirement evidence resolver must be a tailnet IPv4")
    if evidence["owner_tailnet_dns_confirmed"] is not True or evidence["normal_client_dns_confirmed"] is not True:
        raise RuntimeError("Owner tailnet DNS and normal-client acceptance must be recorded")
    critical = evidence["critical_paths_confirmed"]
    if not isinstance(critical, dict) or set(critical) != CRITICAL_PATHS or any(value is not True for value in critical.values()):
        raise RuntimeError("All critical client and callback checks must be recorded")
    off_tailnet = evidence["off_tailnet"]
    if not isinstance(off_tailnet, dict) or set(off_tailnet) != set(retirement_names(value)) or any(
            decision not in ("migrated", "accepted_loss") for decision in off_tailnet.values()):
        raise RuntimeError("Every retired app subdomain needs an off-tailnet caller decision")
    ttl = evidence["previous_ttl_seconds"]
    if type(ttl) is not int or ttl < 0:
        raise RuntimeError("Retirement evidence needs the old maximum public TTL")
    if evidence["checked_names"] != retirement_names(value):
        raise RuntimeError("Public baseline must confirm the ordered 26 non-apex names were queried")
    records = evidence["baseline_records"]
    if not isinstance(records, list) or (records and ttl == 0):
        raise RuntimeError("Public baseline records require a measured old TTL")
    ids = set()
    for record in records:
        if (not isinstance(record, dict) or set(record) != {"id", "name", "type", "content", "proxied", "ttl"}
                or not isinstance(record["id"], str) or not record["id"] or record["id"] in ids
                or record["name"] not in retirement_names(value)
                or not isinstance(record["type"], str) or record["type"] not in ADDRESS_TYPES
                or not isinstance(record["content"], str) or not record["content"]
                or type(record["proxied"]) is not bool or type(record["ttl"]) is not int or record["ttl"] < 1):
            raise RuntimeError("Public baseline contains an invalid, duplicate or out-of-scope record")
        ids.add(record["id"])
    return str(resolver)


def verify_private_dns(value, addresses, resolver_ip):
    run("python3", "-I", str(ROOT / "scripts/tailnet-dns-check.py"), "--server", resolver_ip)
    expected = set(addresses["A"] + addresses["AAAA"])
    for hostname in value["hostnames"]:
        test_host = hostname.replace("*.", "dns-preflight.", 1)
        resolved = {item[4][0] for item in socket.getaddrinfo(test_host, 443, type=socket.SOCK_STREAM)}
        if resolved != expected:
            raise RuntimeError(f"Normal client DNS for {hostname} does not match the private Traefik Service")
    routes({"hostnames": value["hostnames"][:27]})
    print("Direct resolver, normal client DNS, and migration HTTPS routes verified", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retire-private", action="store_true", help="Prepare fixed 26-name public app retirement")
    parser.add_argument("--execute", action="store_true", help="Gate retirement on reviewed main and cutover evidence")
    parser.add_argument("--check", action="store_true", help="Read-only live route readiness check")
    parser.add_argument("--baseline-ttl", action="store_true", help="Measure the old maximum authoritative TTL")
    parser.add_argument("--zone-name-servers", help="Cloudflare zone nameservers to compare with parent delegation")
    parser.add_argument("--inspect-zone", type=Path, help="Inspect complete public-zone record metadata before deletion")
    parser.add_argument("--current", type=Path, help="Selected exact-owner records for public-zone inspection")
    parser.add_argument("--expected-sha")
    parser.add_argument("--evidence", type=Path, help="Private cutover evidence JSON outside this repository")
    args = parser.parse_args()
    value = inventory()
    if args.zone_name_servers is not None:
        if not args.retire_private or args.execute:
            parser.error("--zone-name-servers requires read-only --retire-private")
        verify_zone_nameservers(json.loads(args.zone_name_servers))
        return
    if args.inspect_zone or args.current:
        if not args.retire_private or args.execute or not args.inspect_zone or not args.current:
            parser.error("--inspect-zone requires --retire-private and --current without --execute")
        inspect_public_zone(value, json.loads(args.inspect_zone.read_text()), json.loads(args.current.read_text()))
        return
    if args.baseline_ttl:
        if not args.retire_private or args.execute:
            parser.error("--baseline-ttl requires a read-only --retire-private call")
        print(previous_ttl(value))
        return
    if args.execute:
        if not args.retire_private or not args.expected_sha or not args.evidence:
            parser.error("--execute requires --retire-private, --expected-sha and --evidence")
        verify_main(args.expected_sha)
        if args.evidence.resolve().is_relative_to(ROOT):
            raise RuntimeError("Keep retirement evidence outside the public repository")
        evidence = json.loads(args.evidence.read_text())
        resolver_ip = validate_retirement_evidence(evidence, value, args.expected_sha)
        if previous_ttl(value) > evidence["previous_ttl_seconds"]:
            raise RuntimeError("Current public TTL exceeds the saved baseline; capture and review a new baseline")
    elif args.evidence or args.expected_sha:
        parser.error("--evidence and --expected-sha require --execute")
    if args.retire_private and not (args.execute or args.check):
        print(f"Fixed 26-name public retirement inventory verified; {len(value['hostnames'])} private names retained")
        return
    addresses = mesh_addresses()
    if args.execute or args.check:
        declared_routes()
    if args.execute or args.check:
        route_value = {"hostnames": value["hostnames"][:27]} if args.retire_private else value
        for address in addresses["A"] + addresses["AAAA"]:
            routes(route_value, address)
    if args.execute:
        verify_private_dns(value, addresses, resolver_ip)
    elif not args.check:
        print("Verified controller-owned mesh addresses: " + json.dumps(addresses))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
