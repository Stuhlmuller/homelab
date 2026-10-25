#!/usr/bin/env python3
"""Admit, release, or recover the reviewed kube-router canary Node in protected CI."""

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


def require_exclusive_canary_label(config, placement, selected):
    listing = CLEANUP["kubernetes_json"]("get", "nodes", "-l", f"{CANARY}=true",
                                         "--chunk-size=0")
    try:
        items = CLEANUP["complete_items"](listing, "canary label")
    except ValueError as exc:
        raise ValueError("canary label inventory is incomplete") from exc
    matches = []
    for item in items:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        labels = metadata.get("labels") if isinstance(metadata, dict) else None
        if (not isinstance(labels, dict) or labels.get(CANARY) != "true" or
                not isinstance(metadata.get("name"), str) or not metadata["name"] or
                not isinstance(metadata.get("uid"), str) or not metadata["uid"]):
            raise ValueError("canary label inventory has an invalid Node")
        matches.append((metadata["name"], metadata["uid"]))
    expected = [(config["canary"]["node"], placement["nodeUid"])] if selected else []
    if matches != expected:
        raise ValueError("canary label matches another Node or changed")


def require_preflight_absent():
    preflight = CLEANUP["command"]("kubectl", "--request-timeout=20s", "-n", "kube-system",
                                    "get", "pod", "kube-router-firewall-baseline",
                                    "--ignore-not-found", "-o", "json")
    preflight_pods = CLEANUP["kubernetes_json"]("-n", "kube-system", "get", "pods", "-l",
                                                "app.kubernetes.io/name=kube-router-firewall-baseline",
                                                "--chunk-size=0")
    if preflight.strip() or CLEANUP["complete_items"](preflight_pods, "preflight Pod"):
        raise ValueError("preflight Pod must be deleted before canary placement")


def require_runtime_absent(admit):
    require_preflight_absent()
    for name in (CLEANUP["ENFORCER"], CLEANUP["CLEANUP"] if admit else None):
        if name is None:
            continue
        daemonset = CLEANUP["command"]("kubectl", "--request-timeout=20s", "-n", "kube-system",
                                       "get", "daemonset", name, "--ignore-not-found", "-o", "json")
        if daemonset.strip():
            raise ValueError("firewall DaemonSet must be absent")
        pods = CLEANUP["kubernetes_json"]("-n", "kube-system", "get", "pods", "-l",
                                          f"app.kubernetes.io/name={name}",
                                          "--chunk-size=0")
        if CLEANUP["complete_items"](pods, "firewall DaemonSet Pod"):
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


def require_fresh_capacity(args, directory):
    if (not isinstance(args.bucket, str) or not args.bucket or
            not re.fullmatch(r"[1-9][0-9]*", args.placement_run_id or "") or
            not isinstance(args.placement_version_id, str) or
            args.placement_version_id in {"", "null"}):
        raise ValueError("canary admission requires the selected placement version")
    subprocess.run([sys.executable, "-I", str(ROOT / "scripts/network-policy-placement.py"),
                    "--config", str(args.config), "--expected-sha", args.expected_sha,
                    "--bucket", args.bucket, "--placement-run-id", args.placement_run_id,
                    "--placement-version-id", args.placement_version_id,
                    "--check-placement", str(directory / "placement.json")],
                   cwd=ROOT, check=True, timeout=300)


def validate_placement(placement, config, source_sha, fresh):
    if (not isinstance(placement, dict) or placement.get("format") != 1 or
            placement.get("verified") is not True or
            placement.get("sourceSha") != source_sha or
            placement.get("node") != config["canary"]["node"] or
            placement.get("canaryNode") != config["canary"]["node"] or
            placement.get("measured") is not True or
            placement.get("isolatedTaint") != config["canary"]["taint"] or
            placement.get("firewallBaselineEmpty") is not True or
            not isinstance(placement.get("placementRunId"), str) or
            not re.fullmatch(r"[1-9][0-9]*", placement["placementRunId"]) or
            placement.get("baselineSourceSha") != source_sha or
            not re.fullmatch(r"[1-9][0-9]*", str(placement.get("baselineRunId", ""))) or
            not re.fullmatch(r"[0-9a-f]{64}",
                             str(placement.get("baselineCaptureSha256", ""))) or
            not isinstance(placement.get("baselineCaptureVersionId"), str) or
            placement["baselineCaptureVersionId"] in {"", "null"} or
            not isinstance(placement.get("baselineCapturedAt"), str) or
            not isinstance(placement.get("nodeUid"), str) or not placement["nodeUid"] or
            not isinstance(placement.get("bootID"), str) or not placement["bootID"]):
        raise ValueError("reviewed placement and empty firewall baseline are required")
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
    if fresh:
        PLATFORM["fresh_recovery_time"](placement.get("capturedAt"))
        baseline_time = placement.get("baselineCapturedAt")
        if not isinstance(baseline_time, str) or not re.fullmatch(
                r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", baseline_time):
            raise ValueError("reviewed firewall capture timestamp is missing")
        captured = datetime.strptime(baseline_time, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        if not 0 <= (datetime.now(timezone.utc) - captured).total_seconds() <= 3600:
            raise ValueError("reviewed firewall capture is stale")
        placement_time = datetime.strptime(placement["capturedAt"],
                                           "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if (captured > placement_time or
                (datetime.now(timezone.utc) - placement_time).total_seconds() > 1800):
            raise ValueError("reviewed placement is stale")


def verify_live_pods(config, placement):
    node_name = config["canary"]["node"]
    listing = CLEANUP["kubernetes_json"]("get", "pods", "-A", "--field-selector",
                                          f"spec.nodeName={node_name}", "--chunk-size=0")
    actual = []
    for pod in CLEANUP["complete_items"](listing, "canary Pod"):
        if not isinstance(pod, dict):
            raise ValueError("canary Pod inventory has an invalid entry")
        metadata, spec = pod.get("metadata"), pod.get("spec")
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            raise ValueError("canary Pod inventory has an invalid entry")
        owners = metadata.get("ownerReferences", [])
        if (spec.get("nodeName") != node_name or
                metadata.get("namespace") not in SYSTEM_NAMESPACES or
                metadata.get("deletionTimestamp") or
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


def validate_cleanup(cleanup, ownership, placement, config, source_sha):
    if (not isinstance(ownership, dict) or ownership.get("format") != 1 or
            ownership.get("verified") is not True or
            ownership.get("sourceSha") != source_sha or
            not isinstance(ownership.get("evidenceSourceSha"), str) or
            not PLATFORM["SHA"].fullmatch(ownership["evidenceSourceSha"]) or
            ownership.get("node") != config["canary"]["node"] or
            ownership.get("nodeUid") != placement["nodeUid"] or
            ownership.get("bootID") != placement["bootID"] or
            ownership.get("placementRunId") != placement.get("placementRunId") or
            not isinstance(ownership.get("placementVersionId"), str) or
            ownership["placementVersionId"] in {"", "null"} or
            not isinstance(ownership.get("captureRunId"), str) or
            not re.fullmatch(r"[1-9][0-9]*", ownership["captureRunId"]) or
            not re.fullmatch(r"[0-9a-f]{64}", str(ownership.get("snapshotSha256", ""))) or
            not isinstance(ownership.get("reviewedAt"), str) or
            not ownership["reviewedAt"]):
        raise ValueError("reviewed firewall ownership receipt is required for release")
    validate_placement(placement, config, ownership["evidenceSourceSha"], False)
    CLEANUP["require_placement_selection"](ownership, placement)
    CLEANUP["require_firewall_removal_transition"](ownership["evidenceSourceSha"], source_sha)
    if (not isinstance(cleanup, dict) or cleanup.get("format") != 1 or
            cleanup.get("stage") != "owned-firewall-cleanup" or
            cleanup.get("status") != "verified" or cleanup.get("verified") is not True or
            cleanup.get("sourceSha") != source_sha or
            cleanup.get("captureRunId") != ownership["captureRunId"] or
            cleanup.get("beforeSha256") != ownership["snapshotSha256"] or
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
        cleanup_pods = []
        for pod in CLEANUP["complete_items"](listing, "cleanup Pod"):
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


def validate_recovery_receipts(attempt, proof, placement, args, config):
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    admission_run_id = getattr(args, "admission_run_id", None)
    placement_run_id = getattr(args, "placement_run_id", None)
    placement_version_id = getattr(args, "placement_version_id", None)
    if (not isinstance(admission_run_id, str) or
            not re.fullmatch(r"[1-9][0-9]*", admission_run_id) or
            not isinstance(placement_run_id, str) or
            not re.fullmatch(r"[1-9][0-9]*", placement_run_id) or
            not isinstance(placement_version_id, str) or
            placement_version_id in {"", "null"} or
            not re.fullmatch(r"[1-9][0-9]*", run_id) or
            placement["placementRunId"] != placement_run_id):
        raise ValueError("canary recovery selection is invalid")
    identity = {"node": config["canary"]["node"],
                "nodeUid": placement["nodeUid"], "bootID": placement["bootID"]}
    selection = {"placementRunId": placement_run_id,
                 "placementVersionId": placement_version_id}
    if (not isinstance(attempt, dict) or attempt.get("format") != 1 or
            attempt.get("stage") != "canary-admit" or
            attempt.get("status") != "attempted" or
            attempt.get("verified") is not False or
            attempt.get("sourceSha") != args.expected_sha or
            attempt.get("runId") != admission_run_id or
            any(attempt.get(key) != value for key, value in
                (identity | selection).items())):
        raise ValueError("selected admission attempt is missing or unrelated")
    capture_key = (f"openclaw-enterprise/platform/{args.expected_sha}/{run_id}/"
                   "firewall-recovery-capture.json")
    if (not isinstance(proof, dict) or proof.get("format") != 1 or
            proof.get("stage") != "firewall-recovery-proof" or
            proof.get("status") != "verified" or proof.get("verified") is not True or
            proof.get("sourceSha") != args.expected_sha or
            proof.get("runId") != run_id or
            proof.get("admissionRunId") != admission_run_id or
            any(proof.get(key) != value for key, value in
                (identity | selection).items()) or
            proof.get("firewallBaselineEmpty") is not True or
            proof.get("ownedChains") != 0 or proof.get("ownedSets") != 0 or
            proof.get("podDeleted") is not True or
            not isinstance(proof.get("snapshotSha256"), str) or
            not re.fullmatch(r"[0-9a-f]{64}", proof["snapshotSha256"]) or
            proof.get("captureKey") != capture_key):
        raise ValueError("same-run empty firewall recovery proof is missing or unrelated")
    completed = proof.get("completedAt")
    if not isinstance(completed, str):
        raise ValueError("firewall recovery proof has no completion time")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(completed)).total_seconds()
    except (TypeError, ValueError) as error:
        raise ValueError("firewall recovery proof has invalid completion time") from error
    if not 0 <= age <= 300:
        raise ValueError("firewall recovery proof is stale or in the future")


def recover(args):
    if args.config.resolve() != CONFIG or not PLATFORM["SHA"].fullmatch(args.expected_sha):
        raise ValueError("canary recovery requires committed input and exact source SHA")
    config = PLATFORM["validate_config"](json.loads(args.config.read_text()))
    if config["canary"]["node"] is None:
        raise ValueError("no admitted canary Node configured")
    PLATFORM["protected_context"](args.expected_sha)
    require_current_main(args.expected_sha)
    directory = PLATFORM["private_directory"](args.receipt_dir)
    placement = PLATFORM["read_private_json"](directory / "placement.json")
    validate_placement(placement, config, args.expected_sha, False)
    attempt = PLATFORM["read_private_json"](directory / "admission-attempt.json")
    proof = PLATFORM["read_private_json"](directory / "firewall-recovery-proof.json")
    validate_recovery_receipts(attempt, proof, placement, args, config)
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("canary recovery output already exists")
    node, labeled, tainted = node_state(config, placement)
    if labeled and not tainted:
        raise ValueError("unisolated canary label is not recoverable")
    require_runtime_absent(True)
    verify_live_pods(config, placement)
    require_exclusive_canary_label(config, placement, labeled)
    record = {"format": 1, "stage": "canary-admit-recover", "status": "started",
              "verified": False, "sourceSha": args.expected_sha,
              "runId": os.environ["GITHUB_RUN_ID"],
              "admissionRunId": args.admission_run_id,
              "placementRunId": args.placement_run_id,
              "placementVersionId": args.placement_version_id,
              "firewallCaptureKey": proof["captureKey"],
              "firewallSnapshotSha256": proof["snapshotSha256"],
              "node": config["canary"]["node"], "nodeUid": placement["nodeUid"],
              "bootID": placement["bootID"],
              "startedAt": datetime.now(timezone.utc).isoformat()}
    CLEANUP["write_record"](output, record)
    try:
        if labeled:
            index = next(index for index, item in enumerate(node["spec"]["taints"])
                         if item.get("key") == CANARY)
            patch(node, [{"op": "test", "path": LABEL_PATH, "value": "true"},
                         {"op": "test", "path": f"/spec/taints/{index}", "value": TAINT},
                         {"op": "remove", "path": LABEL_PATH}], args.expected_sha)
            node, labeled, tainted = node_state(config, placement)
            if labeled or not tainted:
                raise ValueError("canary recovery label readback differs")
            require_runtime_absent(True)
            verify_live_pods(config, placement)
            require_exclusive_canary_label(config, placement, False)
        if tainted:
            index = next(index for index, item in enumerate(node["spec"]["taints"])
                         if item.get("key") == CANARY)
            patch(node, [{"op": "test", "path": f"/spec/taints/{index}", "value": TAINT},
                         {"op": "remove", "path": f"/spec/taints/{index}"}],
                  args.expected_sha)
        require_current_main(args.expected_sha)
        node, labeled, tainted = node_state(config, placement)
        if labeled or tainted:
            raise ValueError("canary recovery Node readback differs")
        require_runtime_absent(True)
        verify_live_pods(config, placement)
        require_exclusive_canary_label(config, placement, False)
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
    if args.action == "release":
        if args.placement_run_id or args.placement_version_id:
            raise ValueError("release selection is bound by reviewed ownership")
        validate_cleanup(PLATFORM["read_private_json"](directory / "cleanup.json"),
                         PLATFORM["read_private_json"](directory / "firewall-ownership.json"),
                         placement, config, args.expected_sha)
    else:
        validate_placement(placement, config, args.expected_sha, True)
        if placement["placementRunId"] != args.placement_run_id:
            raise ValueError("selected placement run differs from loaded receipt")
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("canary output already exists")
    node, labeled, tainted = node_state(config, placement)
    require_runtime_absent(args.action == "admit")
    if args.action == "admit":
        if labeled:
            raise ValueError("canary Node is already labeled; review admission state")
        require_exclusive_canary_label(config, placement, False)
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
    if args.action == "admit":
        record.update(placementRunId=args.placement_run_id,
                      placementVersionId=args.placement_version_id)
    CLEANUP["write_record"](output, record)
    try:
        if args.action == "admit":
            require_fresh_capacity(args, directory)
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
            require_exclusive_canary_label(config, placement, False)
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
                verify_live_pods(config, placement)
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
                require_exclusive_canary_label(config, placement, True)
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
    parser.add_argument("action", choices=("admit", "release", "recover"))
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--bucket")
    parser.add_argument("--placement-run-id")
    parser.add_argument("--placement-version-id")
    parser.add_argument("--admission-run-id")
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args()
        if args.action == "recover":
            recover(args)
        else:
            if args.admission_run_id:
                raise ValueError("admission run applies only to canary recovery")
            execute(args)
        print("Canary Node stage verified; private receipt retained")
        return 0
    except (OSError, ValueError, KeyError, TypeError, StopIteration, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Canary Node stage blocked; inspect private receipts", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
