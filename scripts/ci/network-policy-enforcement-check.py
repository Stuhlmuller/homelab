#!/usr/bin/env python3
"""Prove policy enforcement in disposable Kind; never load homelab credentials."""

import json
import select
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLUSTER = "network-policy-check"
NODE = "kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a"
# Upstream's transport-only test CNI; production keeps its supported Flannel.
CNI = "docker.io/kindest/kindnetd:v20230809-80a64d96@sha256:4a58d1cd2b45bf2460762a51a4aa9c80861f460af35800c05baab0573f923052"
PYTHON = "cgr.dev/chainguard/python:latest@sha256:197cf542e9f4dc373864faecd4fd1a4f642622e654e9196881ca852e8fdf26bd"
SERVER = """import socket,socketserver,threading,time
class TCP(socketserver.StreamRequestHandler):
 def handle(self):
  while self.rfile.readline(): self.wfile.write(b'fixture\\n'); self.wfile.flush()
class UDP(socketserver.BaseRequestHandler):
 def handle(self): self.request[1].sendto(b'fixture',self.client_address)
class TCPServer(socketserver.ThreadingTCPServer): address_family=socket.AF_INET6; allow_reuse_address=True
class UDPServer(socketserver.ThreadingUDPServer): address_family=socket.AF_INET6
for server in (TCPServer(('::',8080),TCP),TCPServer(('::',9090),TCP),UDPServer(('::',8080),UDP)):
 threading.Thread(target=server.serve_forever,daemon=True).start()
time.sleep(86400)
"""
PROBE = """import socket,sys
address,port,protocol=sys.argv[1],int(sys.argv[2]),sys.argv[3]
try:
 if protocol=='TCP':
  with socket.create_connection((address,port),timeout=2) as s:
   s.sendall(b'fixture\\n'); assert s.recv(128)==b'fixture\\n'
 else:
  with socket.socket(socket.AF_INET6 if ':' in address else socket.AF_INET,socket.SOCK_DGRAM) as s:
   s.settimeout(2); s.sendto(b'fixture',(address,port)); assert s.recv(128)==b'fixture'
except OSError: sys.exit(7)
print('ALLOWED')
"""
HELD = """import socket,sys
with socket.create_connection((sys.argv[1],8080),timeout=2) as s:
 s.sendall(b'fixture\\n'); assert s.recv(128)==b'fixture\\n'
 print('READY',flush=True); sys.stdin.readline()
 try:
  s.sendall(b'fixture\\n'); response=s.recv(128)
 except OSError: response=b''
 assert response!=b'fixture\\n', 'Established connection bypassed revocation'
 print('BLOCKED',flush=True)
"""
FIRST_PACKET = """import socket,sys
for address,allowed in zip(sys.argv[1:],(True,False)):
 try:
  with socket.create_connection((address,8080),timeout=2) as s:
   s.sendall(b'fixture\\n'); assert s.recv(128)==b'fixture\\n'
 except OSError: assert not allowed, 'Required init-container request was dropped'
 else: assert allowed, 'Init-container bypassed egress denial'
"""


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout


def main():
    run("docker", "info")
    assert CLUSTER not in run("kind", "get", "clusters").splitlines(), "Refusing to reuse an existing cluster"
    with tempfile.TemporaryDirectory(prefix="network-policy-check-") as directory:
        root = Path(directory)
        config, kubeconfig = root / "kind.json", root / "kubeconfig"
        config.write_text(json.dumps({"kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4",
                                     "networking": {"ipFamily": "dual"},
                                     "containerdConfigPatches": ['[plugins."io.containerd.nri.v1.nri"]\n disable = false\n'],
                                     "nodes": [{"role": "control-plane"}, {"role": "worker"}]}))
        kubectl = ["kubectl", "--kubeconfig", str(kubeconfig), "--request-timeout=20s"]
        try:
            run("kind", "create", "cluster", "--name", CLUSTER, "--image", NODE, "--config", str(config),
                "--kubeconfig", str(kubeconfig), "--wait", "120s")
            kubeconfig.chmod(0o600)
            cni = json.loads(run(*kubectl, "-n", "kube-system", "get", "daemonset", "kindnet", "-o", "json"))
            for key in ("status",):
                cni.pop(key, None)
            for key in ("managedFields", "resourceVersion", "uid", "creationTimestamp"):
                cni["metadata"].pop(key, None)
            cni["spec"]["template"]["spec"]["containers"][0]["image"] = CNI
            run(*kubectl, "apply", "-f", "-", input=json.dumps(cni))
            run(*kubectl, "-n", "kube-system", "rollout", "status", "daemonset/kindnet", "--timeout=120s")
            for namespace in ("clients", "allowed", "blocked"):
                run(*kubectl, "create", "namespace", namespace)

            def pod(namespace, name, node, server=False, first_packet=None):
                obj = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": namespace, "labels": {"app": "web" if server else "client"}},
                       "spec": {"nodeName": CLUSTER + "-" + node, "automountServiceAccountToken": False,
                                "securityContext": {"runAsUser": 65532, "runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                                "containers": [{"name": "fixture", "image": PYTHON,
                                                "command": ["/usr/bin/python3", "-u", "-c", SERVER if server else "import time; time.sleep(86400)"],
                                                "securityContext": {"readOnlyRootFilesystem": True, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}}}]}}
                if first_packet:
                    init = dict(obj["spec"]["containers"][0])
                    init["name"] = "first-packet"
                    init["command"] = ["/usr/bin/python3", "-c", FIRST_PACKET, *first_packet]
                    obj["spec"]["initContainers"] = [init]
                run(*kubectl, "apply", "-f", "-", input=json.dumps(obj))
                run(*kubectl, "-n", namespace, "wait", "--for=condition=Ready", "pod/" + name, "--timeout=120s")
                result = json.loads(run(*kubectl, "-n", namespace, "get", "pod", name, "-o", "json"))
                return [ip["ip"] for ip in result["status"]["podIPs"]]

            targets = {ns: pod(ns, "web", "control-plane", True) for ns in ("allowed", "blocked")}
            assert all(len(ips) == 2 for ips in targets.values()), "Fixture must exercise IPv4 and IPv6"
            pod("clients", "client", "worker")
            svc = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "web", "namespace": "allowed"},
                   "spec": {"selector": {"app": "web"}, "ipFamilyPolicy": "RequireDualStack", "ports": [{"port": 80, "targetPort": 8080}]}}
            run(*kubectl, "apply", "-f", "-", input=json.dumps(svc))
            policy = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "required-only", "namespace": "clients"},
                      "spec": {"podSelector": {"matchLabels": {"app": "client"}}, "policyTypes": ["Egress"], "egress": [
                          {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "allowed"}}, "podSelector": {"matchLabels": {"app": "web"}}}],
                           "ports": [{"protocol": "TCP", "port": 8080}]},
                          {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}, "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
                           "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}]}}
            run(*kubectl, "apply", "-f", "-", input=json.dumps(policy))

            def probe(address, port=8080, protocol="TCP", client="client"):
                return subprocess.run([*kubectl, "-n", "clients", "exec", client, "--", "/usr/bin/python3", "-c", PROBE, address, str(port), protocol],
                                      capture_output=True, text=True, timeout=30)

            for ips in targets.values():
                for address in ips:
                    for port, protocol in ((8080, "TCP"), (9090, "TCP"), (8080, "UDP")):
                        result = probe(address, port, protocol)
                        assert result.returncode == 0, "Baseline is not unrestricted: " + result.stderr
            print("Policies alone do not enforce the fixture transport", flush=True)
            run(*kubectl, "apply", "-f", str(ROOT / "scripts/ci/fixtures/network-policy-enforcer.yaml"))
            run(*kubectl, "-n", "kube-system", "rollout", "status", "daemonset/kube-network-policies", "--timeout=120s")
            agents = json.loads(run(*kubectl, "-n", "kube-system", "get", "pods", "-l", "app=kube-network-policies", "-o", "json"))["items"]
            assert len(agents) == 2 and len({p["spec"]["nodeName"] for p in agents}) == 2
            deadline = time.monotonic() + 60
            while True:
                logs = [run(*kubectl, "-n", "kube-system", "logs", p["metadata"]["name"], "--tail=200") for p in agents]
                result = probe(targets["blocked"][0])
                if all("Synchronized state with the runtime" in log for log in logs) and result.returncode == 7:
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("NRI registration and enforcement did not converge: " + "\n".join(logs))
                time.sleep(1)
            count = 0
            for namespace, ips in targets.items():
                for address in ips:
                    for port, protocol in ((8080, "TCP"), (9090, "TCP"), (8080, "UDP")):
                        result = probe(address, port, protocol)
                        allowed = namespace == "allowed" and port == 8080 and protocol == "TCP"
                        assert result.returncode == (0 if allowed else 7), (namespace, address, port, protocol, result.stdout, result.stderr)
                        count += 1
            services = json.loads(run(*kubectl, "-n", "allowed", "get", "service", "web", "-o", "json"))["spec"]["clusterIPs"]
            for address in services:
                assert probe(address, 80).returncode == 0, "Service DNAT must preserve allowed access"
            run(*kubectl, "-n", "clients", "exec", "client", "--", "/usr/bin/python3", "-c",
                "import socket; assert socket.getaddrinfo('web.allowed.svc.cluster.local',80)")
            pod("clients", "fresh", "worker", first_packet=[targets["allowed"][0], targets["blocked"][0]])
            fresh = json.loads(run(*kubectl, "-n", "clients", "get", "pod", "fresh", "-o", "json"))
            assert fresh["status"]["phase"] == "Running"
            for namespace, ips in targets.items():
                for address in ips:
                    assert probe(address, client="fresh").returncode == (0 if namespace == "allowed" else 7)
            held = subprocess.Popen([*kubectl, "-n", "clients", "exec", "-i", "client", "--", "/usr/bin/python3", "-u", "-c", HELD, targets["allowed"][0]],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                assert select.select([held.stdout], [], [], 20)[0], "Held connection did not start"
                assert held.stdout.readline().strip() == "READY", "Held connection was not established"
                policy["spec"]["egress"].pop(0)
                run(*kubectl, "apply", "-f", "-", input=json.dumps(policy))
                deadline = time.monotonic() + 30
                while probe(targets["allowed"][0]).returncode != 7:
                    if time.monotonic() >= deadline:
                        raise AssertionError("Revoked allow rule did not converge")
                    time.sleep(1)
                stdout, stderr = held.communicate("\n", timeout=10)
                assert held.returncode == 0 and stdout.strip() == "BLOCKED", (stdout, stderr)
            finally:
                if held.poll() is None:
                    held.kill()
                    held.communicate(timeout=10)
            print(f"Passed {count} dual-stack destination/port/protocol checks, Service/DNS access, first-packet isolation and established-connection revocation", flush=True)
        finally:
            run("kind", "delete", "cluster", "--name", CLUSTER)


if __name__ == "__main__":
    main()
