#!/usr/bin/env python3
"""Read-only Wazuh capacity gate. No credentials or workload logs are printed."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def read(*args):
    return json.loads(subprocess.check_output(
        ["kubectl", "--request-timeout=20s", *args], text=True))


def memory(value):
    match = re.fullmatch(r"([0-9.]+)([EPTGMK]i?|m)?", str(value or "0"))
    if not match:
        raise ValueError("Unsupported memory quantity")
    suffix = match[2] or ""
    multiplier = 0.001 if suffix == "m" else 1
    if suffix and suffix != "m":
        multiplier = (1024 if suffix.endswith("i") else 1000) ** ("KMGTPE".index(suffix[0]) + 1)
    return int(float(match[1]) * multiplier)


def pod_request(spec):
    # Account for init containers, including native sidecars, as the scheduler does.
    def request(container):
        resources = container.get("resources", {})
        return memory(resources.get("requests", {}).get(
            "memory", resources.get("limits", {}).get("memory", 0)))
    regular = sum(request(c) for c in spec.get("containers", []))
    sidecars, peak = 0, 0
    for container in spec.get("initContainers", []):
        size = request(container)
        if container.get("restartPolicy") == "Always":
            sidecars += size
            peak = max(peak, sidecars)
        else:
            peak = max(peak, sidecars + size)
    return max(regular + sidecars, peak) + memory(spec.get("overhead", {}).get("memory", 0))


def main():
    nodes = read("get", "nodes", "-o", "json")["items"]
    pods = read("get", "pods", "-A", "-o", "json")["items"]
    rendered = subprocess.check_output([
        "kubectl", "kustomize", str(ROOT / "clusters/homelab/apps/wazuh")], text=True)
    manifests = json.loads(subprocess.check_output([
        "yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=rendered, text=True))
    failed = False
    for node in nodes:
        name = node["metadata"]["name"]
        labels = node["metadata"]["labels"]
        capacity = memory(node["status"]["allocatable"]["memory"])
        existing = sum(pod_request(p["spec"]) for p in pods
                       if p["spec"].get("nodeName") == name
                       and p["metadata"]["namespace"] != "wazuh"
                       and p.get("status", {}).get("phase") not in ("Succeeded", "Failed"))
        proposed = 0
        for manifest in manifests:
            if not manifest or manifest.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
                continue
            spec = manifest["spec"]["template"]["spec"]
            if any(labels.get(key) != value for key, value in spec.get("nodeSelector", {}).items()):
                continue
            if manifest["kind"] != "DaemonSet" and not spec.get("nodeSelector"):
                # Reserve flexible single-replica workloads on the central node.
                if name != "acer":
                    continue
            replicas = 1 if manifest["kind"] == "DaemonSet" else manifest["spec"].get("replicas", 1)
            proposed += pod_request(spec) * replicas
        # Keep spare capacity for kernel/etcd and transient ingestion peaks.
        reserve = GIB if name == "acer" else 64 * 1024 ** 2
        free = capacity - existing - proposed
        ready = any(c["type"] == "Ready" and c["status"] == "True"
                    for c in node["status"]["conditions"])
        stats = read("get", "--raw", f"/api/v1/nodes/{name}/proxy/stats/summary")
        available_ram = stats["node"]["memory"]["availableBytes"]
        current_wazuh = sum(p.get("memory", {}).get("workingSetBytes", 0)
                            for p in stats.get("pods", [])
                            if p.get("podRef", {}).get("namespace") == "wazuh")
        incremental = max(0, proposed - current_wazuh)
        actual_fits = available_ram >= incremental + reserve
        fits = ready and free >= reserve and actual_fits
        print(f"{name}: allocatable={capacity/GIB:.2f}Gi existing-requests={existing/GIB:.2f}Gi "
              f"Wazuh-requests={proposed/GIB:.2f}Gi remaining={free/GIB:.2f}Gi "
              f"required-spare={reserve/GIB:.2f}Gi {'PASS' if fits else 'BLOCKED'}")
        print(f"{name}: actual-available={available_ram/GIB:.2f}Gi "
              f"incremental-Wazuh={incremental/GIB:.2f}Gi "
              f"{'PASS' if actual_fits else 'BLOCKED'}")
        failed |= not fits
    stats = read("get", "--raw", "/api/v1/nodes/acer/proxy/stats/summary")
    disk = stats["node"]["fs"]
    available = disk["availableBytes"] / GIB
    disk_ok = available >= 200
    print(f"acer: disk-free={available:.1f}Gi required=200Gi {'PASS' if disk_ok else 'BLOCKED'}")
    failed |= not disk_ok
    if failed:
        raise SystemExit("Wazuh activation blocked by capacity; no changes made")
    print("Capacity gate passed. Verify certificates, secrets, sysctl, backups and ingestion separately.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, ValueError, KeyError) as error:
        print(f"Read-only preflight failed: {type(error).__name__}; no changes made", file=sys.stderr)
        raise SystemExit(1) from None
