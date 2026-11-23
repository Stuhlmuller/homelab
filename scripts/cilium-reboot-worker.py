#!/usr/bin/env python3
"""Restart the evacuated first Cilium worker and verify its new boot."""

import argparse
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
WORKER = "zimaboard-2"
BOOT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
evacuation = runpy.run_path(str(ROOT / "scripts/cilium-evacuate-worker.py"))
get = evacuation["get"]
check_main = evacuation["check_main"]
ready_elsewhere = evacuation["ready_elsewhere"]


def require_ready_for_reboot(node, config, pods, address, previous_boot):
    if node["metadata"]["name"] != WORKER or node["spec"].get("unschedulable") is not True:
        raise ValueError("The first worker must remain cordoned")
    if not any(entry["type"] == "InternalIP" and entry["address"] == address
               for entry in node["status"]["addresses"]):
        raise ValueError("The Kubernetes and reviewed Talos worker addresses differ")
    if node["status"]["nodeInfo"]["bootID"] != previous_boot:
        raise ValueError("Worker boot ID changed since the reviewed preflight")
    if config["spec"] != {
        "nodeSelector": {"matchLabels": {"kubernetes.io/hostname": WORKER}},
        "defaults": {
            "write-cni-conf-when-ready": "/host/etc/cni/net.d/05-cilium.conflist",
            "custom-cni-conf": "false",
            "cni-chaining-mode": "none",
            "cni-exclusive": "false",
        },
    }:
        raise ValueError("Cilium cutover configuration does not select exactly the first worker")
    for pod in pods:
        if pod.get("status", {}).get("phase") in {"Succeeded", "Failed"}:
            continue
        owners = pod["metadata"].get("ownerReferences", [])
        if not any(owner.get("controller") and owner["kind"] == "DaemonSet" for owner in owners):
            raise ValueError("The worker still has active non-DaemonSet Pods")


def await_new_boot(uid, previous_boot):
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        node = get("node", WORKER)
        if node["metadata"]["uid"] != uid or node["spec"].get("unschedulable") is not True:
            raise ValueError("The worker identity or scheduling state changed during reboot")
        status = node["status"]
        if (status["nodeInfo"]["bootID"] != previous_boot
                and any(c["type"] == "Ready" and c["status"] == "True" for c in status["conditions"])):
            return
        time.sleep(10)
    raise RuntimeError("The worker did not report a new Ready boot before the deadline")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--previous-boot-id", required=True)
    parser.add_argument("--talosconfig", required=True, type=Path)
    args = parser.parse_args()
    sha = args.expected_sha
    if (not re.fullmatch(r"[0-9a-f]{40}", sha) or not BOOT_ID.fullmatch(args.previous_boot_id)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_SHA") != sha
            or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
            or subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip() != sha):
        raise SystemExit("The first attempt of the exact-main protected workflow is required")
    platform = json.loads((ROOT / "scripts/config/platform-maintenance.json").read_text())
    address = platform["expectedStart"]["nodes"][WORKER]["address"]
    node = get("node", WORKER)
    require_ready_for_reboot(
        node,
        get("ciliumnodeconfig", "homelab-primary-cni-cutover", "-n", "kube-system"),
        get("pods", "-A", "--field-selector", f"spec.nodeName={WORKER}")["items"],
        address,
        args.previous_boot_id,
    )
    if not (ready_elsewhere("automation", "app.kubernetes.io/name=adguard")
            and ready_elsewhere("harbor", "component=core")):
        raise SystemExit("AdGuard and Harbor must be Ready on surviving nodes")
    check_main(sha)
    subprocess.run(
        ("talosctl", "--talosconfig", str(args.talosconfig),
         "--endpoints", platform["protectedTalosEndpoint"], "--nodes", address, "reboot"),
        check=True, timeout=120,
    )
    await_new_boot(node["metadata"]["uid"], args.previous_boot_id)
    check_main(sha)
    print("First worker reports a new Ready boot and remains cordoned for Cilium probes.")


if __name__ == "__main__":
    main()
