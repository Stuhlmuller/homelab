#!/usr/bin/env python3
"""Bind a reviewed empty firewall capture to fresh canary placement evidence."""

import argparse
import hashlib
import json
import re
import runpy
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts/config/platform-maintenance.json"
BASELINE = runpy.run_path(str(ROOT / "scripts/network-policy-firewall-baseline.py"))
CLEANUP = BASELINE["CLEANUP"]
CANARY = BASELINE["CANARY"]
OWNERSHIP = BASELINE["OWNERSHIP"]
PLATFORM = BASELINE["PLATFORM"]
NODE = BASELINE["NODE"]
MIB = 1024 * 1024
PLANNED_MEMORY_REQUEST = 346 * MIB  # Pinned enforcer 250Mi plus three 32Mi fixtures.
PLANNED_MEMORY_LIMIT = 704 * MIB  # Pinned enforcer 512Mi plus three 64Mi fixtures.
PLANNED_CPU_REQUEST = 280  # Pinned enforcer 250m plus three 10m fixtures.
MEMORY_MARGIN = 128 * MIB
CPU_MARGIN = 100
NODEFS_MINIMUM = 5 * 1024 * MIB
MANIFESTS = {
    "clusters/homelab/platform/network-policy/daemonset.yaml":
        "831351533a2aadc734e4333d24c753a43c5ccedbc5a98c3b8784e0d82d8c0f73",
    "clusters/homelab/platform/network-policy/canary/fixtures.yaml":
        "57a14d3469b22e7480aef8ac02b0218e5248a9d855c0697629aa0cee1987a672",
}
SCALES = {"": 1, "n": Decimal("1e-9"), "u": Decimal("1e-6"),
          "m": Decimal("1e-3"), "k": 1000, "M": 1000**2, "G": 1000**3,
          "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4}


def quantity(value, cpu=False):
    match = re.fullmatch(r"(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(n|u|m|k|M|G|Ki|Mi|Gi|Ti)?",
                         str(value))
    if not match:
        raise ValueError("Kubernetes resource quantity is unsupported")
    amount = Decimal(match[1]) * SCALES[match[2] or ""] * (1000 if cpu else 1)
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def fresh(value, seconds):
    if not isinstance(value, str):
        raise ValueError("evidence timestamp is missing")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() != timedelta(0):
        raise ValueError("evidence timestamp is not UTC")
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    if not 0 <= age <= seconds:
        raise ValueError("evidence timestamp is stale or in the future")
    return stamp


def pinned_manifests(source_sha):
    for relative, digest in MANIFESTS.items():
        content = (ROOT / relative).read_bytes()
        committed = subprocess.check_output(
            ["git", "--no-replace-objects", "show", f"{source_sha}:{relative}"],
            cwd=ROOT, timeout=15)
        if content != committed or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("canary resource budget differs from pinned manifests")


def read_baseline(store, source_sha, run_id):
    key = (f"openclaw-enterprise/platform/{source_sha}/{run_id}/"
           "firewall-baseline-capture.json")
    version = store.version(key, True)
    content = store.read(key, OWNERSHIP["MAX_CAPTURE"])
    if store.version(key, True) != version:
        raise ValueError("firewall capture version changed while reading")
    capture = json.loads(content)
    snapshot = capture.get("snapshot") if isinstance(capture, dict) else None
    if (not isinstance(capture, dict) or capture.get("format") != 1 or
            capture.get("stage") != "firewall-baseline" or
            capture.get("status") != "verified" or capture.get("verified") is not True or
            capture.get("sourceSha") != source_sha or capture.get("runId") != run_id or
            capture.get("node") != NODE or
            not isinstance(capture.get("nodeUid"), str) or not capture["nodeUid"] or
            not isinstance(capture.get("bootID"), str) or not capture["bootID"] or
            capture.get("firewallBaselineEmpty") is not True or
            capture.get("podDeleted") is not True or
            capture.get("ownedChains") != 0 or capture.get("ownedSets") != 0 or
            not isinstance(snapshot, dict) or
            set(snapshot) != {"backend", "nft", "legacy", "ip6nft", "ip6legacy", "ipset"} or
            capture.get("backend") != snapshot["backend"] or
            capture.get("snapshotSha256") != CLEANUP["snapshot_sha256"](snapshot) or
            any(CLEANUP["cleanup_plan"](snapshot))):
        raise ValueError("verified empty firewall baseline is missing")
    fresh(capture.get("completedAt"), 3600)
    return capture, hashlib.sha256(content).hexdigest(), version


def pod_requests(pod):
    if pod.get("status", {}).get("phase") != "Running" or not CLEANUP["ready"](pod):
        raise ValueError("system DaemonSet Pod is not Ready")
    spec = pod["spec"]
    if spec.get("resources") or spec.get("ephemeralContainers"):
        raise ValueError("unreviewed Pod-level or ephemeral resource budget")

    def request(container, name, cpu=False):
        resources = container.get("resources", {})
        if not isinstance(resources, dict) or not isinstance(resources.get("requests", {}), dict):
            raise ValueError("system Pod resource requests are invalid")
        return quantity(resources.get("requests", {}).get(name, "0"), cpu)

    containers, init = spec.get("containers"), spec.get("initContainers", [])
    if not isinstance(containers, list) or not containers or not isinstance(init, list):
        raise ValueError("system Pod container list is invalid")
    if any(container.get("restartPolicy") == "Always" for container in init):
        raise ValueError("restartable init container needs separate capacity accounting")
    total = []
    for name, cpu in (("memory", False), ("cpu", True)):
        ordinary = sum(request(container, name, cpu) for container in containers)
        initial = max((request(container, name, cpu) for container in init), default=0)
        overhead = quantity(spec.get("overhead", {}).get(name, "0"), cpu)
        total.append(max(ordinary, initial) + overhead)
    return total


def capacity(capture):
    node = CLEANUP["kubernetes_json"]("get", "node", NODE)
    allocatable = node.get("status", {}).get("allocatable", {})
    if not isinstance(allocatable, dict):
        raise ValueError("Node allocatable resources are missing")
    memory = quantity(allocatable.get("memory"))
    cpu = quantity(allocatable.get("cpu"), True)
    listing = CLEANUP["kubernetes_json"]("get", "pods", "-A", "--field-selector",
                                         f"spec.nodeName={NODE}", "--chunk-size=0")
    pods = CLEANUP["complete_items"](listing, "placement assigned Pod")
    identities = sorted(({"namespace": item["metadata"]["namespace"],
                          "name": item["metadata"]["name"],
                          "uid": item["metadata"]["uid"]} for item in pods),
                        key=lambda item: (item["namespace"], item["name"]))
    if identities != capture["systemDaemonSetPods"]:
        raise ValueError("assigned Pods changed since firewall capture")
    requests = [pod_requests(pod) for pod in pods]
    used_requests = [sum(item[index] for item in requests) for index in (0, 1)]
    metrics = json.loads(CLEANUP["command"](
        "kubectl", "--request-timeout=20s", "get", "--raw",
        f"/apis/metrics.k8s.io/v1beta1/nodes/{NODE}"))
    if (metrics.get("kind") != "NodeMetrics" or
            metrics.get("metadata", {}).get("name") != NODE):
        raise ValueError("Node metrics identity differs")
    fresh(metrics.get("timestamp"), 120)
    observed_memory = quantity(metrics["usage"]["memory"])
    observed_cpu = quantity(metrics["usage"]["cpu"], True)
    summary = json.loads(CLEANUP["command"](
        "kubectl", "--request-timeout=20s", "get", "--raw",
        f"/api/v1/nodes/{NODE}/proxy/stats/summary"))
    filesystem = summary.get("node", {}).get("fs", {})
    if summary.get("node", {}).get("nodeName") != NODE:
        raise ValueError("kubelet summary Node identity differs")
    fresh(filesystem.get("time"), 120)
    available = filesystem.get("availableBytes")
    if (type(available) is not int or available < NODEFS_MINIMUM or
            type(filesystem.get("capacityBytes")) is not int or
            available > filesystem["capacityBytes"]):
        raise ValueError("canary node filesystem headroom is insufficient")
    if (memory - used_requests[0] - PLANNED_MEMORY_REQUEST < MEMORY_MARGIN or
            memory - observed_memory - PLANNED_MEMORY_LIMIT < MEMORY_MARGIN or
            cpu - used_requests[1] - PLANNED_CPU_REQUEST < CPU_MARGIN or
            cpu - observed_cpu - PLANNED_CPU_REQUEST < CPU_MARGIN):
        raise ValueError("canary node memory or CPU headroom is insufficient")
    return {"allocatableMemoryBytes": memory, "requestedMemoryBytes": used_requests[0],
            "observedMemoryBytes": observed_memory,
            "plannedMemoryRequestBytes": PLANNED_MEMORY_REQUEST,
            "plannedMemoryLimitBytes": PLANNED_MEMORY_LIMIT,
            "allocatableCpuMilli": cpu, "requestedCpuMilli": used_requests[1],
            "observedCpuMilli": observed_cpu, "plannedCpuRequestMilli": PLANNED_CPU_REQUEST,
            "nodeFsAvailableBytes": available, "memoryMarginBytes": MEMORY_MARGIN,
            "cpuMarginMilli": CPU_MARGIN, "nodeFsMinimumBytes": NODEFS_MINIMUM}


def reviewed_config(args):
    PLATFORM["require_reviewed_execution_config"](args.config, args.expected_sha)
    config = PLATFORM["validate_config"](json.loads(args.config.read_text()))
    if config["activationEnabled"] is not False or config["canary"]["node"] != NODE:
        raise ValueError("placement requires the reviewed pre-enable node")
    PLATFORM["protected_context"](args.expected_sha)
    CLEANUP["require_current_main"](args.expected_sha)
    pinned_manifests(args.expected_sha)
    return config


def live_capacity(config, capture, source_sha, placement=None):
    def identity():
        if placement is None:
            return BASELINE["node_identity"]()
        node, labeled, _ = CANARY["node_state"](config, placement)
        if labeled:
            raise ValueError("canary Node is already labeled")
        return node["metadata"]["uid"], node["status"]["nodeInfo"]["bootID"]

    CANARY["require_runtime_absent"](True)
    current = identity()
    if current != (capture["nodeUid"], capture["bootID"]):
        raise ValueError("Node identity changed since firewall capture")
    if BASELINE["system_pods"]() != capture["systemDaemonSetPods"]:
        raise ValueError("system DaemonSet Pods changed since firewall capture")
    CANARY["require_exclusive_canary_label"](config, capture, False)
    measured = capacity(capture)
    if (identity() != current or
            BASELINE["system_pods"]() != capture["systemDaemonSetPods"]):
        raise ValueError("Node or Pods changed during capacity measurement")
    CANARY["require_runtime_absent"](True)
    CLEANUP["require_current_main"](source_sha)
    return current, measured


def execute(args):
    if (args.baseline_source_sha != args.expected_sha or
            not re.fullmatch(r"[1-9][0-9]*", args.baseline_run_id or "")):
        raise ValueError("placement requires a baseline from exact current main")
    config = reviewed_config(args)
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("placement output already exists")
    store = OWNERSHIP["PrivateStore"](args.bucket)
    store.store.check()
    capture, digest, version = read_baseline(store, args.expected_sha, args.baseline_run_id)
    identity, measured = live_capacity(config, capture, args.expected_sha)
    record = {"format": 1, "verified": True, "sourceSha": args.expected_sha,
              "node": NODE, "canaryNode": NODE, "nodeUid": identity[0],
              "bootID": identity[1], "measured": True,
              "isolatedTaint": config["canary"]["taint"],
              "firewallBaselineEmpty": True,
              "systemDaemonSetPods": capture["systemDaemonSetPods"],
              "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "baselineSourceSha": args.expected_sha,
              "baselineRunId": args.baseline_run_id,
              "baselineCapturedAt": fresh(capture["completedAt"], 3600).strftime(
                  "%Y-%m-%dT%H:%M:%SZ"),
              "baselineCaptureSha256": digest, "baselineCaptureVersionId": version,
              "capacity": measured}
    CANARY["validate_placement"](record, config, args.expected_sha, True)
    key = f"openclaw-enterprise/platform/receipts/{args.expected_sha}/placement.json"
    store.write_once(key, record, 1048576)
    CLEANUP["write_record"](output, record)
    return record


def check(args):
    config = reviewed_config(args)
    placement_path = PLATFORM["private_directory"](args.check_placement.parent) / "placement.json"
    if args.check_placement.name != "placement.json":
        raise ValueError("reviewed placement path is required")
    placement = PLATFORM["read_private_json"](placement_path)
    CANARY["validate_placement"](placement, config, args.expected_sha, True)
    store = OWNERSHIP["PrivateStore"](args.bucket)
    store.store.check()
    capture, digest, version = read_baseline(
        store, args.expected_sha, placement["baselineRunId"])
    if (placement["nodeUid"] != capture["nodeUid"] or
            placement["bootID"] != capture["bootID"] or
            placement["systemDaemonSetPods"] != capture["systemDaemonSetPods"] or
            placement["baselineCaptureSha256"] != digest or
            placement["baselineCaptureVersionId"] != version or
            placement["baselineCapturedAt"] != fresh(
                capture["completedAt"], 3600).strftime("%Y-%m-%dT%H:%M:%SZ")):
        raise ValueError("placement differs from verified firewall capture")
    live_capacity(config, capture, args.expected_sha, placement)
    CANARY["validate_placement"](placement, config, args.expected_sha, True)
    fresh(capture["completedAt"], 3600)
    key = (f"openclaw-enterprise/platform/{args.expected_sha}/"
           f"{placement['baselineRunId']}/firewall-baseline-capture.json")
    if store.version(key, True) != version:
        raise ValueError("firewall capture version changed during admission check")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--baseline-source-sha")
    parser.add_argument("--baseline-run-id")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-placement", type=Path)
    args = parser.parse_args()
    try:
        if args.check_placement:
            if args.output or args.baseline_source_sha or args.baseline_run_id:
                raise ValueError("placement check accepts only its reviewed receipt")
            check(args)
        else:
            if not args.output or not args.baseline_source_sha or not args.baseline_run_id:
                raise ValueError("placement output and baseline source are required")
            execute(args)
    except (OSError, ValueError, KeyError, TypeError, IndexError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"placement blocked: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
