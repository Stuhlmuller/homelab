#!/usr/bin/env python3
"""Probe the admitted policy canary; lifecycle evidence is checked separately."""

import argparse
import ipaddress
import json
import os
import runpy
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "network-policy-canary"
CANARY_KEY = "homelab.stinkyboi.com/network-policy-canary"
FIXTURE_NODE = "zimaboard-1"
HOSTNAME_LABEL = "kubernetes.io/hostname"
IMAGE = "harbor.stinkyboi.com/mirror/cgr.dev/chainguard/python:1c4deeea85db49ab5f6bcd9e7fc0bf3fd8439e99f7bde45330f40400685eb394@sha256:1c4deeea85db49ab5f6bcd9e7fc0bf3fd8439e99f7bde45330f40400685eb394"
SERVER_CODE = """import socket, threading, time
def serve_tcp(port):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('0.0.0.0', port))
        listener.listen()
        while True:
            connection, _ = listener.accept()
            with connection:
                connection.sendall(b'npq-ok')
def serve_udp():
    with socket.socket(type=socket.SOCK_DGRAM) as listener:
        listener.bind(('0.0.0.0', 8080))
        while True:
            _, address = listener.recvfrom(32)
            listener.sendto(b'npq-ok', address)
for port in (8080, 9090):
    threading.Thread(target=serve_tcp, args=(port,), daemon=True).start()
threading.Thread(target=serve_udp, daemon=True).start()
time.sleep(86400)
"""
FIXTURE_COMMANDS = {
    "client": ["/usr/bin/python3", "-c", "import time; time.sleep(86400)"],
    "allowed": ["/usr/bin/python3", "-u", "-c", SERVER_CODE],
    "denied": ["/usr/bin/python3", "-u", "-c", SERVER_CODE],
}
FIXTURE_SECURITY = {
    "allowPrivilegeEscalation": False,
    "readOnlyRootFilesystem": True,
    "capabilities": {"drop": ["ALL"]},
}
FIXTURE_RESOURCES = {"requests": {"cpu": "10m", "memory": "32Mi"},
                     "limits": {"cpu": "100m", "memory": "64Mi"}}
SERVER_PORTS = [{"name": "fixture-tcp", "containerPort": 8080, "protocol": "TCP"},
                {"name": "fixture-udp", "containerPort": 8080, "protocol": "UDP"},
                {"name": "alternate-tcp", "containerPort": 9090, "protocol": "TCP"}]
SERVER_PROBE = {"tcpSocket": {"port": "fixture-tcp"}}
FIREWALL_IMAGE = "harbor.stinkyboi.com/mirror/docker.io/cloudnativelabs/kube-router:64da9a538d29e13780e256ce3897a52932a68657793bef009063bbeb2762146a@sha256:64da9a538d29e13780e256ce3897a52932a68657793bef009063bbeb2762146a"
FIREWALL_FLAGS = {
    "--run-router=false", "--run-service-proxy=false", "--run-loadbalancer=false",
    "--run-firewall=true", "--enable-cni=false", "--netpol-default-deny=true",
    "--use-nftables-for-netpol=false", "--enable-ipv4=true", "--enable-ipv6=false",
    "--health-addr=127.0.0.1",
}
LIFECYCLE_SCENARIOS = (
    "cold-bootstrap", "first-application-packet", "enforcer-graceful-stop",
    "enforcer-crash-restart", "api-loss", "policy-change-and-conntrack",
    "pod-reschedule-and-ip-reuse", "cold-node-reboot", "ipv6-absence",
)
PROBE = """import socket,sys
address,port,protocol=sys.argv[1],int(sys.argv[2]),sys.argv[3]
try:
 if protocol=='TCP':
  with socket.create_connection((address,port),timeout=3) as connection:
   data=connection.recv(32)
 else:
  with socket.socket(type=socket.SOCK_DGRAM) as connection:
   connection.settimeout(3); connection.sendto(b'npq',(address,port))
   data=connection.recv(32)
except OSError:
 print('NPQ_DENIED')
 sys.exit(7)
if data!=b'npq-ok': sys.exit(8)
print('NPQ_ALLOWED')
"""
DNS_PROBE = """import os,socket,struct,sys
address,protocol,expected,port=sys.argv[1:]
port=int(port)
name=b''.join(bytes([len(part)])+part.encode() for part in 'kubernetes.default.svc.cluster.local'.split('.'))+b'\\0'
question=name+b'\\0\\x01\\0\\x01'
query=os.urandom(2)+b'\\x01\\0\\0\\x01\\0\\0\\0\\0\\0\\0'+question
def receive(connection,count):
 data=b''
 while len(data)<count:
  part=connection.recv(count-len(data))
  if not part: raise OSError('short DNS reply')
  data+=part
 return data
try:
 kind=socket.SOCK_STREAM if protocol=='TCP' else socket.SOCK_DGRAM
 with socket.socket(socket.AF_INET,kind) as connection:
  connection.settimeout(3)
  if kind==socket.SOCK_STREAM:
   connection.connect((address,port))
   connection.sendall(struct.pack('!H',len(query))+query)
   reply=receive(connection,struct.unpack('!H',receive(connection,2))[0])
  else:
   connection.sendto(query,(address,port))
   reply,source=connection.recvfrom(4096)
except OSError: sys.exit(7)
if protocol=='UDP' and source!=(address,port): sys.exit(8)
if (len(reply)<12+len(question) or reply[:2]!=query[:2] or
    not reply[2]&0x80 or reply[2]&0x02 or reply[3]&0x0f or
    int.from_bytes(reply[4:6],'big')!=1 or
    not int.from_bytes(reply[6:8],'big') or
    reply[12:12+len(question)]!=question): sys.exit(8)
offset=12+len(question)
found=False
for _ in range(int.from_bytes(reply[6:8],'big')):
 if reply[offset:offset+2]==b'\\xc0\\x0c': offset+=2
 elif reply[offset:offset+len(name)]==name: offset+=len(name)
 else: sys.exit(8)
 if len(reply)<offset+10: sys.exit(8)
 kind,record_class,_,length=struct.unpack('!HHIH',reply[offset:offset+10])
 offset+=10
 if len(reply)<offset+length: sys.exit(8)
 if kind==1 and record_class==1 and length==4 and reply[offset:offset+4]==socket.inet_aton(expected): found=True
 offset+=length
if not found: sys.exit(8)
print('NPQ_DNS_ALLOWED')
"""
CASES = (
    ("npq-allowed", "npq-denied", 8080, "TCP", True),
    ("npq-allowed", "npq-denied", 8080, "UDP", True),
    ("npq-denied", "npq-allowed", 9090, "TCP", True),
    ("npq-client", "npq-allowed", 8080, "TCP", True),
    ("npq-client", "npq-allowed", 8080, "UDP", True),
    ("npq-client", "npq-denied", 8080, "TCP", False),
    ("npq-client", "npq-denied", 8080, "UDP", False),
    ("npq-client", "npq-allowed", 9090, "TCP", False),
    ("npq-allowed", "npq-denied", 8080, "TCP", True),
    ("npq-allowed", "npq-denied", 8080, "UDP", True),
    ("npq-denied", "npq-allowed", 9090, "TCP", True),
)
EXPECTED_POLICY = {
    "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
    "metadata": {"name": "npq-client-egress", "namespace": NAMESPACE},
    "spec": {"podSelector": {"matchLabels": {"role": "client"}},
             "policyTypes": ["Egress"],
             "egress": [
                 {"to": [{"podSelector": {"matchLabels": {"role": "allowed"}}}],
                  "ports": [{"protocol": "TCP", "port": 8080},
                            {"protocol": "UDP", "port": 8080}]},
                 {"to": [{"namespaceSelector": {"matchLabels": {
                     "kubernetes.io/metadata.name": "kube-system"}},
                     "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
                  "ports": [{"protocol": "TCP", "port": 53},
                            {"protocol": "UDP", "port": 53}]},
             ]},
}


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=25, check=True)
    return result.stdout


def kubernetes_json(*args):
    return json.loads(command("kubectl", "--request-timeout=15s", *args, "-o", "json"))


def ready(pod):
    return (pod.get("status", {}).get("phase") == "Running" and
            any(item.get("type") == "Ready" and item.get("status") == "True"
                for item in pod.get("status", {}).get("conditions", [])))


def require_protected_source():
    source_sha = os.environ.get("GITHUB_SHA", "")
    platform = runpy.run_path(str(ROOT / "scripts/platform-maintenance.py"))
    platform["protected_context"](source_sha)
    if (command("git", "-C", str(ROOT), "rev-parse", "HEAD").strip() != source_sha or
            platform["current_main_sha"]() != source_sha):
        raise ValueError("qualification source is not exact current main")
    return source_sha


def inspect_firewall_source():
    name = "kube-router-network-policy"
    service_account = kubernetes_json("-n", "kube-system", "get", "serviceaccount", name)
    role = kubernetes_json("get", "clusterrole", name)
    binding = kubernetes_json("get", "clusterrolebinding", name)
    daemonset = kubernetes_json("-n", "kube-system", "get", "daemonset", name)
    rules = {(tuple(rule.get("apiGroups", [])), tuple(rule.get("resources", [])),
              tuple(rule.get("verbs", []))) for rule in role.get("rules", [])}
    expected_rules = {
        (("",), ("namespaces", "pods", "services", "nodes", "endpoints"),
         ("get", "list", "watch")),
        (("networking.k8s.io",), ("networkpolicies",), ("get", "list", "watch")),
        (("discovery.k8s.io",), ("endpointslices",), ("get", "list", "watch")),
        (("coordination.k8s.io",), ("leases",), ("get", "create", "update")),
    }
    subjects = binding.get("subjects", [])
    if (service_account.get("metadata", {}).get("name") != name or
            service_account["metadata"].get("namespace") != "kube-system" or
            role.get("metadata", {}).get("name") != name or
            len(role.get("rules", [])) != len(expected_rules) or rules != expected_rules or
            binding.get("metadata", {}).get("name") != name or
            binding.get("roleRef") != {"apiGroup": "rbac.authorization.k8s.io",
                                       "kind": "ClusterRole", "name": name} or
            len(subjects) != 1 or subjects[0].get("kind") != "ServiceAccount" or
            subjects[0].get("name") != name or
            subjects[0].get("namespace") != "kube-system" or
            subjects[0].get("apiGroup") not in (None, "")):
        raise ValueError("firewall service account or RBAC differs from reviewed source")
    template = daemonset["spec"]["template"]["spec"]
    containers = template.get("containers", [])
    if len(containers) != 1:
        raise ValueError("firewall container count differs from reviewed source")
    container, = containers
    args = container.get("args", [])
    environment = container.get("env", [])
    fields = {item.get("name"): item.get("valueFrom", {}).get("fieldRef", {}).get("fieldPath")
              for item in environment}
    if (daemonset.get("metadata", {}).get("name") != name or
            daemonset["metadata"].get("namespace") != "kube-system" or
            daemonset["spec"].get("selector", {}).get("matchLabels") !=
            {"app.kubernetes.io/name": name} or
            template.get("serviceAccountName") != name or
            template.get("hostNetwork") is not True or
            template.get("dnsPolicy") != "ClusterFirstWithHostNet" or
            template.get("priorityClassName") != "system-node-critical" or
            template.get("hostPID") is True or template.get("hostIPC") is True or
            template.get("initContainers") or
            template.get("nodeSelector") != {CANARY_KEY: "true"} or
            template.get("tolerations") != [{"key": CANARY_KEY, "operator": "Equal",
                                            "value": "true", "effect": "NoSchedule"}] or
            template.get("volumes") != [{"name": "xtables-lock", "hostPath": {
                "path": "/run/xtables.lock", "type": "FileOrCreate"}}] or
            container.get("volumeMounts") != [{"name": "xtables-lock",
                                               "mountPath": "/run/xtables.lock"}] or
            container.get("image") != FIREWALL_IMAGE or
            container.get("command") or
            len(environment) != 2 or fields != {"NODE_NAME": "spec.nodeName",
                                                 "POD_NAME": "metadata.name"} or
            len(args) != len(FIREWALL_FLAGS) or set(args) != FIREWALL_FLAGS or
            container.get("securityContext", {}).get("privileged") is not True or
            container.get("livenessProbe", {}).get("httpGet", {}).get("host") !=
            "127.0.0.1" or
            container.get("readinessProbe", {}).get("httpGet", {}).get("host") !=
            "127.0.0.1"):
        raise ValueError("live firewall DaemonSet differs from firewall-only source")
    return daemonset


def inspect(config, require_firewall=True):
    canary = config.get("canary", {})
    node_name = canary.get("node")
    if (config.get("activationEnabled") is not True or
            node_name not in config.get("nodeOrder", [])[:-1]):
        raise ValueError("no admitted worker canary")
    node = kubernetes_json("get", "node", node_name)
    labels = node["metadata"].get("labels", {})
    taints = node["spec"].get("taints", [])
    if (labels.get(CANARY_KEY) != "true" or
            not any(taint.get("key") == CANARY_KEY and taint.get("value") == "true" and
                    taint.get("effect") == "NoSchedule" for taint in taints) or
            not any(item.get("type") == "Ready" and item.get("status") == "True"
                    for item in node["status"]["conditions"])):
        raise ValueError("canary label, taint, or node readiness differs")
    server_node = kubernetes_json("get", "node", FIXTURE_NODE)
    server_meta = server_node.get("metadata", {})
    server_spec = server_node.get("spec", {})
    server_status = server_node.get("status", {})
    if (server_meta.get("name") != FIXTURE_NODE or
            not server_meta.get("uid") or server_meta.get("deletionTimestamp") or
            server_meta.get("labels", {}).get(HOSTNAME_LABEL) != FIXTURE_NODE or
            server_meta.get("labels", {}).get(CANARY_KEY) == "true" or
            not server_status.get("nodeInfo", {}).get("bootID") or
            server_spec.get("unschedulable") is True or
            any(item.get("effect") in {"NoSchedule", "NoExecute"}
                for item in server_spec.get("taints", [])) or
            not any(item.get("type") == "Ready" and item.get("status") == "True"
                    for item in server_status.get("conditions", []))):
        raise ValueError("fixture Node identity, readiness, or scheduling differs")
    namespace = kubernetes_json("get", "namespace", NAMESPACE)
    namespace_labels = namespace["metadata"].get("labels", {})
    if (namespace_labels.get("pod-security.kubernetes.io/enforce") != "restricted" or
            namespace_labels.get("istio.io/dataplane-mode") == "ambient"):
        raise ValueError("canary namespace security boundary differs")
    fixture_pods = kubernetes_json("-n", NAMESPACE, "get", "pods").get("items", [])
    if {pod.get("metadata", {}).get("name") for pod in fixture_pods} != {
            "npq-client", "npq-allowed", "npq-denied"} or len(fixture_pods) != 3:
        raise ValueError("canary namespace contains foreign or missing Pods")
    pods = {}
    def reviewed_server_probe(probe):
        if not isinstance(probe, dict):
            return False
        defaults = {"initialDelaySeconds": 0, "periodSeconds": 10,
                    "timeoutSeconds": 1, "successThreshold": 1,
                    "failureThreshold": 3}
        return (probe.get("tcpSocket") == SERVER_PROBE["tcpSocket"] and
                set(probe) <= {"tcpSocket", *defaults} and
                all(probe.get(key, value) == value for key, value in defaults.items()))
    for name, role in (("npq-client", "client"), ("npq-allowed", "allowed"),
                       ("npq-denied", "denied")):
        pod = kubernetes_json("-n", NAMESPACE, "get", "pod", name)
        spec = pod["spec"]
        containers = spec.get("containers", [])
        container = (containers[0] if isinstance(containers, list) and
                     len(containers) == 1 and isinstance(containers[0], dict) else {})
        expected_node = node_name if role == "client" else FIXTURE_NODE
        expected_selector = ({CANARY_KEY: "true"} if role == "client" else
                             {HOSTNAME_LABEL: FIXTURE_NODE})
        tolerations = spec.get("tolerations", [])
        if role == "client":
            placement_tolerations_valid = any(
                item.get("key") == CANARY_KEY and item.get("operator") == "Equal" and
                item.get("value") == "true" and item.get("effect") == "NoSchedule"
                for item in tolerations)
        else:
            # Kubernetes injects these transient and Burstable-Pod tolerations.
            placement_tolerations_valid = all(
                (item.get("key") in {"node.kubernetes.io/not-ready",
                                     "node.kubernetes.io/unreachable"} and
                 item.get("operator") == "Exists" and
                 item.get("effect") == "NoExecute" and
                 item.get("tolerationSeconds") == 300) or
                (item.get("key") == "node.kubernetes.io/memory-pressure" and
                 item.get("operator") == "Exists" and
                 item.get("effect") == "NoSchedule" and
                 "tolerationSeconds" not in item)
                for item in tolerations)
        statuses = pod["status"].get("containerStatuses", [])
        image_status_valid = (
            len(statuses) == 1 and statuses[0].get("name") ==
            ("probe" if role == "client" else "server") and
            isinstance(statuses[0].get("containerID"), str) and
            bool(statuses[0]["containerID"]) and
            isinstance(statuses[0].get("imageID"), str) and
            bool(statuses[0]["imageID"]))
        reviewed_ports = [] if role == "client" else SERVER_PORTS
        probes_valid = (
            container.get("readinessProbe") in (None, {}) and
            container.get("livenessProbe") in (None, {})
            if role == "client" else
            reviewed_server_probe(container.get("readinessProbe")) and
            reviewed_server_probe(container.get("livenessProbe")))
        if (not ready(pod) or spec.get("nodeName") != expected_node or
                pod["metadata"].get("deletionTimestamp") or
                pod["metadata"].get("ownerReferences") or
                pod["metadata"].get("labels", {}).get("role") != role or
                spec.get("nodeSelector") != expected_selector or
                not placement_tolerations_valid or
                spec.get("automountServiceAccountToken") is not False or
                spec.get("hostNetwork") is True or spec.get("hostPID") is True or
                spec.get("hostIPC") is True or spec.get("volumes") or
                spec.get("initContainers") or spec.get("ephemeralContainers") or
                spec.get("securityContext") != {"runAsUser": 65532,
                                                "runAsNonRoot": True,
                                                "seccompProfile": {"type": "RuntimeDefault"}} or
                len(containers) != 1 or
                container.get("name") != ("probe" if role == "client" else "server") or
                container.get("image") != IMAGE or
                container.get("command") != FIXTURE_COMMANDS[role] or
                container.get("args") not in (None, []) or
                container.get("securityContext") != FIXTURE_SECURITY or
                container.get("resources") != FIXTURE_RESOURCES or
                container.get("imagePullPolicy") != "Always" or
                container.get("ports", []) != reviewed_ports or
                not probes_valid or
                not image_status_valid or
                not pod["metadata"].get("uid") or not pod["status"].get("podIP")):
            raise ValueError(f"canary fixture identity or readiness differs: {name}")
        pods[name] = pod
    firewall_pod = None
    if require_firewall:
        firewall = inspect_firewall_source()
        firewall_pods = kubernetes_json("-n", "kube-system", "get", "pods", "-l",
                                        "app.kubernetes.io/name=kube-router-network-policy")
        owners = [item for pod in firewall_pods.get("items", [])
                  for item in pod.get("metadata", {}).get("ownerReferences", [])
                  if item.get("controller") is True]
        if (not firewall.get("metadata", {}).get("uid") or
                firewall["status"].get("observedGeneration") !=
                firewall["metadata"].get("generation") or
                firewall["status"].get("desiredNumberScheduled") != 1 or
                firewall["status"].get("updatedNumberScheduled") != 1 or
                firewall["status"].get("numberReady") != 1 or
                len(firewall_pods.get("items", [])) != 1 or
                firewall_pods["items"][0]["spec"].get("nodeName") != node_name or
                firewall_pods["items"][0]["spec"]["containers"][0].get("image") != FIREWALL_IMAGE or
                len(owners) != 1 or owners[0].get("apiVersion") != "apps/v1" or
                owners[0].get("kind") != "DaemonSet" or
                owners[0].get("name") != "kube-router-network-policy" or
                owners[0].get("uid") != firewall["metadata"]["uid"] or
                not ready(firewall_pods["items"][0])):
            raise ValueError("firewall is not ready only on the admitted canary")
        firewall_pod = firewall_pods["items"][0]
    inventory = runpy.run_path(str(ROOT / "scripts/network-policy-inventory.py"))
    policies = kubernetes_json("-n", NAMESPACE, "get", "networkpolicies")
    policy, = policies.get("items", [])
    def fingerprint(item):
        return inventory["policy_fingerprint"](inventory["normalized_policy"](item))
    if fingerprint(policy) != fingerprint(EXPECTED_POLICY):
        raise ValueError("canary policy differs from reviewed traffic fixture")
    return node, server_node, pods, firewall_pod, fingerprint(policy)


def probe(source, address, port, protocol):
    return subprocess.run(
        ["kubectl", "--request-timeout=15s", "-n", NAMESPACE, "exec", source,
         "--", "/usr/bin/python3", "-c", PROBE, address, str(port), protocol],
        capture_output=True, text=True, timeout=25,
    )


def probe_dns(source, address, protocol, expected):
    return subprocess.run(
        ["kubectl", "--request-timeout=15s", "-n", NAMESPACE, "exec", source,
         "--", "/usr/bin/python3", "-c", DNS_PROBE, address, protocol, expected, "53"],
        capture_output=True, text=True, timeout=25,
    )


def dns_matrix():
    service = kubernetes_json("-n", "kube-system", "get", "service", "kube-dns")
    kubernetes = kubernetes_json("-n", "default", "get", "service", "kubernetes")
    metadata, spec = service.get("metadata", {}), service.get("spec", {})
    kube_metadata, kube_spec = kubernetes.get("metadata", {}), kubernetes.get("spec", {})
    ports = {(item.get("protocol"), item.get("port"), item.get("targetPort"))
             for item in spec.get("ports", [])}
    if (metadata.get("name") != "kube-dns" or metadata.get("namespace") != "kube-system" or
            spec.get("clusterIP") != "10.96.0.10" or
            spec.get("ipFamilies") != ["IPv4"] or
            spec.get("selector") != {"k8s-app": "kube-dns"} or
            not {("TCP", 53, 53), ("UDP", 53, 53)}.issubset(ports)):
        raise ValueError("DNS Service differs from reviewed IPv4 source")
    try:
        expected = str(ipaddress.IPv4Address(kube_spec.get("clusterIP")))
    except (ValueError, TypeError):
        raise ValueError("Kubernetes Service has no IPv4 address") from None
    if (kube_metadata.get("name") != "kubernetes" or
            kube_metadata.get("namespace") != "default" or
            kube_spec.get("ipFamilies") != ["IPv4"]):
        raise ValueError("Kubernetes Service differs from reviewed IPv4 source")
    results = []
    for protocol in ("TCP", "UDP"):
        result = probe_dns("npq-client", "10.96.0.10", protocol, expected)
        if result.returncode != 0 or result.stdout.strip() != "NPQ_DNS_ALLOWED":
            raise ValueError(f"DNS {protocol} probe failed")
        results.append({"source": "npq-client", "target": "kube-dns", "port": 53,
                        "protocol": protocol, "permitted": True,
                        "observed": "NPQ_DNS_ALLOWED"})
    return results


def traffic_matrix(pods):
    results = []
    for source, target, port, protocol, permitted in CASES:
        result = probe(source, pods[target]["status"]["podIP"], port, protocol)
        marker = "NPQ_ALLOWED" if permitted else "NPQ_DENIED"
        if result.returncode != (0 if permitted else 7) or result.stdout.strip() != marker:
            raise ValueError(f"canary traffic mismatch: {source}/{target}/{port}/{protocol}")
        results.append({"source": source, "target": target, "port": port,
                        "protocol": protocol, "permitted": permitted,
                        "observed": marker})
    results.extend(dns_matrix())
    return results


def private_output(path, record):
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError("private receipt path must be new and absolute")
    parent = path.parent.resolve(strict=True)
    info = parent.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) != 0o700 or
            any((directory / ".git").exists() for directory in (parent, *parent.parents))):
        raise ValueError("private receipt directory must be owned, 0700, and outside Git")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(record, output, sort_keys=True, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def fixture_identity(pods):
    return {name: {"uid": pod["metadata"]["uid"],
                   "node": pod["spec"]["nodeName"],
                   "podIP": pod["status"]["podIP"],
                   "containerID": pod["status"]["containerStatuses"][0]["containerID"],
                   "imageID": pod["status"]["containerStatuses"][0]["imageID"]}
            for name, pod in pods.items()}


def traffic_receipt(source_sha, node, server_node, pods, firewall, policy_hash, cases):
    """Record fixture probes without implying that lifecycle qualification passed."""
    return {
        "format": 1, "result": "traffic-probe-passed-lifecycle-unverified",
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "sourceSha": source_sha,
        "node": node["metadata"]["name"], "nodeUid": node["metadata"]["uid"],
        "bootID": node["status"]["nodeInfo"]["bootID"],
        "fixtureNode": server_node["metadata"]["name"],
        "fixtureNodeUid": server_node["metadata"]["uid"],
        "fixtureBootID": server_node["status"]["nodeInfo"]["bootID"],
        "firewallPodUid": firewall["metadata"]["uid"],
        "fixturePodUids": {name: pod["metadata"]["uid"] for name, pod in pods.items()},
        "fixturePodNodes": {name: pod["spec"]["nodeName"] for name, pod in pods.items()},
        "fixturePodIps": {name: pod["status"]["podIP"] for name, pod in pods.items()},
        "fixtureContainerIds": {name: pod["status"]["containerStatuses"][0]["containerID"]
                                for name, pod in pods.items()},
        "fixtureImageIds": {name: pod["status"]["containerStatuses"][0]["imageID"]
                            for name, pod in pods.items()},
        "policySha256": policy_hash, "cases": cases,
        "unverifiedLifecycleScenarios": list(LIFECYCLE_SCENARIOS),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=ROOT / "scripts/config/platform-maintenance.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        source_sha = require_protected_source()
        config = json.loads(args.config.read_text())
        runpy.run_path(str(ROOT / "scripts/platform-maintenance.py"))["validate_config"](config)
        node, server_node, pods, firewall, policy_hash = inspect(config)
        cases = traffic_matrix(pods)
        node_after, server_after, pods_after, firewall_after, policy_hash_after = inspect(config)
        if (node_after["metadata"]["uid"] != node["metadata"]["uid"] or
                node_after["status"]["nodeInfo"]["bootID"] != node["status"]["nodeInfo"]["bootID"] or
                server_after["metadata"]["uid"] != server_node["metadata"]["uid"] or
                server_after["status"]["nodeInfo"]["bootID"] != server_node["status"]["nodeInfo"]["bootID"] or
                firewall_after["metadata"]["uid"] != firewall["metadata"]["uid"] or
                policy_hash_after != policy_hash or
                fixture_identity(pods_after) != fixture_identity(pods)):
            raise ValueError("canary identity changed during the traffic matrix")
        private_output(args.output, traffic_receipt(
            source_sha, node, server_node, pods, firewall, policy_hash, cases))
        print("Canary traffic probe passed; lifecycle and real workload qualification remain pending")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        try:
            private_output(args.output, {"format": 1, "result": "traffic-probe-failed",
                                         "capturedAt": datetime.now(timezone.utc).isoformat(),
                                         "diagnostic": str(error)})
        except (OSError, ValueError):
            # A failed diagnostic write must not hide the probe failure.
            pass
        print("Canary traffic probe blocked; private diagnostics required", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
