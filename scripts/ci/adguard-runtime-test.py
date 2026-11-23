#!/usr/bin/env python3
"""Run the pinned AdGuard image against synthetic DNS/filter servers, never production."""
import base64
import copy
import http.server
import importlib.util
import ipaddress
import json
from pathlib import Path
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

spec = importlib.util.spec_from_file_location("adguard_manifest", Path(__file__).with_name("adguard-test.py"))
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)
IMAGE = "docker.io/adguard/adguardhome:v0.107.80@" + manifest.DIGEST


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE, timeout=90).strip()


def question_end(packet, offset=12):
    while packet[offset]:
        if packet[offset] & 0xC0:
            return offset + 2
        offset += packet[offset] + 1
    return offset + 1


def read_exact(stream, count):
    data = b""
    while len(data) < count:
        chunk = stream.recv(count - len(data))
        if not chunk:
            raise OSError("Truncated fixture DNS response")
        data += chunk
    return data


def query(port, name, kind=1, transport="UDP"):
    wire = b"".join(bytes([len(part)]) + part.encode() for part in name.split(".")) + b"\0"
    packet = struct.pack("!6H", 31415, 0x0100, 1, 0, 0, 0) + wire + struct.pack("!2H", kind, 1)
    if transport == "TCP":
        with socket.create_connection(("127.0.0.1", port), timeout=3) as stream:
            stream.sendall(struct.pack("!H", len(packet)) + packet)
            result = read_exact(stream, struct.unpack("!H", read_exact(stream, 2))[0])
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
            stream.settimeout(3)
            stream.sendto(packet, ("127.0.0.1", port))
            result = stream.recv(4096)
    ident, flags, _, count, _, _ = struct.unpack("!6H", result[:12])
    if ident != 31415:
        raise ValueError("Wrong fixture DNS transaction")
    offset = question_end(result) + 4
    answers = []
    for _ in range(count):
        offset = question_end(result, offset)
        rrtype, _, _, size = struct.unpack("!HHIH", result[offset:offset + 10])
        offset += 10
        if rrtype in (1, 28):
            answers.append(str(ipaddress.ip_address(result[offset:offset + size])))
        offset += size
    return flags & 15, answers


class Upstream:
    def __init__(self, private=False):
        self.private, self.fail, self.names = private, False, []
        owner = self

        class UDP(socketserver.BaseRequestHandler):
            def handle(self):
                data, stream = self.request
                stream.sendto(owner.answer(data), self.client_address)

        class TCP(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(3)
                size = struct.unpack("!H", read_exact(self.request, 2))[0]
                data = owner.answer(read_exact(self.request, size))
                self.request.sendall(struct.pack("!H", len(data)) + data)

        self.udp = socketserver.ThreadingUDPServer(("0.0.0.0", 0), UDP)
        self.port = self.udp.server_address[1]
        self.tcp = socketserver.ThreadingTCPServer(("0.0.0.0", self.port), TCP)
        for server in (self.udp, self.tcp):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def answer(self, packet):
        end = question_end(packet)
        labels, offset = [], 12
        while packet[offset]:
            size = packet[offset]
            labels.append(packet[offset + 1:offset + 1 + size].decode())
            offset += size + 1
        name = ".".join(labels)
        self.names.append(name)
        kind = struct.unpack("!H", packet[end:end + 2])[0]
        rcode = 2 if self.fail else 3 if name.startswith("missing.") else 0
        value = None
        if not rcode and kind == 1:
            value = ipaddress.ip_address("10.99.0.7" if self.private else "198.51.100.7").packed
        elif not rcode and kind == 28 and not self.private:
            value = ipaddress.ip_address("2001:db8::7").packed
        answer = b"" if value is None else b"\xc0\x0c" + struct.pack("!HHIH", kind, 1, 0, len(value)) + value
        return (packet[:2] + struct.pack("!5H", 0x8180 | rcode, 1, int(value is not None), 0, 0)
                + packet[12:end + 4] + answer)

    def close(self):
        for server in (self.udp, self.tcp):
            server.shutdown()
            server.server_close()


class Runtime:
    def __init__(self, root, config):
        self.root, self.container = root, None
        for name in ("seed", "conf", "work"):
            (root / name).mkdir(mode=0o777)
            (root / name).chmod(0o777)
        (root / "seed/config.json").write_text(json.dumps(config))
        # Seed as the runtime UID, then launch the binary directly. A shell
        # wrapper would drop its capabilities before exec under no-new-privileges.
        docker("run", "--rm", "--user", "65534:65534", "--entrypoint", "/bin/sh",
               "--mount", f"type=bind,src={root / 'seed'},dst=/seed,readonly",
               "--mount", f"type=bind,src={root / 'conf'},dst=/conf",
               IMAGE, "-c", "umask 077; cp /seed/config.json /conf/AdGuardHome.yaml")
        self.container = docker(
            "run", "--detach", "--user", "65534:65534", "--read-only",
            "--cap-drop=ALL", "--cap-add=NET_BIND_SERVICE", "--security-opt=no-new-privileges:true",
            "--sysctl", "net.ipv4.ip_unprivileged_port_start=1024",
            "--label", "homelab.fixture=adguard", "--memory=512m", "--cpus=0.5",
            "--mount", f"type=bind,src={root / 'conf'},dst=/conf",
            "--mount", f"type=bind,src={root / 'work'},dst=/work",
            "-p", "127.0.0.1::53/udp", "-p", "127.0.0.1::53/tcp", "-p", "127.0.0.1::3000/tcp",
            IMAGE, "--no-check-update", "-c", "/conf/AdGuardHome.yaml", "-w", "/work")
        try:
            self.ports = {name: int(docker("port", self.container, name).rsplit(":", 1)[1])
                          for name in ("53/udp", "53/tcp", "3000/tcp")}
        except Exception:
            self.close()
            raise

    def api(self, path, body=None, authenticated=True):
        headers = {}
        if authenticated:
            headers["Authorization"] = "Basic " + base64.b64encode(
                ("admin:" + manifest.FIXTURE_PASSWORD).encode()).decode()
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.ports['3000/tcp']}/control/{path}", data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=3) as response:
            content = response.read()
            return json.loads(content) if content else None

    def wait_ready(self, require_filter=True, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.api("status")
                filters = self.api("filtering/status")["filters"]
                if not require_filter or any(f["enabled"] and f.get("rules_count", 0) > 0 for f in filters):
                    return
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.2)
        raise TimeoutError("Synthetic AdGuard is not ready with an enabled nonempty filter")

    def close(self):
        if self.container:
            docker("rm", "--force", self.container)
        docker("run", "--rm", "--user", "65534:65534", "--entrypoint", "/bin/sh",
               "--mount", f"type=bind,src={self.root / 'conf'},dst=/conf",
               "--mount", f"type=bind,src={self.root / 'work'},dst=/work",
               IMAGE, "-c", "rm -rf /conf/* /work/*")


class AdGuardRuntimeTests(unittest.TestCase):
    def test_initialized_admin_query_history_and_persisted_statistics(self):
        check_spec = importlib.util.spec_from_file_location(
            "adguard_check", Path(__file__).resolve().parents[1] / "adguard-check.py")
        check = importlib.util.module_from_spec(check_spec)
        check_spec.loader.exec_module(check)
        # Only this isolated synthetic fixture uses HTTP on loopback. The real
        # helper has a fixed HTTPS origin and normal certificate validation.
        check.ADMIN_URL = "http://127.0.0.1:" + str(self.runtime.ports["3000/tcp"])
        check.verify_admin(check.Admin(manifest.FIXTURE_PASSWORD))
        port = self.runtime.ports["53/udp"]
        self.assertEqual(query(port, "phone.ads.fixture.test"), (0, ["0.0.0.0"]))
        entries = self.runtime.api("querylog?limit=10")["data"]
        self.assertTrue(any(e["question"]["name"] == "phone.ads.fixture.test"
                            and e["reason"].startswith("Filtered") for e in entries))
        for index in range(self.config["querylog"]["size_memory"] + 1):
            query(port, f"bounded{index}.ads.fixture.test")
        entries = self.runtime.api("querylog?limit=5000")["data"]
        self.assertLessEqual(len(entries), self.config["querylog"]["size_memory"])
        self.assertFalse(any(e["question"]["name"] == "phone.ads.fixture.test" for e in entries))
        docker("restart", self.runtime.container)
        self.runtime.ports = {name: int(docker("port", self.runtime.container, name).rsplit(":", 1)[1])
                              for name in ("53/udp", "53/tcp", "3000/tcp")}
        self.runtime.wait_ready()
        self.assertEqual(self.runtime.api("querylog?limit=1")["data"], [])
        self.assertGreaterEqual(self.runtime.api("stats")["num_dns_queries"],
                                self.config["querylog"]["size_memory"] + 2)
        self.assertEqual(docker("exec", self.runtime.container, "find", "/work", "-name", "querylog*.json*"), "")

    def test_active_filter_api_contract(self):
        check_spec = importlib.util.spec_from_file_location(
            "adguard_check", Path(__file__).resolve().parents[1] / "adguard-check.py")
        check = importlib.util.module_from_spec(check_spec)
        check_spec.loader.exec_module(check)
        filters = self.runtime.api("filtering/status")
        # This fixture replaces only the list URL with its local synthetic server.
        # Validate the real API shapes and matching list IDs, never live identity.
        self.assertEqual(filters["filters"][0]["url"], self.config["filters"][0]["url"])
        filters["filters"][0]["url"] = check.FILTER_URL
        for kind in ("A", "AAAA"):
            match = self.runtime.api("filtering/check_host?name=ads.fixture.test&qtype=" + kind)
            check.validate_filter(self.runtime.api("status"), filters, match)

    @classmethod
    def setUpClass(cls):
        cls.config = manifest.render_config()
        cls.public, cls.private = Upstream(), Upstream(private=True)
        cls.filter_failed, cls.filter_requests = False, 0

        class Filter(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                cls.filter_requests += 1
                self.send_response(503 if cls.filter_failed else 200)
                self.end_headers()
                if not cls.filter_failed:
                    self.wfile.write(b"! Synthetic fixture\n||ads.fixture.test^\n")

            def log_message(self, *_):
                pass

        cls.http = http.server.ThreadingHTTPServer(("0.0.0.0", 0), Filter)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        gateway = json.loads(docker("network", "inspect", "bridge"))[0]["IPAM"]["Config"][0]["Gateway"]
        cls.config["dns"]["upstream_dns"] = [
            f"{gateway}:{cls.public.port}", f"[/stinkyboi.com/]{gateway}:{cls.private.port}"]
        cls.config["dns"]["cache_enabled"] = False
        cls.config["filters"][0]["url"] = f"http://{gateway}:{cls.http.server_port}/filter.txt"
        cls.temp = tempfile.TemporaryDirectory(prefix="adguard-runtime-")
        root = Path(cls.temp.name) / "main"
        root.mkdir()
        cls.runtime = Runtime(root, cls.config)
        try:
            cls.runtime.wait_ready()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.runtime.close()
        cls.http.shutdown()
        cls.http.server_close()
        cls.public.close()
        cls.private.close()
        cls.temp.cleanup()

    def test_isolated_replacement_and_fresh_restore(self):
        spec = importlib.util.spec_from_file_location("adguard_recovery", manifest.ROOT / "scripts/adguard-recovery.py")
        recovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recovery)
        secret = next(d for d in manifest.documents() if d["kind"] == "ExternalSecret")
        template = secret["spec"]["target"]["template"]["data"]["config.json"]
        reconstructions = []
        def factory():
            reconstructions.append(True)
            config = recovery.render_config(template, manifest.FIXTURE_PASSWORD)
            config["dns"] = copy.deepcopy(self.config["dns"])
            config["filters"] = copy.deepcopy(self.config["filters"])
            return config
        result = recovery.recover(factory, manifest.FIXTURE_PASSWORD, IMAGE, "ads.fixture.test")
        self.assertEqual(len(reconstructions), 3)
        self.assertTrue(result["replacement_verified"])
        self.assertTrue(result["fresh_restore_verified"])
        self.assertTrue(result["administrator_access_verified"])
        self.assertFalse(result["private_routing_verified"])
        self.assertFalse(result["client_acceptance"])

    def test_both_transports_block_and_resolve(self):
        for transport in ("UDP", "TCP"):
            port = self.runtime.ports["53/" + transport.lower()]
            for index in range(10):
                self.assertEqual(query(port, f"q{index}.ads.fixture.test", transport=transport), (0, ["0.0.0.0"]))
                self.assertEqual(query(port, f"q{index}.allowed.fixture.test", transport=transport), (0, ["198.51.100.7"]))
            self.assertEqual(query(port, "ads.fixture.test", 28, transport), (0, ["::"]))
            self.assertEqual(query(port, "allowed.fixture.test", 28, transport), (0, ["2001:db8::7"]))
            self.assertEqual(query(port, "missing.fixture.test", transport=transport)[0], 3)
            self.assertEqual(query(port, "private.stinkyboi.com", transport=transport), (0, ["10.99.0.7"]))
            self.assertEqual(query(port, "private.stinkyboi.com", 28, transport), (0, []))

    def test_empty_cache_is_not_filter_ready(self):
        root = Path(self.temp.name) / "empty"
        root.mkdir()
        type(self).filter_failed = True
        runtime = None
        try:
            runtime = Runtime(root, self.config)
            runtime.wait_ready(require_filter=False)
            with self.assertRaises(TimeoutError):
                runtime.wait_ready(timeout=1)
        finally:
            if runtime:
                runtime.close()
            type(self).filter_failed = False

    def test_failed_refresh_preserves_filter(self):
        before = type(self).filter_requests
        cached = docker("exec", self.runtime.container, "sha256sum", "/work/data/filters/1.txt")
        type(self).filter_failed = True
        try:
            try:
                self.runtime.api("filtering/refresh", {"whitelist": False})
            except urllib.error.HTTPError:
                pass
            self.assertGreater(type(self).filter_requests, before)
            self.assertEqual(docker("exec", self.runtime.container, "sha256sum", "/work/data/filters/1.txt"), cached)
            self.runtime.wait_ready(timeout=2)
            self.assertEqual(query(self.runtime.ports["53/udp"], "ads.fixture.test"), (0, ["0.0.0.0"]))
        finally:
            type(self).filter_failed = False

    def test_private_failure_does_not_reach_public_upstream(self):
        self.private.fail = True
        before = len(self.public.names)
        try:
            for transport in ("UDP", "TCP"):
                port = self.runtime.ports["53/" + transport.lower()]
                self.assertEqual(query(port, "failed.stinkyboi.com", transport=transport)[0], 2)
            self.assertEqual(len(self.public.names), before)
        finally:
            self.private.fail = False


if __name__ == "__main__":
    unittest.main()
