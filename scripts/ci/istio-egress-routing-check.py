#!/usr/bin/env python3
"""Exercise pinned ambient waypoint routing inside the existing owned Kind fixture."""

import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.27.3"
CHARTS = {
    "base": "4b3069a8f68224a385725fb9c64b47282ff62eefdd306229258000f6f04fceb6",
    "istiod": "560adf601edaf0682a8126a6c54eafc2636878bf452a113d83f50b78230a1174",
    "cni": "fa60f8b5e80ee72c48ea72f2a0b63f9ed1b82fdffc57d1c59241bbbcba2b9f0a",
    "ztunnel": "6573f2645e87d5161ea5bc143c3ff9782dd392fd74b5f5e39326a05d81f174d1",
}
IMAGES = {
    "istiod": "docker.io/istio/pilot:1.27.3-distroless@sha256:70f4f8ccf75ba51187f0920b3f40a6517ba98c068b1b88399a342cbd5e31b857",
    "cni": "docker.io/istio/install-cni:1.27.3-distroless@sha256:cfe35258547be35aed2f3c94b56949d5460c0dd3810b94a16d3310c7e9337e62",
    "ztunnel": "docker.io/istio/ztunnel:1.27.3-distroless@sha256:3837029816e78cb6fc88d928dc5c6c58522ab9346772a1409b7f7da00d9de4ce",
}
PROXY = "1.27.3-distroless@sha256:0ff2299890e3e5b9fe0e38391b048c0788900f69af27306a7aef3036a59220e1"
API = "https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/40be951cebe5cb3f0365fe6951403de4ff8b9f33/config/crd/standard/"
HOST = "required.fixture.test"
SERVER = """import socket,socketserver
class Handler(socketserver.StreamRequestHandler):
 def handle(self):
  while self.rfile.readline(): self.wfile.write(b'fixture\\n'); self.wfile.flush()
class Server(socketserver.ThreadingTCPServer):
 address_family=socket.AF_INET6
 allow_reuse_address=True
 def server_bind(self):
  self.socket.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
  super().server_bind()
Server(('::',8080),Handler).serve_forever()
"""
PROBE = """import socket,sys
try:
 with socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=3) as s:
  s.sendall(b'fixture\\n'); assert s.recv(128)==b'fixture\\n'
except (OSError,AssertionError): sys.exit(7)
print('ALLOWED')
"""


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=240, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout


def wait(check):
    deadline = time.monotonic() + 120
    while not check():
        if time.monotonic() >= deadline:
            raise AssertionError("Ambient routing fixture did not converge")
        time.sleep(2)


def check(kubectl, root, python):
    assert "--kubeconfig" in kubectl, "Explicit disposable kubeconfig required"
    assert run(*kubectl, "config", "current-context").strip() == "kind-network-policy-check"
    nodes = json.loads(run(*kubectl, "get", "nodes", "-o", "json"))["items"]
    assert {n["metadata"]["name"] for n in nodes} == {"network-policy-check-control-plane", "network-policy-check-worker"}

    def apply(obj):
        run(*kubectl, "apply", "-f", "-", input=json.dumps(obj))

    for name in ("gatewayclasses", "gateways", "grpcroutes", "httproutes", "referencegrants"):
        run(*kubectl, "apply", "--server-side", "-f", API + "gateway.networking.k8s.io_" + name + ".yaml")
    apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "istio-system"}})
    for chart, digest in CHARTS.items():
        archive = root / (chart + ".tgz")
        data = urllib.request.urlopen("https://istio-release.storage.googleapis.com/charts/" + chart + "-" + VERSION + ".tgz", timeout=30).read()
        assert hashlib.sha256(data).hexdigest() == digest, "Istio chart bytes changed"
        archive.write_bytes(data)
        values = {"profile": "ambient"}
        if chart in IMAGES:
            values["image"] = IMAGES[chart]
        if chart == "istiod":
            values["global"] = {"hub": "docker.io/istio", "tag": PROXY, "variant": ""}
        if chart == "cni":
            values["cni"] = {"ambient": {"enabled": True, "dnsCapture": True, "ipv6": True}}
        if chart == "ztunnel":
            values["env"] = {"IPV6_ENABLED": "true"}
        file = root / (chart + "-values.json")
        file.write_text(json.dumps(values))
        release = {"base": "istio-base", "istiod": "istiod", "cni": "istio-cni", "ztunnel": "ztunnel"}[chart]
        rendered = run("helm", "template", release, str(archive), "--namespace", "istio-system", "--values", str(file))
        objects = json.loads(run("yq", "ea", "-o=json", "-I=0", "[.]", "-", input=rendered))
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            pod_spec = (obj.get("spec") or {}).get("template", {}).get("spec", {})
            for container in pod_spec.get("containers", []) + pod_spec.get("initContainers", []):
                assert container["image"] in IMAGES.values(), "Unexpected unpinned Istio component image"
        run(*kubectl, "apply", "-f", "-", input=rendered)
        if chart == "istiod":
            run(*kubectl, "-n", "istio-system", "rollout", "status", "deployment/istiod", "--timeout=180s")
        if chart in ("cni", "ztunnel"):
            run(*kubectl, "-n", "istio-system", "rollout", "status", "daemonset/" + ("istio-cni-node" if chart == "cni" else "ztunnel"), "--timeout=180s")
    for name, ambient in (("egress-clients", True), ("egress-gateway", True), ("egress-target", False)):
        labels = {"istio.io/dataplane-mode": "ambient"} if ambient else {}
        apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name, "labels": labels}})
    for account in ("required-client", "unauthorized-client"):
        apply({"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": account, "namespace": "egress-clients"}, "automountServiceAccountToken": False})

    def pod(namespace, name, account=None, server=False):
        spec = {"automountServiceAccountToken": False,
                "nodeName": "network-policy-check-" + ("control-plane" if server else "worker"),
                "securityContext": {"runAsUser": 65532, "runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [{"name": "fixture", "image": python,
                                "command": ["/usr/bin/python3", "-u", "-c", SERVER if server else "import time; time.sleep(86400)"],
                                "securityContext": {"readOnlyRootFilesystem": True, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}}}]}
        if account:
            spec["serviceAccountName"] = account
        apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": namespace, "labels": {"app": "fixture"}}, "spec": spec})
        run(*kubectl, "-n", namespace, "wait", "--for=condition=Ready", "pod/" + name, "--timeout=120s")
        return json.loads(run(*kubectl, "-n", namespace, "get", "pod", name, "-o", "json"))["status"]["podIP"]

    target = pod("egress-target", "server", server=True)
    target_addresses = json.loads(run(*kubectl, "-n", "egress-target", "get", "pod", "server", "-o", "json"))["status"]["podIPs"]
    target_v6 = [a["ip"] for a in target_addresses if ipaddress.ip_address(a["ip"]).version == 6]
    assert len(target_v6) == 1, "Dual-stack target must have one IPv6 address"
    pod("egress-clients", "required", "required-client")
    pod("egress-clients", "unauthorized", "unauthorized-client")
    gateway = {"apiVersion": "gateway.networking.k8s.io/v1", "kind": "Gateway", "metadata": {"name": "required-egress", "namespace": "egress-gateway", "labels": {"istio.io/waypoint-for": "service"}}, "spec": {"gatewayClassName": "istio-waypoint", "listeners": [{"name": "mesh", "port": 15008, "protocol": "HBONE"}]}}
    apply(gateway)
    run(*kubectl, "-n", "egress-gateway", "wait", "--for=condition=Programmed", "gateway/required-egress", "--timeout=120s")
    gateway_pods = json.loads(run(*kubectl, "-n", "egress-gateway", "get", "pods", "-l", "gateway.networking.k8s.io/gateway-name=required-egress", "-o", "json"))["items"]
    assert gateway_pods and all(c["image"] == "docker.io/istio/proxyv2:" + PROXY for p in gateway_pods for c in p["spec"]["containers"]), "Generated waypoint image must match its reviewed digest"
    entry = {"apiVersion": "networking.istio.io/v1", "kind": "ServiceEntry", "metadata": {"name": "required", "namespace": "egress-gateway", "labels": {"istio.io/use-waypoint": "required-egress"}}, "spec": {"hosts": [HOST], "location": "MESH_EXTERNAL", "resolution": "STATIC", "ports": [{"name": "tcp", "number": 80, "protocol": "TCP", "targetPort": 8080}], "endpoints": [{"address": target}]}}
    apply(entry)
    addresses = []

    def allocated():
        obj = json.loads(run(*kubectl, "-n", "egress-gateway", "get", "serviceentry", "required", "-o", "json"))
        addresses[:] = [a["value"] for a in obj.get("status", {}).get("addresses", []) if a.get("host") == HOST and ipaddress.ip_address(a["value"]).version == 4]
        return len(addresses) == 1

    wait(allocated)
    vip = addresses[0]
    assert ipaddress.ip_address(vip) in ipaddress.ip_network("240.240.0.0/16")
    resolved = run(*kubectl, "-n", "egress-clients", "exec", "required", "--", "/usr/bin/python3", "-c", "import socket; print(socket.gethostbyname('" + HOST + "'))").strip()
    assert resolved == vip, "Captured DNS must resolve the exact allocated service address"

    def probe(client, address, port):
        return subprocess.run([*kubectl, "-n", "egress-clients", "exec", client, "--", "/usr/bin/python3", "-c", PROBE, address, str(port)], capture_output=True, text=True, timeout=30).returncode

    wait(lambda: probe("required", HOST, 80) == 0 and probe("unauthorized", HOST, 80) == 0)
    auth = {"apiVersion": "security.istio.io/v1", "kind": "AuthorizationPolicy", "metadata": {"name": "required-client", "namespace": "egress-gateway"}, "spec": {"targetRefs": [{"group": "gateway.networking.k8s.io", "kind": "Gateway", "name": "required-egress"}], "action": "ALLOW", "rules": [{"from": [{"source": {"principals": ["cluster.local/ns/egress-clients/sa/required-client"]}}]}]}}
    apply(auth)
    wait(lambda: probe("required", HOST, 80) == 0 and probe("unauthorized", HOST, 80) == 7)
    print("Captured service DNS traverses a waypoint enforcing the caller principal", flush=True)
    assert probe("required", target, 8080) == 0, "Direct-IP baseline must succeed before network isolation"
    assert probe("required", target_v6[0], 8080) == 0, "IPv6 direct-IP baseline must succeed before network isolation"
    policy = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "required-only", "namespace": "egress-clients"}, "spec": {"podSelector": {}, "policyTypes": ["Egress"], "egress": [
        {"to": [{"ipBlock": {"cidr": vip + "/32"}}], "ports": [{"protocol": "TCP", "port": 80}]},
        {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "egress-gateway"}}, "podSelector": {"matchLabels": {"gateway.networking.k8s.io/gateway-name": "required-egress"}}}], "ports": [{"protocol": "TCP", "port": 15008}]},
        {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}, "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}], "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]},
    ]}}
    apply(policy)
    wait(lambda: probe("required", HOST, 80) == 0 and probe("required", target, 8080) == 7 and probe("required", target_v6[0], 8080) == 7)
    assert probe("required", vip, 81) == 7, "Alternate service port bypassed egress restriction"
    assert probe("unauthorized", HOST, 80) == 7, "Network policy bypassed waypoint caller authorization"
    print("Pinned ambient routing plus enforced policy permits required TCP and denies IPv4/IPv6 real-IP and alternate-port bypass; TLS/SNI/DNS leakage and required IPv6 routing remain separate", flush=True)
