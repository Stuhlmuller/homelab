#!/usr/bin/env python3
"""Exercise the rendered DNS views against pinned k8s_gateway and a fake API."""

import argparse
import ipaddress
import json
import re
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
CHART = "oci://codeberg.org/k8s-gateway/charts/k8s-gateway"
VALUES = ROOT / "clusters/homelab/platform/tailnet-dns/values.yaml"
TRAEFIK_VALUES = ROOT / "clusters/homelab/apps/traefik/values.yaml"
SIDECAR_IP = "100.101.102.103"
PUBLIC_A = "192.0.2.55"
PUBLIC_AAAA = "2001:db8::55"
QTYPES = {"A": 1, "MX": 15, "TXT": 16, "AAAA": 28}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def load_yaml(path):
    return json.loads(subprocess.check_output(
        ["yq", "ea", "-o=json", "-I=0", "select(document_index == 0)", str(path)],
        text=True))


def rendered_corefile():
    chart = subprocess.run(
        ["helm", "template", "tailnet-dns", CHART, "--version", "4.0.0",
         "--namespace", "tailnet-dns", "-f", str(VALUES)],
        check=True, text=True, capture_output=True)
    check("sha256:b02209df03b08706179875b6e1887cb6064a589b591a0ce1e809a354811e37a7"
          in chart.stderr, "pinned chart digest changed")
    query = 'select(.kind == "ConfigMap" and .metadata.name == "tailnet-dns-k8s-gateway") | .data.Corefile'
    return json.loads(subprocess.check_output(
        ["yq", "ea", "-o=json", "-I=0", query, "-"],
        input=chart.stdout, text=True))


def dns_response(query, seen):
    cursor = 12
    labels = []
    while query[cursor]:
        length = query[cursor]
        labels.append(query[cursor + 1:cursor + 1 + length].decode("ascii"))
        cursor += 1 + length
    cursor += 1
    qtype, qclass = struct.unpack_from("!HH", query, cursor)
    name = ".".join(labels) + "."
    seen.append((name, qtype))
    question = query[12:cursor + 4]
    answer_data = {
        1: ipaddress.IPv4Address(PUBLIC_A).packed,
        28: ipaddress.IPv6Address(PUBLIC_AAAA).packed,
        15: struct.pack("!H", 10) + b"\x04mail\x07example\x00",
        16: b"\x06public",
    }.get(qtype)
    answer = b""
    if answer_data is not None and qclass == 1:
        answer = (b"\xc0\x0c" + struct.pack("!HHIH", qtype, qclass, 30, len(answer_data))
                  + answer_data)
    return (query[:2] + struct.pack("!HHHHH", 0x8180, 1, bool(answer), 0, 0)
            + question + answer)


class PublicUDP(socketserver.BaseRequestHandler):
    def handle(self):
        query, sock = self.request
        sock.sendto(dns_response(query, self.server.seen), self.client_address)


class PublicTCP(socketserver.BaseRequestHandler):
    def handle(self):
        header = self.request.recv(2)
        if len(header) != 2:
            return
        length = struct.unpack("!H", header)[0]
        query = b""
        while len(query) < length:
            chunk = self.request.recv(length - len(query))
            if not chunk:
                return
            query += chunk
        answer = dns_response(query, self.server.seen)
        self.request.sendall(struct.pack("!H", len(answer)) + answer)


class FakeAPI(BaseHTTPRequestHandler):
    def do_GET(self):
        request = urlsplit(self.path)
        if request.path.endswith("/customresourcedefinitions/dnsendpoints.externaldns.k8s.io") \
                or request.path.endswith("/customresourcedefinitions/gatewayclasses.gateway.networking.k8s.io"):
            self.send_response(404)
            self.end_headers()
            return
        if request.path == "/api/v1/services":
            kind, version, items = "ServiceList", "v1", self.server.services
        elif request.path == "/apis/discovery.k8s.io/v1/endpointslices":
            kind, version, items = "EndpointSliceList", "discovery.k8s.io/v1", self.server.slices
        else:
            self.send_response(404)
            self.end_headers()
            return
        if parse_qs(request.query).get("watch") == ["true"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps({"apiVersion": version, "kind": kind,
                           "metadata": {"resourceVersion": "1"}, "items": items}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def fake_objects(state, hostnames):
    service = {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": "sidecar", "namespace": "traefik", "resourceVersion": "1",
                     "labels": {"homelab.rst.io/private-dns": "approved"},
                     "annotations": {"coredns.io/hostname": hostnames,
                                     "k8s-gateway.dns/resolve-endpoints": "true"}},
        "spec": {"type": "ClusterIP", "clusterIP": "None"},
    }
    endpoint = {"addresses": [SIDECAR_IP], "conditions": {"ready": state == "ready"}}
    slices = [] if state == "empty" else [{
        "apiVersion": "discovery.k8s.io/v1", "kind": "EndpointSlice",
        "metadata": {"name": "sidecar-1", "namespace": "traefik", "resourceVersion": "1",
                     "labels": {"kubernetes.io/service-name": "sidecar"}},
        "addressType": "IPv4", "endpoints": [endpoint], "ports": [],
    }]
    return ([] if state == "absent-service" else [service], slices)


def query(port, name, record_type, *, tcp=False):
    command = ["dig", "@127.0.0.1", "-p", str(port), name, record_type,
               "+time=1", "+tries=1", "+noall", "+comments", "+answer"]
    if tcp:
        command.append("+tcp")
    result = subprocess.run(command, text=True, capture_output=True, timeout=3)
    check(result.returncode == 0, f"DNS query failed: {name} {record_type}: {result.stderr}")
    return result.stdout


def test_state(state, binary, corefile, hostnames, public_port):
    with tempfile.TemporaryDirectory(prefix="tailnet-dns-runtime-") as temp:
        temp = Path(temp)
        api = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        api.services, api.slices = fake_objects(state, hostnames)
        api_thread = threading.Thread(target=api.serve_forever, daemon=True)
        api_thread.start()
        kubeconfig = temp / "kubeconfig"
        kubeconfig.write_text(
            'apiVersion: v1\nkind: Config\nclusters:\n- name: fixture\n  cluster:\n'
            f'    server: http://127.0.0.1:{api.server_port}\n'
            'contexts:\n- name: fixture\n  context:\n    cluster: fixture\n    user: fixture\n'
            'current-context: fixture\nusers:\n- name: fixture\n  user: {}\n')
        with socketserver.UDPServer(("127.0.0.1", 0), PublicUDP) as unused:
            dns_port = unused.server_address[1]
        fixture = corefile.replace(".:1053", f".:{dns_port}")
        fixture = fixture.replace("k8s_gateway stinkyboi.com {",
                                  f"k8s_gateway stinkyboi.com {{\n            kubeconfig {kubeconfig}")
        fixture = fixture.replace("forward . 1.1.1.1 1.0.0.1",
                                  f"forward . 127.0.0.1:{public_port}")
        fixture = re.sub(r"(?m)^\s*health \{.*?^\s*\}\n", "", fixture, flags=re.S)
        fixture = re.sub(r"(?m)^\s*ready\n", "", fixture)
        path = temp / "Corefile"
        path.write_text(fixture)
        log_path = temp / "resolver.log"
        log = log_path.open("w")
        proc = subprocess.Popen([str(binary), "-conf", str(path)],
                                stdout=subprocess.DEVNULL, stderr=log, text=True)
        try:
            deadline = time.monotonic() + 8
            while True:
                if proc.poll() is not None:
                    log.flush()
                    raise AssertionError(f"resolver exited: {log_path.read_text()}")
                try:
                    response = query(dns_port, "affine.stinkyboi.com", "A")
                    if state == "ready" and SIDECAR_IP in response:
                        break
                    if state != "ready" and "status: NXDOMAIN" in response:
                        break
                except (AssertionError, subprocess.TimeoutExpired):
                    pass
                check(time.monotonic() < deadline, f"resolver did not sync for {state}")
                time.sleep(0.15)
            for name in ("stinkyboi.com", "affine.stinkyboi.com",
                         "AfFiNe.StInKyBoI.CoM",
                         "team.cordium.stinkyboi.com",
                         "agent-0123456789abcdef0123456789abcdef.agents.oce.stinkyboi.com"):
                for record_type in ("A", "AAAA"):
                    for tcp_query in (False, True):
                        response = query(dns_port, name, record_type, tcp=tcp_query)
                        check(PUBLIC_A not in response and PUBLIC_AAAA not in response,
                              f"private answer recursed for {state}: {name} {record_type}")
                        if state == "ready" and record_type == "A":
                            check(SIDECAR_IP in response, f"ready endpoint missing: {name}")
                        else:
                            check(SIDECAR_IP not in response, f"stale endpoint answered: {state} {name}")
            for name, record_type, answer in (
                    ("unrelated.stinkyboi.com", "A", PUBLIC_A),
                    ("unrelated.stinkyboi.com", "AAAA", PUBLIC_AAAA),
                    ("stinkyboi.com", "MX", "mail.example."),
                    ("stinkyboi.com", "TXT", '"public"')):
                for tcp_query in (False, True):
                    response = query(dns_port, name, record_type, tcp=tcp_query)
                    check(answer in response, f"public record lost: {state} {name} {record_type}")
        finally:
            proc.terminate()
            try:
                proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
            log.close()
            api.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolver-bin", required=True, type=Path,
                        help="binary built from k8s_gateway v1.9.0")
    args = parser.parse_args()
    check(args.resolver_bin.is_file(), "resolver binary is missing")
    hostnames = load_yaml(TRAEFIK_VALUES)["service"]["private"]["annotations"]["coredns.io/hostname"]
    private_samples = {"stinkyboi.com.", "affine.stinkyboi.com.",
                       "AfFiNe.StInKyBoI.CoM.",
                       "team.cordium.stinkyboi.com.",
                       "agent-0123456789abcdef0123456789abcdef.agents.oce.stinkyboi.com."}
    corefile = rendered_corefile()
    with socketserver.ThreadingUDPServer(("127.0.0.1", 0), PublicUDP) as udp:
        udp.seen = []
        tcp = socketserver.ThreadingTCPServer(("127.0.0.1", udp.server_address[1]), PublicTCP)
        tcp.seen = udp.seen
        threading.Thread(target=udp.serve_forever, daemon=True).start()
        threading.Thread(target=tcp.serve_forever, daemon=True).start()
        try:
            for state in ("ready", "unready", "empty", "absent-service"):
                before = len(udp.seen)
                test_state(state, args.resolver_bin, corefile, hostnames, udp.server_address[1])
                forwarded = udp.seen[before:]
                check(not any(name in private_samples and qtype in (1, 28)
                              for name, qtype in forwarded),
                      f"private query reached public forwarder for {state}: {forwarded}")
                print(f"{state}: approved A/AAAA and public A/AAAA/MX/TXT passed")
        finally:
            udp.shutdown()
            tcp.shutdown()
            tcp.server_close()


if __name__ == "__main__":
    main()
