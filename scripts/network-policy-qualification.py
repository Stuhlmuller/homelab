#!/usr/bin/env python3
"""Probe the admitted policy canary; lifecycle evidence is checked separately."""

import argparse
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
IMAGE = "harbor.stinkyboi.com/mirror/cgr.dev/chainguard/python:1c4deeea85db49ab5f6bcd9e7fc0bf3fd8439e99f7bde45330f40400685eb394@sha256:1c4deeea85db49ab5f6bcd9e7fc0bf3fd8439e99f7bde45330f40400685eb394"
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
except OSError: sys.exit(7)
if data!=b'npq-ok': sys.exit(8)
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
             "egress": [{"to": [{"podSelector": {"matchLabels": {"role": "allowed"}}}],
                         "ports": [{"protocol": "TCP", "port": 8080},
                                   {"protocol": "UDP", "port": 8080}]}]},
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


def inspect(config):
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
    for name, role in (("npq-client", "client"), ("npq-allowed", "allowed"),
                       ("npq-denied", "denied")):
        pod = kubernetes_json("-n", NAMESPACE, "get", "pod", name)
        if (not ready(pod) or pod["spec"].get("nodeName") != node_name or
                pod["metadata"].get("labels", {}).get("role") != role or
                pod["spec"]["containers"][0].get("image") != IMAGE or
                not pod["metadata"].get("uid") or not pod["status"].get("podIP")):
            raise ValueError(f"canary fixture identity or readiness differs: {name}")
        pods[name] = pod
    firewall = inspect_firewall_source()
    firewall_pods = kubernetes_json("-n", "kube-system", "get", "pods", "-l",
                                    "app.kubernetes.io/name=kube-router-network-policy")
    if (firewall["status"].get("desiredNumberScheduled") != 1 or
            firewall["status"].get("numberReady") != 1 or
            len(firewall_pods.get("items", [])) != 1 or
            firewall_pods["items"][0]["spec"].get("nodeName") != node_name or
            firewall_pods["items"][0]["spec"]["containers"][0].get("image") != FIREWALL_IMAGE or
            not ready(firewall_pods["items"][0])):
        raise ValueError("firewall is not ready only on the admitted canary")
    inventory = runpy.run_path(str(ROOT / "scripts/network-policy-inventory.py"))
    policies = kubernetes_json("-n", NAMESPACE, "get", "networkpolicies")
    policy, = policies.get("items", [])
    def fingerprint(item):
        return inventory["policy_fingerprint"](inventory["normalized_policy"](item))
    if fingerprint(policy) != fingerprint(EXPECTED_POLICY):
        raise ValueError("canary policy differs from reviewed traffic fixture")
    return node, pods, firewall_pods["items"][0], fingerprint(policy)


def probe(source, address, port, protocol):
    return subprocess.run(
        ["kubectl", "--request-timeout=15s", "-n", NAMESPACE, "exec", source,
         "--", "/usr/bin/python3", "-c", PROBE, address, str(port), protocol],
        capture_output=True, text=True, timeout=25,
    ).returncode


def traffic_matrix(pods):
    results = []
    for source, target, port, protocol, permitted in CASES:
        code = probe(source, pods[target]["status"]["podIP"], port, protocol)
        if code not in (0, 7) or (code == 0) != permitted:
            raise ValueError(f"canary traffic mismatch: {source}/{target}/{port}/{protocol}")
        results.append({"source": source, "target": target, "port": port,
                        "protocol": protocol, "permitted": permitted})
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


def traffic_receipt(source_sha, node, pods, firewall, policy_hash, cases):
    """Record fixture probes without implying that lifecycle qualification passed."""
    return {
        "format": 1, "result": "traffic-probe-passed-lifecycle-unverified",
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "sourceSha": source_sha,
        "node": node["metadata"]["name"], "nodeUid": node["metadata"]["uid"],
        "bootID": node["status"]["nodeInfo"]["bootID"],
        "firewallPodUid": firewall["metadata"]["uid"],
        "fixturePodUids": {name: pod["metadata"]["uid"] for name, pod in pods.items()},
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
        node, pods, firewall, policy_hash = inspect(config)
        cases = traffic_matrix(pods)
        node_after, pods_after, firewall_after, policy_hash_after = inspect(config)
        if (node_after["metadata"]["uid"] != node["metadata"]["uid"] or
                node_after["status"]["nodeInfo"]["bootID"] != node["status"]["nodeInfo"]["bootID"] or
                firewall_after["metadata"]["uid"] != firewall["metadata"]["uid"] or
                policy_hash_after != policy_hash or
                any(pods_after[name]["metadata"]["uid"] != pod["metadata"]["uid"]
                    for name, pod in pods.items())):
            raise ValueError("canary identity changed during the traffic matrix")
        private_output(args.output, traffic_receipt(
            source_sha, node, pods, firewall, policy_hash, cases))
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
