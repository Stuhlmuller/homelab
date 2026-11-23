#!/usr/bin/env python3
"""Evacuate the fixed first worker through the protected Cilium rollout."""

import argparse
import json
import os
import re
import subprocess


REPOSITORY = "Stuhlmuller/homelab"
WORKER = "zimaboard-2"
NODES = {"acer", "zimaboard-0", "zimaboard-1", WORKER}
APP = "platform-cilium"


def run(*args, timeout=30):
    return subprocess.check_output(args, text=True, timeout=timeout).strip()


def kube(*args, timeout=30):
    return run("kubectl", f"--request-timeout={timeout}s", *args, timeout=timeout + 10)


def get(*args):
    return json.loads(kube("get", *args, "-o", "json"))


def check_main(sha):
    if run("gh", "api", f"repos/{REPOSITORY}/git/ref/heads/main", "--jq", ".object.sha") != sha:
        raise ValueError("main moved before worker evacuation")


def require_overlay(app, nodes, daemonsets):
    status = app["status"]
    if status["sync"]["status"] != "Synced" or status["health"]["status"] != "Healthy":
        raise ValueError("Cilium coexistence Application must be Synced and Healthy")
    sync = app["spec"]["syncPolicy"]["automated"]
    if sync["enabled"] is not True:
        raise ValueError("Cilium coexistence overlay is not enabled")
    revisions = status["sync"].get("revisions", [])
    if len(revisions) != 2 or revisions[0] != "1.20.5" or not re.fullmatch(r"[0-9a-f]{40}", revisions[1]):
        raise ValueError("Cilium Application has not observed the reviewed chart and Git sources")
    if any(resource["kind"] == "CiliumNodeConfig" for resource in status.get("resources", [])):
        raise ValueError("Node cutover configuration is already tracked")
    if {node["metadata"]["name"] for node in nodes} != NODES:
        raise ValueError("Unexpected Kubernetes node inventory")
    if any(node["metadata"]["name"] != WORKER and node["spec"].get("unschedulable")
           for node in nodes):
        raise ValueError("A different node is already cordoned")
    for daemonset in daemonsets:
        metadata, status = daemonset["metadata"], daemonset["status"]
        if status.get("observedGeneration") != metadata["generation"] or any(
            status.get(field) != len(NODES)
            for field in ("desiredNumberScheduled", "numberReady", "updatedNumberScheduled", "numberAvailable")
        ):
            raise ValueError(f"{metadata['name']} is not current and ready on every node")


def ready_elsewhere(namespace, labels):
    pods = get("pods", "-n", namespace, "-l", labels)["items"]
    return any(pod["spec"].get("nodeName") in NODES - {WORKER}
               and not pod["metadata"].get("deletionTimestamp")
               and any(condition["type"] == "Ready" and condition["status"] == "True"
                       for condition in pod.get("status", {}).get("conditions", []))
               for pod in pods)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    sha = parser.parse_args().expected_sha
    if (not re.fullmatch(r"[0-9a-f]{40}", sha)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_SHA") != sha
            or run("git", "rev-parse", "HEAD") != sha):
        raise SystemExit("The exact-main protected workflow is required")

    check_main(sha)
    require_overlay(
        get("application", APP, "-n", "argocd"),
        get("nodes")["items"],
        [get("daemonset", name, "-n", "kube-system")
         for name in ("cilium", "cilium-envoy", "kube-flannel", "kube-multus-ds")],
    )
    config = get("configmap", "cilium-config", "-n", "kube-system")["data"]
    if config.get("enable-policy") != "never" or config.get("custom-cni-conf") != "true":
        raise SystemExit("Cilium must still be in coexistence mode")
    if get("ciliumnodeconfigs", "-A")["items"]:
        raise SystemExit("Review existing CiliumNodeConfig objects before first-worker evacuation")
    if not ready_elsewhere("automation", "app.kubernetes.io/name=adguard"):
        raise SystemExit("Verify AdGuard on a surviving node before evacuation")
    options = ("drain", WORKER, "--ignore-daemonsets", "--delete-emptydir-data", "--timeout=300s")
    kube(*options, "--dry-run=server", timeout=60)
    check_main(sha)
    if not ready_elsewhere("harbor", "component=core"):
        raise SystemExit("Verify Harbor core Ready on a surviving node before evacuation")
    kube(*options, timeout=310)
    kube("-n", "harbor", "rollout", "status", "deployment/harbor-core", "--timeout=300s", timeout=310)
    if not ready_elsewhere("harbor", "component=core"):
        raise SystemExit("Harbor core is not Ready on a surviving node")
    check_main(sha)
    print("First worker remains cordoned and drained. Verify registry pulls and tailnet DNS before cutover.")


if __name__ == "__main__":
    main()
