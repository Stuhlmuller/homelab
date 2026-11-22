"""Isolated fail-closed check for a shared-identity, two-gateway topology."""
import ipaddress
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time


RUNTIME = Path("/opt/deluge-gluetun/network.py")
FIXTURE = Path("/fixture.py")
PROFILE_DIR = Path("/vpn-source")
POD = {"client": "10.244.2.2", "a": "10.244.3.2", "b": "10.244.4.2"}
VIP = "10.96.10.61"
AIRVPN = "11.0.0.1"
EXIT = "10.88.1.2"
PUBLIC = "203.0.113.10"


def run(*argv, **kwargs):
    return subprocess.run(tuple(map(str, argv)), check=True, text=True, **kwargs)


def ns(name, *argv, **kwargs):
    return run("ip", "netns", "exec", name, *argv, **kwargs)


def configure_links():
    run("ip", "link", "add", "underlay", "type", "bridge")
    run("ip", "link", "set", "underlay", "up")
    for address in ("10.244.2.1/24", "10.244.3.1/24", "10.244.4.1/24",
                    AIRVPN + "/32", PUBLIC + "/32", "2001:db8:1::1/64"):
        run("ip", "addr", "add", address, "dev", "underlay")

    run("sysctl", "-qw", "net.ipv4.ip_forward=1")
    for name, address in POD.items():
        run("ip", "netns", "add", name)
        run("ip", "link", "add", f"v-{name}", "type", "veth", "peer", "name",
            "eth0", "netns", name)
        run("ip", "link", "set", f"v-{name}", "master", "underlay")
        run("ip", "link", "set", f"v-{name}", "up")
        ns(name, "ip", "link", "set", "lo", "up")
        ns(name, "ip", "link", "set", "eth0", "up")
        ns(name, "ip", "addr", "add", address + "/24", "dev", "eth0")
        ns(name, "ip", "route", "add", "default", "via", address.rsplit(".", 1)[0] + ".1")
        ns(name, "sysctl", "-qw", "net.ipv4.ip_forward=1",
           "net.ipv4.conf.all.rp_filter=0", "net.ipv4.conf.default.rp_filter=0",
           "net.ipv4.conf.eth0.rp_filter=0")
    ns("client", "ip", "-6", "addr", "add", "2001:db8:1::2/64", "dev", "eth0", "nodad")
    ns("client", "ip", "-6", "route", "add", "default", "via", "2001:db8:1::1")
    for gateway in ("a", "b"):
        run("ip", "route", "replace", POD[gateway] + "/32", "dev", "underlay", "src", AIRVPN)

    run("nft", "-f", "-", input="""
table ip fixture {
  chain service {
    type nat hook prerouting priority dstnat; policy accept;
  }
}
""")


def select_gateway(name):
    operation = "flush chain ip fixture service\n"
    if name:
        operation += f"add rule ip fixture service ip daddr {VIP} udp dport 51820 dnat to {POD[name]}:51820\n"
    run("nft", "-f", "-", input=operation)


def keypair():
    private = run("wg", "genkey", capture_output=True).stdout.strip()
    public = run("wg", "pubkey", input=private + "\n", capture_output=True).stdout.strip()
    return private, public


def configure_provider():
    PROFILE_DIR.mkdir(exist_ok=True)
    gateway_private, gateway_public = keypair()
    provider_private, provider_public = keypair()
    psk = run("wg", "genpsk", capture_output=True).stdout.strip()
    (PROFILE_DIR / "wg0.conf").write_text(f"""[Interface]
PrivateKey = {gateway_private}
Address = {EXIT}/32
[Peer]
PublicKey = {provider_public}
PresharedKey = {psk}
Endpoint = {AIRVPN}:1637
AllowedIPs = 0.0.0.0/0
""")
    private_file = Path("/tmp/provider-key")
    gateway_file = Path("/tmp/gateway-key")
    preshared_file = Path("/tmp/provider-psk")
    private_file.write_text(provider_private + "\n")
    gateway_file.write_text(gateway_private + "\n")
    preshared_file.write_text(psk + "\n")
    run("ip", "link", "add", "provider", "type", "wireguard")
    run("wg", "set", "provider", "listen-port", "1637", "private-key", private_file,
        "peer", gateway_public, "preshared-key", preshared_file, "allowed-ips", EXIT + "/32")
    run("ip", "addr", "add", "10.88.1.1/32", "dev", "provider")
    run("ip", "link", "set", "provider", "up")
    run("ip", "route", "add", EXIT + "/32", "dev", "provider")
    for name in ("a", "b"):
        net(name, "gateway-init")
        # Gluetun owns tun0 in production. Emulate its kernel WireGuard
        # interface, fwmark, default route and shared upstream identity here.
        ns(name, "ip", "link", "add", "tun0", "type", "wireguard")
        ns(name, "wg", "set", "tun0", "fwmark", "51820", "private-key", gateway_file,
           "peer", provider_public, "preshared-key", preshared_file, "allowed-ips", "0.0.0.0/0",
           "endpoint", f"{AIRVPN}:1637", "persistent-keepalive", "2")
        ns(name, "ip", "addr", "add", EXIT + "/32", "dev", "tun0")
        ns(name, "ip", "link", "set", "tun0", "up")
        ns(name, "ip", "route", "add", "default", "dev", "tun0", "table", "51820")
        ns(name, "ip", "rule", "add", "pref", "120", "not", "fwmark", "51820", "lookup", "51820")
        ns(name, "ip", "rule", "add", "pref", "110", "lookup", "main", "suppress_prefixlength", "0")
    for path in (private_file, gateway_file, preshared_file):
        path.unlink()


def net(name, *args):
    return ns(name, sys.executable, "-B", RUNTIME, *args)


def fence(name, seconds):
    net(name, "fence", time.clock_gettime_ns(time.CLOCK_BOOTTIME) + seconds * 1_000_000_000 if seconds else 0)


def echo(address, port, udp):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((address, port))
        if not udp:
            sock.listen()
        while True:
            if udp:
                data, peer = sock.recvfrom(512)
                sock.sendto(data + b" " + peer[0].encode(), peer)
            else:
                conn, peer = sock.accept()
                with conn:
                    conn.settimeout(1)
                    data = conn.recv(512)
                    conn.sendall(data + b" " + peer[0].encode())


def request(address, port, udp):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        sock.connect((address, port))
        sock.sendall(b"deluge")
        return sock.recv(512)


def client(action):
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    if action == "connected":
        for udp in (False, True):
            assert request(PUBLIC, 9000, udp) == b"deluge " + EXIT.encode()
        return

    for address, port, family in ((PUBLIC, 9000, socket.AF_INET),
                                  ("9.9.9.9", 53, socket.AF_INET),
                                  ("2001:db8:1::1", 9000, socket.AF_INET6)):
        for udp in (False, True):
            with socket.socket(family, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                try:
                    sock.connect((address, port))
                    sock.sendall(b"must stay inside the pod")
                    assert not sock.recv(512), f"unexpected public reply from {address}:{port}"
                except OSError:
                    continue


def assert_no_client_leak(capture):
    while True:
        try:
            packet = capture.recv(65535)
        except BlockingIOError:
            return
        if packet[12:14] == b"\x08\x00" and packet[26:30] == socket.inet_aton(POD["client"]):
            protocol = packet[23]
            address = str(ipaddress.IPv4Address(packet[30:34]))
            payload = 14 + (packet[14] & 15) * 4
            assert protocol == 17 and address == VIP and packet[payload + 2:payload + 4] == struct.pack("!H", 51820), (
                f"direct IPv4 packet on Deluge underlay: protocol {protocol}, destination {address}")
        if packet[12:14] == b"\x86\xdd" and packet[22:38] == socket.inet_pton(socket.AF_INET6, "2001:db8:1::2"):
            assert packet[20] == 58, "direct IPv6 packet on Deluge underlay"


def expect_connectivity(gateway):
    for _ in range(8):
        fence(gateway, 7)
        try:
            ns("client", sys.executable, FIXTURE, "connected", capture_output=True)
            return
        except subprocess.CalledProcessError:
            time.sleep(0.25)
    raise AssertionError(f"public traffic did not recover through gateway {gateway}")


def main():
    os.umask(0o077)
    configure_links()
    configure_provider()
    capture = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
    capture.bind(("v-client", 0))
    capture.setblocking(False)
    net("client", "client-init")
    ns("client", sys.executable, FIXTURE, "blocked")
    assert_no_client_leak(capture)

    for udp in (False, True):
        threading.Thread(target=echo, args=(PUBLIC, 9000, udp), daemon=True).start()
    peers = [subprocess.Popen(("ip", "netns", "exec", "client", sys.executable, str(FIXTURE), "echo", proto))
             for proto in ("tcp", "udp")]
    try:
        select_gateway("a")
        net("client", "renew")
        expect_connectivity("a")
        for udp in (False, True):
            assert request(EXIT, 5983, udp).startswith(b"deluge ")

        # Simulate a frozen leader: keep its tun0 and the stale Service
        # endpoint. The local packet fence must expire without a userspace stop.
        fence("a", 2)
        time.sleep(3)
        ns("client", sys.executable, FIXTURE, "blocked")
        assert_no_client_leak(capture)
        select_gateway("b")
        net("client", "renew")
        expect_connectivity("b")
        for udp in (False, True):
            assert request(EXIT, 5983, udp).startswith(b"deluge ")

        fence("b", 0)
        select_gateway(None)
        ns("client", sys.executable, FIXTURE, "blocked")
        assert_no_client_leak(capture)
    finally:
        for child in peers:
            child.terminate()
    print("PASS: shared provider identity, fenced old gateway, automatic-path data handoff, no direct egress")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        main()
    elif sys.argv[1] == "echo":
        echo("0.0.0.0", 5983, sys.argv[2] == "udp")
    else:
        client(sys.argv[1])
