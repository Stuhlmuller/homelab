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
    firewall = kubernetes_json("-n", "kube-system", "get", "daemonset",
                               "kube-router-network-policy")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=ROOT / "scripts/config/platform-maintenance.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
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
        private_output(args.output, {
            "format": 1, "result": "traffic-probe-passed-lifecycle-unverified",
            "capturedAt": datetime.now(timezone.utc).isoformat(),
            "sourceSha": command("git", "-C", str(ROOT), "rev-parse", "HEAD").strip(),
            "node": node["metadata"]["name"], "nodeUid": node["metadata"]["uid"],
            "bootID": node["status"]["nodeInfo"]["bootID"],
            "firewallPodUid": firewall["metadata"]["uid"],
            "fixturePodUids": {name: pod["metadata"]["uid"] for name, pod in pods.items()},
            "policySha256": policy_hash, "cases": cases,
        })
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
