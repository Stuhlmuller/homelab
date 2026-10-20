#!/usr/bin/env python3
"""Admit or release the reviewed kube-router canary Node in protected CI."""

import argparse
import json
import os
import re
import runpy
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts/config/platform-maintenance.json"
PLATFORM = runpy.run_path(str(ROOT / "scripts/platform-maintenance.py"))
CLEANUP = runpy.run_path(str(ROOT / "scripts/network-policy-cleanup.py"))
CANARY = CLEANUP["CANARY"]
TAINT = {"key": CANARY, "value": "true", "effect": "NoSchedule"}
LABEL_PATH = "/metadata/labels/" + CANARY.replace("~", "~0").replace("/", "~1")
SYSTEM_NAMESPACES = {"kube-system", "istio-system"}


def require_current_main(source_sha):
    CLEANUP["require_current_main"](source_sha)


def node_state(config, placement):
    node = CLEANUP["kubernetes_json"]("get", "node", config["canary"]["node"])
    metadata, spec = node["metadata"], node["spec"]
    labels, taints = metadata.get("labels", {}), spec.get("taints", [])
    if (metadata.get("name") != config["canary"]["node"] or
            metadata.get("uid") != placement["nodeUid"] or
            node["status"].get("nodeInfo", {}).get("bootID") != placement["bootID"] or
            not isinstance(metadata.get("resourceVersion"), str) or
            not metadata["resourceVersion"] or not isinstance(labels, dict) or
            not isinstance(taints, list) or
            any(not isinstance(item, dict) for item in taints) or
            metadata.get("deletionTimestamp") or spec.get("unschedulable") is True or
            not CLEANUP["ready"](node)):
        raise ValueError("canary Node identity, readiness, or shape changed")
    owned = [item for item in taints if item.get("key") == CANARY]
    if len(owned) > 1 or owned and owned[0] != TAINT or labels.get(CANARY) not in (None, "true"):
        raise ValueError("unexpected canary label or taint")
    return node, labels.get(CANARY) == "true", bool(owned)


def require_runtime_absent(admit):
    for name in (CLEANUP["ENFORCER"], CLEANUP["CLEANUP"] if admit else None):
        if name is None:
            continue
        daemonset = CLEANUP["command"]("kubectl", "--request-timeout=20s", "-n", "kube-system",
                                       "get", "daemonset", name, "--ignore-not-found", "-o", "json")
        if daemonset.strip():
            raise ValueError("firewall DaemonSet must be absent")
        pods = CLEANUP["kubernetes_json"]("-n", "kube-system", "get", "pods", "-l",
                                          f"app.kubernetes.io/name={name}")
        if pods.get("items"):
            raise ValueError("firewall DaemonSet Pod still exists")
    namespace = CLEANUP["command"]("kubectl", "--request-timeout=20s", "get", "namespace",
                                   "network-policy-canary", "--ignore-not-found", "-o", "json")
    if namespace.strip():
        raise ValueError("canary fixture namespace must be absent")


def patch(node, operations, source_sha):
    require_current_main(source_sha)
    metadata = node["metadata"]
    steps = [{"op": "test", "path": "/metadata/resourceVersion",
              "value": metadata["resourceVersion"]},
             {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
             *operations]
    CLEANUP["command"]("kubectl", "--request-timeout=20s", "patch", "node",
                       metadata["name"], "--type=json", "-p", json.dumps(steps), "-o", "json")


def validate_placement(placement, config, source_sha, fresh):
    if (not isinstance(placement, dict) or placement.get("format") != 1 or
            placement.get("verified") is not True or
            placement.get("sourceSha") != source_sha or
            placement.get("node") != config["canary"]["node"] or
            placement.get("canaryNode") != config["canary"]["node"] or
            placement.get("measured") is not True or
            placement.get("isolatedTaint") != config["canary"]["taint"] or
            placement.get("firewallBaselineEmpty") is not True or
            not isinstance(placement.get("nodeUid"), str) or not placement["nodeUid"] or
            not isinstance(placement.get("bootID"), str) or not placement["bootID"]):
        raise ValueError("reviewed placement and empty firewall baseline are required")
    if fresh:
        PLATFORM["fresh_recovery_time"](placement.get("capturedAt"))
        expected = placement.get("systemDaemonSetPods")
        if (not isinstance(expected, list) or
                any(not isinstance(pod, dict) or
                    set(pod) != {"namespace", "name", "uid"} or
                    pod.get("namespace") not in SYSTEM_NAMESPACES or
                    any(not isinstance(value, str) or not value
                        for value in pod.values()) for pod in expected) or
                len({(pod["namespace"], pod["name"], pod["uid"])
                     for pod in expected}) != len(expected)):
            raise ValueError("reviewed system DaemonSet Pod identities are required")


def verify_live_pods(config, placement):
    node_name = config["canary"]["node"]
    listing = CLEANUP["kubernetes_json"]("get", "pods", "-A", "--field-selector",
                                          f"spec.nodeName={node_name}", "--chunk-size=0")
    if not isinstance(listing, dict) or not isinstance(listing.get("items"), list):
        raise ValueError("canary Pod inventory is incomplete")
    actual = []
    for pod in listing["items"]:
        if not isinstance(pod, dict):
            raise ValueError("canary Pod inventory has an invalid entry")
        metadata, spec = pod.get("metadata"), pod.get("spec")
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            raise ValueError("canary Pod inventory has an invalid entry")
        owners = metadata.get("ownerReferences", [])
        if (spec.get("nodeName") != node_name or
                metadata.get("namespace") not in SYSTEM_NAMESPACES or
                not isinstance(owners, list) or
                not any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                        owner.get("controller") is True and
                        isinstance(owner.get("name"), str) and owner["name"] and
                        (owner["name"] == "ztunnel" if
                         metadata["namespace"] == "istio-system" else
                         owner["name"] not in {CLEANUP["ENFORCER"], CLEANUP["CLEANUP"]})
                        for owner in owners)):
            raise ValueError("canary Node has a foreign or unscheduled Pod")
        actual.append((metadata.get("namespace"), metadata.get("name"),
                       metadata.get("uid")))
    expected = {(pod["namespace"], pod["name"], pod["uid"])
                for pod in placement["systemDaemonSetPods"]}
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("canary Node Pod inventory differs from reviewed placement")


def validate_cleanup(cleanup, placement, source_sha):
    if (not isinstance(cleanup, dict) or cleanup.get("format") != 1 or
            cleanup.get("stage") != "owned-firewall-cleanup" or
            cleanup.get("status") != "verified" or cleanup.get("verified") is not True or
            cleanup.get("sourceSha") != source_sha or
            cleanup.get("node") != placement["node"] or
            cleanup.get("nodeUid") != placement["nodeUid"] or
            cleanup.get("bootID") != placement["bootID"] or
            not re.fullmatch(r"[0-9a-f]{64}", cleanup.get("afterSha256", "")) or
            not cleanup.get("completedAt")):
        raise ValueError("verified owned-firewall cleanup receipt is required")


def wait_for_cleanup_pod_deletion(config, placement, pod_name, timeout_seconds=120):
    deadline = time.monotonic() + timeout_seconds
    while True:
        node, labeled, tainted = node_state(config, placement)
        if labeled or not tainted:
            raise ValueError("canary Node lost its release isolation state")
        listing = CLEANUP["kubernetes_json"]("-n", "kube-system", "get", "pods",
                                             "--chunk-size=0")
        if not isinstance(listing, dict) or not isinstance(listing.get("items"), list):
            raise ValueError("cleanup Pod inventory is incomplete")
        cleanup_pods = []
        for pod in listing["items"]:
            if not isinstance(pod, dict) or not isinstance(pod.get("metadata"), dict):
                raise ValueError("cleanup Pod inventory has an invalid entry")
            metadata = pod["metadata"]
            owners = metadata.get("ownerReferences", [])
            labels = metadata.get("labels", {})
            if not isinstance(owners, list) or not isinstance(labels, dict):
                raise ValueError("cleanup Pod ownership is invalid")
            if (metadata.get("name") == pod_name or
                    labels.get("app.kubernetes.io/name") == CLEANUP["CLEANUP"] or
                    any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                        owner.get("name") == CLEANUP["CLEANUP"] for owner in owners)):
                cleanup_pods.append(pod)
        if not cleanup_pods:
            return node
        if time.monotonic() >= deadline:
            raise ValueError("cleanup Pod remains; isolation taint retained")
        time.sleep(2)


def execute(args):
    if args.config.resolve() != CONFIG or not PLATFORM["SHA"].fullmatch(args.expected_sha):
        raise ValueError("canary stage requires committed input and exact source SHA")
    config = PLATFORM["validate_config"](json.loads(args.config.read_text()))
    if config["canary"]["node"] is None:
        raise ValueError("no admitted canary Node configured")
    PLATFORM["protected_context"](args.expected_sha)
    require_current_main(args.expected_sha)
    directory = PLATFORM["private_directory"](args.receipt_dir)
    placement = PLATFORM["read_private_json"](directory / "placement.json")
    validate_placement(placement, config, args.expected_sha, args.action == "admit")
    if args.action == "release":
        validate_cleanup(PLATFORM["read_private_json"](directory / "cleanup.json"),
                         placement, args.expected_sha)
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("canary output already exists")
    node, labeled, tainted = node_state(config, placement)
    require_runtime_absent(args.action == "admit")
    if args.action == "admit":
        if labeled:
            raise ValueError("canary Node is already labeled; review admission state")
    elif labeled != tainted:
        raise ValueError("canary label and isolation taint differ")
    if args.action == "release":
        if not labeled:
            raise ValueError("canary Node is not admitted; live firewall proof unavailable")
        pod, _ = CLEANUP["inspect_cluster"](config, placement)
        remaining, _, _ = CLEANUP["cleanup_plan"](CLEANUP["snapshot"](pod))
        if remaining:
            raise ValueError("owned firewall objects remain")
    record = {"format": 1, "stage": f"canary-{args.action}", "status": "started",
              "verified": False, "sourceSha": args.expected_sha,
              "node": config["canary"]["node"], "nodeUid": placement["nodeUid"],
              "bootID": placement["bootID"], "runId": os.environ["GITHUB_RUN_ID"],
              "startedAt": datetime.now(timezone.utc).isoformat()}
    CLEANUP["write_record"](output, record)
    try:
        if args.action == "admit":
            if not tainted:
                taints = node["spec"].get("taints")
                taint_add = {"op": "add", "path": "/spec/taints/-", "value": TAINT} if taints \
                    else {"op": "add", "path": "/spec/taints", "value": [TAINT]}
                patch(node, [taint_add], args.expected_sha)
            node, labeled, tainted = node_state(config, placement)
            if labeled or not tainted:
                raise ValueError("canary Node taint readback differs")
            require_runtime_absent(True)
            verify_live_pods(config, placement)
            labels = node["metadata"].get("labels")
            label_add = {"op": "add", "path": LABEL_PATH, "value": "true"} if labels \
                else {"op": "add", "path": "/metadata/labels", "value": {CANARY: "true"}}
            patch(node, [label_add], args.expected_sha)
        else:
            if labeled:
                index = next(index for index, item in enumerate(node["spec"].get("taints", []))
                             if item.get("key") == CANARY)
                patch(node, [{"op": "test", "path": LABEL_PATH, "value": "true"},
                             {"op": "test", "path": f"/spec/taints/{index}", "value": TAINT},
                             {"op": "remove", "path": LABEL_PATH}], args.expected_sha)
                node = wait_for_cleanup_pod_deletion(config, placement, pod)
                require_runtime_absent(False)
                index = next(index for index, item in enumerate(node["spec"].get("taints", []))
                             if item.get("key") == CANARY)
                patch(node, [{"op": "test", "path": f"/spec/taints/{index}", "value": TAINT},
                             {"op": "remove", "path": f"/spec/taints/{index}"}],
                      args.expected_sha)
        require_current_main(args.expected_sha)
        node, labeled, tainted = node_state(config, placement)
        if (labeled, tainted) != ((True, True) if args.action == "admit" else (False, False)):
            raise ValueError("canary Node readback differs")
        if args.action == "admit":
            try:
                verify_live_pods(config, placement)
            except (OSError, ValueError, KeyError, TypeError,
                    subprocess.CalledProcessError, subprocess.TimeoutExpired):
                require_runtime_absent(True)
                patch(node, [{"op": "test", "path": LABEL_PATH, "value": "true"},
                             {"op": "remove", "path": LABEL_PATH}], args.expected_sha)
                raise
        record.update({"status": "verified", "verified": True,
                       "resourceVersion": node["metadata"]["resourceVersion"],
                       "completedAt": datetime.now(timezone.utc).isoformat()})
    except (OSError, ValueError, KeyError, TypeError, StopIteration,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        record.update({"status": "interrupted", "verified": False})
        CLEANUP["write_record"](output, record, replace=True)
        raise
    CLEANUP["write_record"](output, record, replace=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("admit", "release"))
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        execute(parser.parse_args())
        print("Canary Node stage verified; private receipt retained")
        return 0
    except (OSError, ValueError, KeyError, TypeError, StopIteration, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Canary Node stage blocked; inspect private receipts", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
