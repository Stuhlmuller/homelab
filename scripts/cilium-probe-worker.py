#!/usr/bin/env python3
"""Qualify the first worker's Cilium sandbox before restoring scheduling."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "cilium-worker-probe"
JOB = "cilium-first-worker-probe"
WORKER = "zimaboard-2"
PROBE = ROOT / "clusters/homelab/platform/cilium/worker-probe"
checks = runpy.run_path(str(ROOT / "scripts/cilium-cutover-check.py"))
commands = runpy.run_path(str(ROOT / "scripts/cilium-evacuate-worker.py"))
get, kube, check_main = (commands[name] for name in ("get", "kube", "check_main"))


def check_worker(node, previous_boot):
    status = node["status"]
    if (node["metadata"]["name"] != WORKER or not node["spec"].get("unschedulable")
            or not status["nodeInfo"].get("bootID")
            or status["nodeInfo"]["bootID"] == previous_boot
            or not any(item["type"] == "Ready" and item["status"] == "True"
                       for item in status["conditions"])):
        raise ValueError("Expected a Ready, rebooted and still-cordoned first worker")


def wait_for_probe():
    selector = f"batch.kubernetes.io/job-name={JOB}"
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        pods = get("pods", "-n", NAMESPACE, "-l", selector)["items"]
        if pods:
            if len(pods) != 1:
                raise ValueError("Expected one first-worker probe")
            name = pods[0]["metadata"]["name"]
            kube("-n", NAMESPACE, "wait", "--for=condition=Ready",
                 f"pod/{name}", "--timeout=180s", timeout=185)
            pod = get("pod", name, "-n", NAMESPACE)
            if pod["metadata"]["uid"] != pods[0]["metadata"]["uid"] or pod["spec"].get("nodeName") != WORKER:
                raise ValueError("The Ready probe identity or assignment changed")
            return pod
        time.sleep(2)
    raise RuntimeError("The worker probe Pod was not created in time")


def delete_namespace(uid):
    options = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": uid}}
    subprocess.run(("kubectl", "--request-timeout=30s", "delete", "--raw",
                    f"/api/v1/namespaces/{NAMESPACE}", "-f", "-"),
                   input=json.dumps(options), text=True, check=True,
                   stdout=subprocess.DEVNULL, timeout=40)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--previous-boot-id", required=True)
    parser.add_argument("--pool", required=True, type=ipaddress.ip_network)
    args = parser.parse_args()
    sha = args.expected_sha
    if (not re.fullmatch(r"[0-9a-f]{40}", sha)
            or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", args.previous_boot_id)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_SHA") != sha
            or subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip() != sha):
        raise SystemExit("The exact-main protected workflow is required")

    check_main(sha)
    initial_node = get("node", WORKER)
    check_worker(initial_node, args.previous_boot_id)
    namespace = json.loads(kube("create", "-f", str(PROBE / "namespace.yaml"), "-o", "json"))
    namespace_uid = namespace["metadata"]["uid"]
    try:
        kube("create", "-f", str(PROBE / "secondary.yaml"), "-f", str(PROBE / "probe.yaml"))
        pod = wait_for_probe()
        attachments = json.loads(pod["metadata"]["annotations"]["k8s.v1.cni.cncf.io/network-status"])
        if not any(entry["name"] == f"{NAMESPACE}/secondary" and entry.get("interface") == "net1"
                   and entry.get("ips") and not entry.get("default") for entry in attachments):
            raise ValueError("The probe lacks the expected Multus secondary network status")
        endpoint = get("ciliumendpoint", pod["metadata"]["name"], "-n", NAMESPACE)
        _, failures = checks["verify"]([pod], [endpoint], args.pool)
        if failures:
            raise ValueError("; ".join(failures))
    finally:
        delete_namespace(namespace_uid)
    kube("wait", "--for=delete", f"namespace/{NAMESPACE}", "--timeout=90s", timeout=95)

    node = get("node", WORKER)
    check_worker(node, args.previous_boot_id)
    if (node["metadata"]["uid"] != initial_node["metadata"]["uid"]
            or node["status"]["nodeInfo"]["bootID"] != initial_node["status"]["nodeInfo"]["bootID"]):
        raise ValueError("Worker identity or boot changed while the probe ran")
    check_main(sha)
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": node["metadata"]["uid"]},
        {"op": "test", "path": "/metadata/resourceVersion", "value": node["metadata"]["resourceVersion"]},
        {"op": "test", "path": "/spec/unschedulable", "value": True},
        {"op": "replace", "path": "/spec/unschedulable", "value": False},
    ]
    kube("patch", "node", WORKER, "--type=json", "-p", json.dumps(patch))
    print("Cilium primary attachment, Multus secondary attachment, DNS and Service checks passed.")


if __name__ == "__main__":
    main()
