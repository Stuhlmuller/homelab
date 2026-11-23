"""Install the Deluge VPN pod firewall and manage its WireGuard interfaces."""

import argparse
import base64
import configparser
import ipaddress
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


VPN_DIR = Path("/vpn")
RUN_DIR = Path("/run/deluge-vpn")
POD_CIDR = "10.244.0.0/16"
TRANSIT_PORT = 51820
AIRVPN_PORT = 51821
AIRVPN_TRANSPORT_MARK = 203
PEER_PORT = 5983
MTU = 1360
FIREWALL = "deluge_vpn"


@dataclass(frozen=True)
class PathConfig:
    name: str
    service: str
    gateway: str
    client: str
    route_mark: int
    transport_mark: int

    @property
    def interface(self):
        return f"vpn-{self.name}"


PATHS = {
    "a": PathConfig("a", "10.96.10.61", "172.31.61.1", "172.31.61.2", 101, 201),
    "b": PathConfig("b", "10.96.10.62", "172.31.62.1", "172.31.62.2", 102, 202),
}


@dataclass(frozen=True)
class AirVpnProfile:
    address: ipaddress.IPv4Address
    endpoint: ipaddress.IPv4Address
    port: int
    public_key: str


def run(*args, input=None, quiet=False):
    return subprocess.run(
        args,
        input=input,
        text=True,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
        check=not quiet,
    )


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


def nft(rules):
    run("nft", "-f", "-", input=rules)


def select_paths(paths):
    rules = f"flush chain inet {FIREWALL} choose_path\n"
    if len(paths) == 1:
        rules += f"add rule inet {FIREWALL} choose_path meta mark set {paths[0].route_mark}\n"
    if len(paths) == 2:
        mapping = ", ".join(f"{index} : {path.route_mark}" for index, path in enumerate(paths))
        rules += f"add rule inet {FIREWALL} choose_path meta mark set symhash mod 2 map {{ {mapping} }}\n"
    nft(rules)


def client_firewall():
    prerouting = []
    client_input = []
    client_output = []
    postrouting = []
    for path in PATHS.values():
        prerouting.append(f'iifname "{path.interface}" ct mark 0 ct mark set {path.route_mark}')
        client_input.extend((
            f'iifname "eth0" ip saddr {path.service} udp sport {TRANSIT_PORT} ct state established accept',
            f'iifname "{path.interface}" ct state {{ established, related }} accept',
            f'iifname "{path.interface}" ip daddr {path.client} ct state new meta l4proto {{ tcp, udp }} th dport {PEER_PORT} accept',
        ))
        client_output.extend((
            f'oifname "eth0" meta mark {path.transport_mark} ip daddr {path.service} udp dport {TRANSIT_PORT} accept',
            f'oifname "{path.interface}" meta nfproto ipv4 meta mark {path.route_mark} accept',
        ))
        postrouting.append(f'oifname "{path.interface}" snat ip to {path.client}')

    route_marks = ", ".join(str(path.route_mark) for path in PATHS.values())
    transport_marks = ", ".join(str(path.transport_mark) for path in PATHS.values())
    newline = "\n    "
    # The route hook runs a second route lookup when it changes a packet mark.
    # Conntrack retains the chosen path across packets and keeps ingress replies symmetric.
    # Postrouting sees the effective interface after that lookup, unlike the output hook.
    return f"""
destroy table inet {FIREWALL}
table inet {FIREWALL} {{
  chain pin_return_path {{
    type filter hook prerouting priority mangle; policy accept;
    meta nfproto != ipv4 return
    {newline.join(prerouting)}
  }}
  chain choose_path {{ }}
  chain route_payload {{
    type route hook output priority mangle; policy accept;
    meta nfproto != ipv4 return
    oifname "lo" return
    meta mark {{ {transport_marks} }} return
    ct mark {{ {route_marks} }} meta mark set ct mark return
    meta mark {{ {route_marks} }} ct mark set meta mark return
    ip daddr {POD_CIDR} return
    ct state new jump choose_path
    meta mark {{ {route_marks} }} ct mark set meta mark
  }}
  chain input {{
    type filter hook input priority filter; policy drop;
    iifname "lo" accept
    iifname "eth0" ip saddr {POD_CIDR} tcp dport {{ 8112, 9797, 9798 }} ct state {{ new, established }} accept
    {newline.join(client_input)}
  }}
  chain egress {{
    type filter hook postrouting priority filter; policy drop;
    oifname "lo" accept
    oifname "eth0" ip daddr {POD_CIDR} tcp sport {{ 8112, 9797, 9798 }} ct direction reply ct state established accept
    {newline.join(client_output)}
  }}
  chain forward {{ type filter hook forward priority filter; policy drop; }}
  chain masquerade_payload {{
    type nat hook postrouting priority srcnat; policy accept;
    {newline.join(postrouting)}
  }}
}}
"""


def gateway_firewall(path, profile):
    mss = MTU - 40
    return f"""
destroy table inet {FIREWALL}
table inet {FIREWALL} {{
  chain input {{
    type filter hook input priority filter; policy drop;
    iifname "lo" accept
    iifname "eth0" ip saddr {POD_CIDR} udp dport {TRANSIT_PORT} accept
    iifname "eth0" ip saddr {profile.endpoint} udp sport {profile.port} udp dport {AIRVPN_PORT} accept
  }}
  chain output {{
    type filter hook output priority filter; policy drop;
    oifname "lo" accept
    oifname "eth0" meta mark {path.transport_mark} ip daddr {POD_CIDR} udp sport {TRANSIT_PORT} accept
    oifname "eth0" meta mark {AIRVPN_TRANSPORT_MARK} ip daddr {profile.endpoint} udp sport {AIRVPN_PORT} udp dport {profile.port} accept
  }}
  chain forward {{
    type filter hook forward priority filter; policy drop;
    meta nfproto != ipv4 drop
    ct state invalid drop
    iifname "transit" oifname "airvpn" tcp flags & (syn | rst) == syn tcp option maxseg size > {mss} tcp option maxseg size set {mss}
    iifname "airvpn" oifname "transit" tcp flags & (syn | rst) == syn tcp option maxseg size > {mss} tcp option maxseg size set {mss}
    iifname "transit" oifname "airvpn" ip saddr {path.client} ct state {{ new, established, related }} accept
    iifname "airvpn" oifname "transit" ip daddr {path.client} ct state {{ established, related }} accept
    iifname "airvpn" oifname "transit" ip daddr {path.client} ct status dnat meta l4proto {{ tcp, udp }} th dport {PEER_PORT} accept
  }}
  chain forward_peer_port {{
    type nat hook prerouting priority dstnat; policy accept;
    iifname "airvpn" ip daddr {profile.address} meta l4proto {{ tcp, udp }} th dport {PEER_PORT} dnat ip to {path.client}
  }}
  chain masquerade_payload {{
    type nat hook postrouting priority srcnat; policy accept;
    oifname "airvpn" ip saddr {path.client} snat ip to {profile.address}
  }}
}}
"""


def reset_interface(name, address):
    run("ip", "link", "del", "dev", name, quiet=True)
    run("ip", "link", "add", "dev", name, "type", "wireguard")
    run("ip", "link", "set", "dev", name, "mtu", str(MTU))
    run("ip", "-4", "addr", "add", address, "dev", name)


def add_policy_route(interface, mark, selector, address=None):
    table = str(mark)
    run("ip", "-4", "rule", "del", "pref", table, *selector, "lookup", table, quiet=True)
    # If the link disappears, keep marked traffic from falling through to eth0.
    run("ip", "-4", "route", "replace", "unreachable", "default", "metric", "32767", "table", table)
    route = ["ip", "-4", "route", "replace", "default", "dev", interface]
    if address:
        route.extend(("src", address))
    run(*route, "metric", "10", "table", table)
    run("ip", "-4", "rule", "add", "pref", table, *selector, "lookup", table)


def transit_endpoint(path):
    return f"{path.service}:{TRANSIT_PORT}"


def wireguard_key(value):
    value = value.strip()
    if len(value) != 44 or len(base64.b64decode(value, validate=True)) != 32:
        raise ValueError("Expected a base64 WireGuard key")
    return value


def read_key(path):
    try:
        return wireguard_key(path.read_text())
    except (OSError, ValueError):
        raise RuntimeError(f"Missing or invalid transit WireGuard key in {path.name}") from None


def transit_peer(path):
    return read_key(VPN_DIR / "transit" / f"{path.name}.public")


def setup_client():
    nft(client_firewall())
    validate_namespace(forwarding=False)
    for path in PATHS.values():
        private_key_path = VPN_DIR / "transit" / f"{path.name}.private"
        read_key(private_key_path)
        reset_interface(path.interface, f"{path.client}/30")
        run(
            "wg", "set", path.interface, "fwmark", str(path.transport_mark),
            "private-key", str(private_key_path),
            "peer", transit_peer(path), "allowed-ips", "0.0.0.0/0",
            "endpoint", transit_endpoint(path), "persistent-keepalive", "10",
        )
        run("ip", "link", "set", "dev", path.interface, "up")
        add_policy_route(path.interface, path.route_mark, ("fwmark", str(path.route_mark)), path.client)


def renew_client_path(path):
    run("wg", "set", path.interface, "listen-port", "0", "peer", transit_peer(path), "endpoint", transit_endpoint(path))


def read_airvpn_profile(path):
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open() as stream:
            parser.read_file(stream)
        interface = parser["Interface"]
        peer = parser["Peer"]
        addresses = [ipaddress.ip_interface(value.strip()) for value in interface["Address"].split(",")]
        ipv4_addresses = [address.ip for address in addresses if address.version == 4]
        if len(ipv4_addresses) != 1:
            raise ValueError
        endpoint, port = peer["Endpoint"].split(":")
        endpoint = ipaddress.IPv4Address(endpoint)
        port = int(port)
        if not endpoint.is_global or not 1 <= port <= 65535:
            raise ValueError
        profile = AirVpnProfile(ipv4_addresses[0], endpoint, port, wireguard_key(peer["PublicKey"]))
        return profile, wireguard_key(interface["PrivateKey"]), wireguard_key(peer["PresharedKey"])
    except (OSError, configparser.Error, KeyError, ValueError):
        raise RuntimeError("AirVPN profile is missing or invalid. Expected one IPv4 address, a numeric IPv4 endpoint, and WireGuard keys.") from None


def setup_gateway(path):
    ready = RUN_DIR / "ready"
    ready.unlink(missing_ok=True)
    nft(f"""
destroy table inet {FIREWALL}
table inet {FIREWALL} {{
  chain input {{ type filter hook input priority filter; policy drop; }}
  chain output {{ type filter hook output priority filter; policy drop; }}
  chain forward {{ type filter hook forward priority filter; policy drop; }}
}}
""")
    profile, private_key, preshared_key = read_airvpn_profile(VPN_DIR / "airvpn/wg0.conf")
    validate_namespace(forwarding=True)
    transit_private_key = VPN_DIR / "transit/private"
    read_key(transit_private_key)
    transit_public_key = read_key(VPN_DIR / "transit/peer.public")
    nft(gateway_firewall(path, profile))

    reset_interface("transit", f"{path.gateway}/30")
    run(
        "wg", "set", "transit", "fwmark", str(path.transport_mark), "listen-port", str(TRANSIT_PORT),
        "private-key", str(transit_private_key),
        "peer", transit_public_key, "allowed-ips", f"{path.client}/32",
    )
    reset_interface("airvpn", f"{profile.address}/32")
    with tempfile.TemporaryDirectory(dir=RUN_DIR) as keys:
        private_key_file = Path(keys) / "private"
        private_key_file.write_text(private_key + "\n")
        preshared_key_file = Path(keys) / "preshared"
        preshared_key_file.write_text(preshared_key + "\n")
        run(
            "wg", "set", "airvpn", "fwmark", str(AIRVPN_TRANSPORT_MARK), "listen-port", str(AIRVPN_PORT),
            "private-key", str(private_key_file), "peer", profile.public_key, "allowed-ips", "0.0.0.0/0",
            "endpoint", f"{profile.endpoint}:{profile.port}", "preshared-key", str(preshared_key_file),
            "persistent-keepalive", "15",
        )
    run("ip", "link", "set", "dev", "airvpn", "up")
    add_policy_route("airvpn", path.route_mark, ("iif", "transit"))
    run("ip", "link", "set", "dev", "transit", "up")
    ready.touch()

    def terminate(*_):
        ready.unlink(missing_ok=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    while True:
        signal.pause()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("client-init")
    commands.add_parser("gateway").add_argument("path", choices=PATHS)
    commands.add_parser("renew").add_argument("path", choices=PATHS)
    commands.add_parser("select").add_argument("paths", nargs="*")
    args = parser.parse_args()
    try:
        if args.command == "client-init":
            setup_client()
        elif args.command == "gateway":
            setup_gateway(PATHS[args.path])
        elif args.command == "renew":
            renew_client_path(PATHS[args.path])
        else:
            if set(args.paths) - PATHS.keys() or len(set(args.paths)) != len(args.paths):
                parser.error("select accepts only the unique path names a and b")
            select_paths([PATHS[name] for name in args.paths])
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError):
        print("Failed to configure Deluge VPN networking. Check the command error above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
