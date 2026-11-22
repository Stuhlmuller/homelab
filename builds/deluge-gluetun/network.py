"""Install Deluge's fail-closed WireGuard transit and fence its VPN gateway."""

import argparse
import base64
import configparser
import hashlib
import hmac
import ipaddress
import json
import os
import subprocess
import sys
import time
from pathlib import Path


PROFILE = Path("/vpn-source/wg0.conf")
POD_CIDR = "10.244.0.0/16"
API_IP = "10.96.0.1"
SERVICE_IP = "10.96.10.61"
CLIENT_IP = "172.31.61.2"
TRANSIT_SUBNET = "172.31.61.0/30"
GATEWAY_IP = "172.31.61.1"
TRANSIT_PORT = 51820
TRANSIT_MARK = 201
AIRVPN_MARK = 51820
AIRVPN_PORT = 1637
PEER_PORT = 5983
MTU = 1320  # Match the pinned Gluetun WireGuard default.
TABLE = "deluge_gluetun"
MAX_FENCE_NS = 7_000_000_000


def run(*args, input=None, capture=False, missing_ok=False, pass_fds=()):
    return subprocess.run(
        args, input=input, text=True, check=not missing_ok, pass_fds=pass_fds,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.DEVNULL if missing_ok else None,
    ).stdout


def nft(rules):
    subprocess.run(("nft", "-f", "-"), input=rules, text=True, check=True,
                   env={**os.environ, "TZ": "UTC"})


def validate_namespace(*, forwarding):
    sysctl = Path("/proc/sys/net/ipv4")
    expected = {
        "conf/all/rp_filter": "0",
        "conf/default/rp_filter": "0",
        "conf/eth0/rp_filter": "0",
    }
    if forwarding:
        expected["ip_forward"] = "1"
    for name, value in expected.items():
        if (sysctl / name).read_text().strip() != value:
            raise RuntimeError(f"Required IPv4 setting {name} must be {value}")


def profile():
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with PROFILE.open() as stream:
            parser.read_file(stream)
        interface = parser["Interface"]
        secret = base64.b64decode(interface["PrivateKey"].strip(), validate=True)
        addresses = [ipaddress.ip_interface(value.strip()) for value in interface["Address"].split(",")]
        ipv4 = next(address.ip for address in addresses if address.version == 4)
        if len(secret) != 32 or not any(secret):
            raise ValueError
        return secret, ipv4
    except (configparser.Error, KeyError, OSError, StopIteration, ValueError):
        raise RuntimeError("AirVPN profile requires a valid WireGuard private key and IPv4 address") from None


def transit_key(secret, role):
    # RFC 5869 HKDF-SHA256 with separate info for each transit role. The AirVPN
    # key itself never becomes a transit key or crosses a process boundary.
    prk = hmac.digest(b"homelab/deluge/gluetun-transit/v1", secret, hashlib.sha256)
    expanded = hmac.digest(prk, role.encode() + b"\x01", hashlib.sha256)
    return base64.b64encode(expanded).decode() + "\n"


def setup_transit(secret, *, gateway):
    local_role, peer_role = ("gateway", "client") if gateway else ("client", "gateway")
    local = GATEWAY_IP if gateway else CLIENT_IP
    peer = run("wg", "pubkey", input=transit_key(secret, peer_role), capture=True).strip()
    run("ip", "link", "del", "dev", "transit", missing_ok=True)
    run("ip", "link", "add", "dev", "transit", "type", "wireguard")
    run("ip", "link", "set", "dev", "transit", "mtu", str(MTU), "addrgenmode", "none")
    run("ip", "-4", "addr", "add", f"{local}/30", "dev", "transit")
    with os.fdopen(os.memfd_create("deluge-transit-key"), "w+") as keyfile:
        keyfile.write(transit_key(secret, local_role))
        keyfile.flush()
        keyfile.seek(0)
        fd = keyfile.fileno()
        args = ["wg", "set", "transit", "fwmark", str(TRANSIT_MARK),
                "private-key", f"/proc/self/fd/{fd}"]
        if gateway:
            args.extend(("listen-port", str(TRANSIT_PORT), "peer", peer, "allowed-ips", f"{CLIENT_IP}/32"))
        else:
            args.extend(("peer", peer, "allowed-ips", "0.0.0.0/0", "endpoint", f"{SERVICE_IP}:{TRANSIT_PORT}",
                         "persistent-keepalive", "5"))
        run(*args, pass_fds=(fd,))
    run("ip", "link", "set", "dev", "transit", "up")


def eth_gateway(anchor):
    routes = json.loads(run("ip", "-j", "-4", "route", "show", "exact", anchor, "dev", "eth0", capture=True))
    if not routes:
        routes = json.loads(run("ip", "-j", "-4", "route", "show", "default", "dev", "eth0", capture=True))
    if len(routes) != 1 or "gateway" not in routes[0]:
        raise RuntimeError("Could not find the IPv4 CNI gateway")
    return str(ipaddress.IPv4Address(routes[0]["gateway"]))


def add_eth_routes(router, *prefixes):
    for prefix in prefixes:
        run("ip", "-4", "route", "replace", prefix, "via", router, "dev", "eth0")


def client_firewall():
    return f"""
destroy table inet {TABLE}
table inet {TABLE} {{
  chain input {{
    type filter hook input priority filter; policy drop;
    iifname "lo" accept
    ct state invalid drop
    iifname "eth0" ip saddr {SERVICE_IP} udp sport {TRANSIT_PORT} ct state established accept
    iifname "eth0" ip saddr {POD_CIDR} tcp dport {{ 8112, 9797, 9798 }} ct state {{ new, established }} accept
    iifname "transit" meta nfproto ipv4 ct state {{ established, related }} accept
    iifname "transit" ip daddr {CLIENT_IP} ct state new meta l4proto {{ tcp, udp }} th dport {PEER_PORT} accept
  }}
  chain output {{
    type filter hook output priority filter; policy drop;
    oifname "lo" accept
    oifname "eth0" meta mark {TRANSIT_MARK} ip daddr {SERVICE_IP} udp dport {TRANSIT_PORT} accept
    oifname "eth0" ip daddr {POD_CIDR} tcp sport {{ 8112, 9797, 9798 }} ct direction reply ct state established accept
    oifname "transit" ip saddr {CLIENT_IP} accept
  }}
  chain forward {{ type filter hook forward priority filter; policy drop; }}
}}
"""


def init_client():
    nft(client_firewall())
    validate_namespace(forwarding=False)
    secret, _ = profile()
    router = eth_gateway(f"{SERVICE_IP}/32")
    add_eth_routes(router, f"{SERVICE_IP}/32", POD_CIDR)
    setup_transit(secret, gateway=False)
    run("ip", "-4", "route", "replace", "unreachable", "default", "metric", "32767")
    run("ip", "-4", "route", "replace", "default", "dev", "transit", "src", CLIENT_IP, "metric", "10")
    run("ip", "-4", "route", "del", "default", "via", router, "dev", "eth0", missing_ok=True)


def gateway_firewall(address):
    mss = MTU - 40
    return f"""
destroy table inet {TABLE}
table inet {TABLE} {{
  set lease_live {{ type nf_proto; flags timeout; }}
  chain require_lease {{ drop; }}
  chain input {{
    type filter hook input priority filter; policy drop;
    iifname "lo" accept
    ct state invalid drop
    iifname "eth0" ip saddr {API_IP} tcp sport 443 ct state established accept
    iifname "eth0" ip saddr {POD_CIDR} udp dport {TRANSIT_PORT} jump require_lease
    iifname "eth0" udp sport {AIRVPN_PORT} ct state established jump require_lease
    iifname "tun0" meta nfproto ipv4 ct state {{ established, related }} jump require_lease
  }}
  chain output {{
    type filter hook output priority filter; policy drop;
    oifname "lo" accept
    oifname "eth0" ip daddr {API_IP} tcp dport 443 accept
    oifname "eth0" meta mark {TRANSIT_MARK} ip daddr {POD_CIDR} udp sport {TRANSIT_PORT} jump require_lease
    oifname "eth0" meta mark {AIRVPN_MARK} udp dport {AIRVPN_PORT} jump require_lease
    oifname "tun0" meta nfproto ipv4 jump require_lease
  }}
  chain forward {{
    type filter hook forward priority filter; policy drop;
    ct state invalid drop
    iifname "transit" oifname "tun0" meta nfproto ipv4 tcp flags & (syn | rst) == syn tcp option maxseg size > {mss} tcp option maxseg size set {mss}
    iifname "tun0" oifname "transit" meta nfproto ipv4 tcp flags & (syn | rst) == syn tcp option maxseg size > {mss} tcp option maxseg size set {mss}
    iifname "transit" oifname "tun0" ip saddr {CLIENT_IP} ct state {{ new, established, related }} jump require_lease
    iifname "tun0" oifname "transit" ip daddr {CLIENT_IP} ct state {{ established, related }} jump require_lease
    iifname "tun0" oifname "transit" ip daddr {CLIENT_IP} ct status dnat meta l4proto {{ tcp, udp }} th dport {PEER_PORT} jump require_lease
  }}
  chain forward_peer_port {{
    type nat hook prerouting priority dstnat; policy accept;
    iifname "tun0" ip daddr {address} meta l4proto {{ tcp, udp }} th dport {PEER_PORT} dnat ip to {CLIENT_IP}
  }}
  chain masquerade_payload {{
    type nat hook postrouting priority srcnat; policy accept;
    oifname "tun0" ip saddr {CLIENT_IP} snat ip to {address}
  }}
}}
"""


def ip_rule(priority, *selector):
    args = ("pref", str(priority), *selector)
    run("ip", "-4", "rule", "del", *args, missing_ok=True)
    run("ip", "-4", "rule", "add", *args)


def init_gateway():
    nft(f"""
destroy table inet {TABLE}
table inet {TABLE} {{
  chain input {{ type filter hook input priority filter; policy drop; }}
  chain output {{ type filter hook output priority filter; policy drop; }}
  chain forward {{ type filter hook forward priority filter; policy drop; }}
}}
""")
    validate_namespace(forwarding=True)
    secret, address = profile()
    router = eth_gateway(f"{API_IP}/32")
    add_eth_routes(router, f"{API_IP}/32", POD_CIDR)
    run("ip", "link", "set", "dev", "eth0", "addrgenmode", "none")
    run("ip", "-6", "addr", "flush", "dev", "eth0")
    run("ip", "-6", "route", "flush", "dev", "eth0")
    setup_transit(secret, gateway=True)
    # Gluetun's IPv4 rules start at priority 98. Preserve cluster routes first,
    # then forward client traffic only when Gluetun has installed its tunnel route.
    ip_rule(90, "to", f"{API_IP}/32", "lookup", "main")
    ip_rule(91, "to", TRANSIT_SUBNET, "lookup", "main")
    ip_rule(92, "fwmark", str(TRANSIT_MARK), "lookup", "main")
    ip_rule(93, "iif", "transit", "lookup", str(AIRVPN_MARK))
    ip_rule(94, "iif", "transit", "unreachable")
    nft(gateway_firewall(address))


def fence(deadline):
    rules = f"flush set inet {TABLE} lease_live\nflush chain inet {TABLE} require_lease\n"
    remaining = 0
    if deadline:
        # The kernel timeout limits even an installed lease whose wall clock
        # moves back. The wall condition also rejects a delayed nft command.
        wall_now = time.time_ns()
        remaining = nonnegative_deadline(deadline, time.clock_gettime_ns(time.CLOCK_BOOTTIME))
        if remaining:
            limit = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime((wall_now + remaining) // 1_000_000_000))
            rules += f"add element inet {TABLE} lease_live {{ ipv4 timeout {remaining // 1_000_000}ms }}\n"
            rules += f'add rule inet {TABLE} require_lease meta nfproto @lease_live meta time < "{limit}" accept\n'
    nft(rules + f"add rule inet {TABLE} require_lease drop\n")
    if deadline and not remaining:
        raise RuntimeError("VPN fencing deadline expired or exceeds the supported window")


def nonnegative_deadline(deadline, now):
    remaining = deadline - now
    if remaining < 1_000_000 or remaining > MAX_FENCE_NS:
        return 0
    return remaining


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("client-init")
    commands.add_parser("gateway-init")
    commands.add_parser("renew")
    commands.add_parser("fence").add_argument("deadline", nargs="?", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.command == "client-init":
            init_client()
        elif args.command == "gateway-init":
            init_gateway()
        elif args.command == "renew":
            run("wg", "set", "transit", "listen-port", "0")
        else:
            fence(args.deadline)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError, ValueError):
        print("Failed to configure Deluge VPN networking", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
