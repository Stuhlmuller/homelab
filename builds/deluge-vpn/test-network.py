"""Exercise the shipped Linux dataplane with two emulated WireGuard exits."""
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


RUNTIME = Path("/opt/deluge-vpn")
FIXTURE = Path("/fixture.py")
ROOT = Path("/tmp/deluge-fixture")
NAMES = {"client": "10.244.2.2", "a": "10.244.3.2", "b": "10.244.4.2"}
VIP = {"a": "10.96.10.61", "b": "10.96.10.62"}
EXIT = {"a": "10.88.1.2", "b": "10.88.2.2"}
TRANSIT_ADDRESS = {"a": "172.31.61.2", "b": "172.31.62.2"}
UNDERLAY = "11.0.0.1"
PUBLIC = "203.0.113.10"
DNS_QUERY = bytes.fromhex("cafe01000001000000000000076578616d706c6503636f6d0000010001")


def run(*argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, **kwargs)


def ns(name, *argv, **kwargs):
    return run("ip", "netns", "exec", name, *map(str, argv), **kwargs)


def popen(name, *argv, **kwargs):
    return subprocess.Popen(("ip", "netns", "exec", name, *map(str, argv)), **kwargs)


def setup_links():
    run("ip", "link", "add", "underlay", "type", "bridge")
    run("ip", "link", "set", "underlay", "up")
    for address in ("10.244.2.1/24", "10.244.3.1/24", "10.244.4.1/24",
                    UNDERLAY + "/32", PUBLIC + "/32",
                    "1.1.1.1/32", "8.8.8.8/32", "2001:db8:1::1/64"):
        run("ip", "addr", "add", address, "dev", "underlay")
    for name, address in NAMES.items():
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
    run("sysctl", "-qw", "net.ipv4.ip_forward=1")
    # The Linux fixture owns the endpoint IP and gateway networks on the same
    # bridge. Explicitly select the endpoint IP for emulator transport replies.
    for path in VIP:
        run("ip", "route", "replace", NAMES[path] + "/32", "dev", "underlay", "src", UNDERLAY)
    service_nat = "\n".join(
        f"ip daddr {vip} udp dport 51820 dnat to {NAMES[path]}:51820" for path, vip in VIP.items()
    )
    # Emulate kube-proxy DNAT and its reverse translation on gateway replies.
    run("nft", "-f", "-", input=f"""
table ip fixture {{
  chain services {{
    type nat hook prerouting priority dstnat; policy accept;
    {service_nat}
  }}
}}
""")


def keypair():
    private = run("wg", "genkey", capture_output=True).stdout.strip()
    public = run("wg", "pubkey", input=private + "\n", capture_output=True).stdout.strip()
    return private, public


def write(path, content):
    path.write_text(content + "\n")
    path.chmod(0o600)


def setup_profiles():
    client = ROOT / "client"
    (client / "transit").mkdir(parents=True)
    for index, path in enumerate(VIP, start=1):
        gateway = ROOT / path
        (gateway / "transit").mkdir(parents=True)
        (gateway / "airvpn").mkdir()
        client_private, client_public = keypair()
        gateway_private, gateway_public = keypair()
        air_private, air_public = keypair()
        server_private, server_public = keypair()
        psk = run("wg", "genpsk", capture_output=True).stdout.strip()
        write(client / "transit" / (path + ".private"), client_private)
        write(client / "transit" / (path + ".public"), gateway_public)
        write(gateway / "transit" / "private", gateway_private)
        write(gateway / "transit" / "peer.public", client_public)
        port = 1636 + index
        write(gateway / "airvpn" / "wg0.conf", f"""[Interface]
PrivateKey = {air_private}
Address = {EXIT[path]}/32
[Peer]
PublicKey = {server_public}
PresharedKey = {psk}
Endpoint = {UNDERLAY}:{port}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 5""")
        server_key = ROOT / "server-key"
        server_psk = ROOT / "server-psk"
        write(server_key, server_private)
        write(server_psk, psk)
        link = "server-" + path
        run("ip", "link", "add", link, "type", "wireguard")
        run("wg", "set", link, "listen-port", str(port), "private-key", str(server_key),
            "peer", air_public, "preshared-key", str(server_psk),
            "allowed-ips", EXIT[path] + "/32")
        run("ip", "addr", "add", f"10.88.{index}.1/32", "dev", link)
        run("ip", "link", "set", link, "up")
        run("ip", "route", "add", EXIT[path] + "/32", "dev", link)
        server_key.unlink()
        server_psk.unlink()


def launch_with_profiles(namespace, *args, wait=False, env=None):
    # Pods mount different secrets and runtime directories. Reproduce that
    # isolation using a separate mount namespace for each bootstrap invocation.
    profiles = ROOT / namespace
    runtime = profiles / "run"
    runtime.mkdir(exist_ok=True)
    command = ("unshare", "-m", "sh", "-ec",
               'mount --bind "$1" /vpn; mount --bind "$2" /run/deluge-vpn; '
               'shift 2; exec "$@"', "fixture", profiles, runtime,
               sys.executable, "-B", *args)
    if wait:
        return ns(namespace, *command, env=env)
    return popen(namespace, *command, env=env)


class DNSHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        query = self.rfile.read(int(self.headers["Content-Length"]))
        end = 12
        while query[end]:
            end += 1 + query[end]
        question = query[12:end + 5]
        response = (query[:2] + b"\x81\x80" + b"\x00\x01\x00\x01\x00\x00\x00\x00"
                    + question + bytes.fromhex("c00c000100010000003c0004cb00710a"))
        self.send_response(200)
        self.send_header("Content-Type", "application/dns-message")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *_):
        pass


def serve_doh(target):
    httpd = ThreadingHTTPServer((target, 443), DNSHandler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain("/tls/cert.pem", "/tls/key.pem")
    httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def echo(address, port, *, udp):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((address, port))
        if not udp:
            listener.listen(30)
        while True:
            if udp:
                data, peer = listener.recvfrom(1024)
                listener.sendto(peer[0].encode() + b" " + data, peer)
            else:
                conn, peer = listener.accept()
                threading.Thread(target=echo_connection, args=(conn, peer), daemon=True).start()


def echo_connection(conn, peer):
    with conn:
        while data := conn.recv(1024):
            conn.sendall(peer[0].encode() + b" " + data)


def read_health():
    program = 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:9999/metrics", timeout=1).read().decode())'
    try:
        output = ns("client", sys.executable, "-c", program, capture_output=True).stdout
    except subprocess.CalledProcessError:
        return None
    return {path for path in EXIT if f'deluge_vpn_path_healthy{{path="{path}"}} 1' in output}


def assert_readiness(expected):
    program = '''import urllib.error, urllib.request
try:
    response = urllib.request.urlopen("http://127.0.0.1:9999/", timeout=1)
except urllib.error.HTTPError as response:
    print(response.code)
else:
    print(response.status)
'''
    status = ns("client", sys.executable, "-c", program, capture_output=True).stdout.strip()
    assert status == str(expected), status


def await_paths(expected, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if read_health() == expected:
            return
        time.sleep(0.2)
    raise AssertionError(f"wanted healthy paths {expected}, got {read_health()}")


def request(target, port, *, udp=False, body=b"proof", family=socket.AF_INET):
    with socket.socket(family, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as conn:
        conn.settimeout(0.6)
        conn.connect((target, port))
        conn.sendall(body)
        return conn.recv(1024)


def surviving_flow():
    for _ in range(30):
        with socket.create_connection((PUBLIC, 9000), timeout=1) as conn:
            conn.sendall(b"before")
            if conn.recv(1024) == EXIT["b"].encode() + b" before":
                print("ready", flush=True)
                assert sys.stdin.readline().strip() == "verify"
                conn.sendall(b"after")
                assert conn.recv(1024) == EXIT["b"].encode() + b" after"
                return
    raise AssertionError("Could not establish a TCP flow through path b")


def exercise(kind):
    # Exercises run with ordinary application privileges.
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    if kind == "blocked":
        for target, port, family in ((PUBLIC, 9000, socket.AF_INET),
                                     ("1.1.1.1", 53, socket.AF_INET),
                                     ("2001:db8:1::1", 9000, socket.AF_INET6)):
            for udp in (True, False):
                try:
                    with socket.socket(family, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as probe:
                        probe.settimeout(0.15)
                        if udp:
                            probe.sendto(b"leak-fixture", (target, port))
                        else:
                            probe.connect((target, port))
                    if not udp:
                        raise AssertionError(f"direct TCP reached {target}:{port}")
                except OSError:
                    # A firewall rejection is expected. Packet capture also checks for leaks.
                    pass
    elif kind == "surviving":
        surviving_flow()
    elif kind == "dns":
        for udp in (True, False):
            body = DNS_QUERY if udp else struct.pack("!H", len(DNS_QUERY)) + DNS_QUERY
            answer = request("127.0.0.1", 53, udp=udp, body=body)
            if not udp:
                answer = answer[2:]
            assert answer[:2] == DNS_QUERY[:2] and answer[7] == 1, answer.hex()
    else:
        exits = set()
        for udp in (True, False):
            for _ in range(20):
                answer = request(PUBLIC, 9000, udp=udp)
                assert answer.endswith(b" proof"), answer
                exits.add(answer.split()[0].decode())
        print(json.dumps(sorted(exits)))


def assert_no_leak(capture):
    found = []
    while True:
        try:
            frame = capture.recv(65535)
        except BlockingIOError:
            break
        ethernet_type = frame[12:14]
        if ethernet_type == b"\x08\x00" and frame[26:30] == socket.inet_aton(NAMES["client"]):
            protocol = frame[23]
            destination = str(ipaddress.IPv4Address(frame[30:34]))
            transport = 14 + (frame[14] & 15) * 4
            if protocol != 17 or destination not in VIP.values() or frame[transport + 2:transport + 4] != struct.pack("!H", 51820):
                found.append((protocol, destination))
        elif ethernet_type == b"\x86\xdd" and frame[22:38] == socket.inet_pton(socket.AF_INET6, "2001:db8:1::2"):
            # Local IPv6 neighbor discovery can occur independently of app sockets.
            if frame[20] != 58:
                found.append(("ipv6", str(ipaddress.IPv6Address(frame[38:54]))))
    assert not found, found


def main():
    os.umask(0o077)
    ROOT.mkdir()
    Path("/vpn").mkdir(exist_ok=True)
    Path("/run/deluge-vpn").mkdir(exist_ok=True)
    setup_links()
    setup_profiles()
    capture = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
    capture.bind(("v-client", 0))
    capture.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1_048_576)
    capture.setblocking(False)
    launch_with_profiles("client", RUNTIME / "network.py", "client-init", wait=True)
    ns("client", sys.executable, FIXTURE, "exercise", "blocked")
    assert_no_leak(capture)

    serve_doh("1.1.1.1")
    serve_doh("8.8.8.8")
    for udp in (True, False):
        threading.Thread(target=echo, args=(PUBLIC, 9000), kwargs={"udp": udp}, daemon=True).start()
    peers = [popen("client", sys.executable, FIXTURE, "echo", path, protocol)
             for path in TRANSIT_ADDRESS for protocol in ("tcp", "udp")]
    health_env = dict(os.environ, SSL_CERT_FILE="/tls/cert.pem")
    processes = list(peers)
    try:
        for path in EXIT:
            processes.append(launch_with_profiles(path, RUNTIME / "network.py", "gateway", path))
        health = launch_with_profiles("client", RUNTIME / "health.py", env=health_env)
        processes.append(health)
        await_paths(set(EXIT), 35)
        assert_readiness(200)
        ns("client", sys.executable, FIXTURE, "exercise", "dns")
        exits = ns("client", sys.executable, FIXTURE, "exercise", "public", capture_output=True).stdout
        assert set(json.loads(exits)) == set(EXIT.values()), exits
        for path in EXIT:
            for udp in (False, True):
                reply = request(EXIT[path], 5983, udp=udp)
                assert reply.endswith(b" proof"), reply

        surviving = popen("client", sys.executable, FIXTURE, "exercise", "surviving",
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        processes.append(surviving)
        assert surviving.stdout.readline().strip() == "ready"
        run("ip", "link", "set", "server-a", "down")
        await_paths({"b"}, 15)
        surviving.communicate(input="verify\n", timeout=5)
        assert surviving.returncode == 0, "Established flow on the surviving path was interrupted"
        exits = ns("client", sys.executable, FIXTURE, "exercise", "public", capture_output=True).stdout
        assert json.loads(exits) == [EXIT["b"]], exits
        run("ip", "link", "set", "server-b", "down")
        await_paths(set(), 15)
        assert_readiness(503)
        ns("client", sys.executable, FIXTURE, "exercise", "blocked")
        assert_no_leak(capture)
        run("ip", "link", "set", "server-a", "up")
        run("ip", "route", "replace", EXIT["a"] + "/32", "dev", "server-a")
        await_paths({"a"}, 30)
        ns("client", sys.executable, FIXTURE, "exercise", "dns")
        run("ip", "link", "set", "server-b", "up")
        run("ip", "route", "replace", EXIT["b"] + "/32", "dev", "server-b")
        await_paths(set(EXIT), 30)
        processes[len(peers)].terminate()
        processes[len(peers)].wait(timeout=5)
        ns("a", "ip", "link", "del", "transit")
        ns("a", "ip", "link", "del", "airvpn")
        await_paths({"b"}, 15)
        processes.append(launch_with_profiles("a", RUNTIME / "network.py", "gateway", "a"))
        await_paths(set(EXIT), 35)
        health.kill()
        health.wait(timeout=5)
        run("ip", "link", "set", "server-a", "down")
        run("ip", "link", "set", "server-b", "down")
        ns("client", sys.executable, FIXTURE, "exercise", "blocked")
        assert_no_leak(capture)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
    print("PASS: two active exits, DNS and forwarded TCP/UDP, path failover and recovery, zero direct egress")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        main()
    elif sys.argv[1] == "echo":
        echo(TRANSIT_ADDRESS[sys.argv[2]], 5983, udp=sys.argv[3] == "udp")
    else:
        exercise(sys.argv[2])
