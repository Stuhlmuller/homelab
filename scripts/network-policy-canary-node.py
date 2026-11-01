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
OWNERSHIP = runpy.run_path(str(ROOT / "scripts/network-policy-ownership.py"))
CANARY = CLEANUP["CANARY"]
TAINT = {"key": CANARY, "value": "true", "effect": "NoSchedule"}
LABEL_PATH = "/metadata/labels/" + CANARY.replace("~", "~0").replace("/", "~1")
ADMISSION = "homelab.stinkyboi.com/network-policy-canary-admission"
ADMISSION_PATH = "/metadata/annotations/" + ADMISSION.replace("/", "~1")
SYSTEM_NAMESPACES = {"kube-system", "istio-system"}
FIXTURE_NODE = "zimaboard-1"


def require_current_main(source_sha):
    CLEANUP["require_current_main"](source_sha)


def node_state(config, placement):
    node = CLEANUP["kubernetes_json"]("get", "node", config["canary"]["node"])
    metadata, spec = node["metadata"], node["spec"]
    labels, taints = metadata.get("labels", {}), spec.get("taints", [])
    annotations = metadata.get("annotations", {})
    if (metadata.get("name") != config["canary"]["node"] or
            metadata.get("uid") != placement["nodeUid"] or
            node["status"].get("nodeInfo", {}).get("bootID") != placement["bootID"] or
            not isinstance(metadata.get("resourceVersion"), str) or
            not metadata["resourceVersion"] or not isinstance(labels, dict) or
            not isinstance(annotations, dict) or
            not isinstance(taints, list) or
            any(not isinstance(item, dict) for item in taints) or
            metadata.get("deletionTimestamp") or spec.get("unschedulable") is True or
            not CLEANUP["ready"](node)):
        raise ValueError("canary Node identity, readiness, or shape changed")
    owned = [item for item in taints if item.get("key") == CANARY]
    if (len(owned) > 1 or owned and owned[0] != TAINT or
            labels.get(CANARY) not in (None, "true") or
            (ADMISSION in annotations) != bool(owned)):
        raise ValueError("unexpected canary label or taint")
    return node, labels.get(CANARY) == "true", bool(owned)


def admission_marker(source_sha, run_id):
    return f"{source_sha}:{run_id}"


def require_admission_marker(node, source_sha, run_id):
    if node["metadata"].get("annotations", {}).get(ADMISSION) != admission_marker(
            source_sha, run_id):
        raise ValueError("canary admission marker differs from selected receipt")


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


def require_runtime_absent(admit, allow_reviewed_fixtures=False):
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
    if not allow_reviewed_fixtures:
        namespace = CLEANUP["command"]("kubectl", "--request-timeout=20s", "get", "namespace",
                                       "network-policy-canary", "--ignore-not-found", "-o", "json")
        if namespace.strip():
            raise ValueError("canary fixture namespace must be absent")


def require_release_runtime_quiesced(config, placement, cleanup_pod_uid):
    """The cleanup controller remains installed, but must have no Pods."""
    require_runtime_absent(False)
    if not isinstance(cleanup_pod_uid, str) or not cleanup_pod_uid:
        raise ValueError("selected cleanup Pod UID is missing")
    daemonset = CLEANUP["kubernetes_json"]("-n", "kube-system", "get", "daemonset",
                                          CLEANUP["CLEANUP"])
    if not isinstance(daemonset, dict):
        raise ValueError("cleanup DaemonSet has invalid shape")
    metadata = daemonset.get("metadata", {})
    spec = daemonset.get("spec", {})
    status = daemonset.get("status", {})
    if not all(isinstance(item, dict) for item in (metadata, spec, status)):
        raise ValueError("cleanup DaemonSet has invalid shape")
    pod_template = spec.get("template", {})
    if not isinstance(pod_template, dict):
        raise ValueError("cleanup DaemonSet has invalid Pod template")
    selector = spec.get("selector", {})
    if not isinstance(selector, dict):
        raise ValueError("cleanup DaemonSet has invalid selector")
    template = pod_template.get("spec", {})
    if not isinstance(template, dict):
        raise ValueError("cleanup DaemonSet has invalid Pod template")
    containers = template.get("containers", [])
    container = containers[0] if isinstance(containers, list) and len(containers) == 1 else {}
    if not isinstance(container, dict):
        raise ValueError("cleanup DaemonSet has invalid container")
    security_context = container.get("securityContext", {})
    if not isinstance(security_context, dict):
        raise ValueError("cleanup DaemonSet has invalid container security")
    if (metadata.get("name") != CLEANUP["CLEANUP"] or
            metadata.get("deletionTimestamp") or
            selector.get("matchLabels") !=
            {"app.kubernetes.io/name": CLEANUP["CLEANUP"]} or
            template.get("nodeSelector") != {CANARY: "true"} or
            template.get("automountServiceAccountToken") is not False or
            template.get("hostNetwork") is not True or
            container.get("image") != CLEANUP["IMAGE"] or
            container.get("command") != ["/bin/sh", "-c"] or
            container.get("args") != ["sleep 86400"] or
            security_context.get("privileged") is not True or
            type(status.get("desiredNumberScheduled")) is not int or
            status["desiredNumberScheduled"] != 0 or
            type(status.get("numberReady")) is not int or
            status["numberReady"] != 0):
        raise ValueError("cleanup DaemonSet is not the reviewed dormant source")
    listing = CLEANUP["kubernetes_json"]("-n", "kube-system", "get", "pods",
                                         "--chunk-size=0")
    for pod in CLEANUP["complete_items"](listing, "cleanup Pod"):
        pod_metadata = pod.get("metadata") if isinstance(pod, dict) else None
        if not isinstance(pod_metadata, dict):
            raise ValueError("cleanup Pod inventory has an invalid entry")
        labels = pod_metadata.get("labels", {})
        owners = pod_metadata.get("ownerReferences", [])
        if not isinstance(labels, dict) or not isinstance(owners, list):
            raise ValueError("cleanup Pod ownership is invalid")
        if (pod_metadata.get("uid") == cleanup_pod_uid or
                labels.get("app.kubernetes.io/name") == CLEANUP["CLEANUP"] or
                any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                    owner.get("name") == CLEANUP["CLEANUP"] for owner in owners)):
            raise ValueError("cleanup Pod still exists")
    require_exclusive_canary_label(config, placement, False)


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
            not isinstance(placement.get("bootID"), str) or not placement["bootID"] or
            placement.get("fixtureNode") != FIXTURE_NODE or
            FIXTURE_NODE == config["canary"]["node"] or
            not isinstance(placement.get("fixtureNodeUid"), str) or
            not placement["fixtureNodeUid"] or
            not isinstance(placement.get("fixtureBootID"), str) or
            not placement["fixtureBootID"] or
            placement.get("fixtureNodeUid") == placement.get("nodeUid") or
            not isinstance(placement.get("fixtureCapacity"), dict) or
            type(placement["fixtureCapacity"].get("fixtureImageCached")) is not bool):
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


def verify_live_pods(config, placement, fixture_client_uid=None):
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
        if (fixture_client_uid is not None and
                metadata.get("namespace") == "network-policy-canary" and
                metadata.get("name") == "npq-client"):
            if (not isinstance(fixture_client_uid, str) or not fixture_client_uid or
                    metadata.get("uid") != fixture_client_uid or
                    metadata.get("deletionTimestamp") or
                    metadata.get("ownerReferences") or
                    spec.get("nodeName") != node_name or
                    pod.get("status", {}).get("phase") != "Running" or
                    not CLEANUP["ready"](pod)):
                raise ValueError("canary fixture client identity or readiness differs")
            actual.append((metadata["namespace"], metadata["name"], metadata["uid"]))
            continue
        owners = metadata.get("ownerReferences", [])
        if (spec.get("nodeName") != node_name or
                metadata.get("namespace") not in SYSTEM_NAMESPACES or
                metadata.get("deletionTimestamp") or
                not isinstance(owners, list) or
                not any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                        owner.get("controller") is True and
                        isinstance(owner.get("name"), str) and owner["name"] and
                        (owner["name"] in CLEANUP["ISTIO_SYSTEM_DAEMONSETS"] if
                         metadata["namespace"] == "istio-system" else
                         owner["name"] not in {CLEANUP["ENFORCER"], CLEANUP["CLEANUP"]})
                        for owner in owners)):
            raise ValueError("canary Node has a foreign or unscheduled Pod")
        actual.append((metadata.get("namespace"), metadata.get("name"),
                       metadata.get("uid")))
    expected = {(pod["namespace"], pod["name"], pod["uid"])
                for pod in placement["systemDaemonSetPods"]}
    if fixture_client_uid is not None:
        expected.add(("network-policy-canary", "npq-client", fixture_client_uid))
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("canary Node Pod inventory differs from reviewed placement")


def clean_release_pods(config, expected=None):
    """Record a complete, stable post-untaint Pod inventory without mutating it."""
    listing = CLEANUP["kubernetes_json"]("get", "pods", "-A", "--field-selector",
                                         f"spec.nodeName={config['canary']['node']}",
                                         "--chunk-size=0")
    forbidden = {CLEANUP["ENFORCER"], CLEANUP["CLEANUP"],
                 "kube-router-firewall-baseline"}
    actual = []
    for pod in CLEANUP["complete_items"](listing, "clean canary Pod"):
        metadata = pod.get("metadata") if isinstance(pod, dict) else None
        spec = pod.get("spec") if isinstance(pod, dict) else None
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            raise ValueError("clean canary Pod inventory has invalid entry")
        labels = metadata.get("labels", {})
        owners = metadata.get("ownerReferences", [])
        identity = {key: metadata.get(key) for key in ("namespace", "name", "uid")}
        if (spec.get("nodeName") != config["canary"]["node"] or
                any(not isinstance(value, str) or not value for value in identity.values()) or
                metadata.get("deletionTimestamp") or
                not isinstance(labels, dict) or not isinstance(owners, list) or
                any(not isinstance(owner, dict) for owner in owners) or
                metadata.get("name") in forbidden or
                labels.get("app.kubernetes.io/name") in forbidden or
                any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                    owner.get("name") in forbidden for owner in owners)):
            raise ValueError("clean canary Pod inventory has forbidden or changed workload")
        actual.append(identity)
    actual.sort(key=lambda item: (item["namespace"], item["name"], item["uid"]))
    if len({(item["namespace"], item["name"], item["uid"]) for item in actual}) != len(actual):
        raise ValueError("clean canary Pod inventory contains duplicates")
    if expected is not None and actual != expected:
        raise ValueError("clean canary Pod inventory changed since firewall proof")
    return actual


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
    if (not isinstance(args.evidence_source_sha, str) or
            not PLATFORM["SHA"].fullmatch(args.evidence_source_sha) or
            not isinstance(admission_run_id, str) or
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
            attempt.get("sourceSha") != args.evidence_source_sha or
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
            proof.get("evidenceSourceSha") != args.evidence_source_sha or
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


def validate_abort_receipt(admission, placement, args, config):
    if (not isinstance(admission, dict) or admission.get("format") != 1 or
            admission.get("stage") != "canary-admit" or
            admission.get("status") != "verified" or admission.get("verified") is not True or
            admission.get("sourceSha") != args.evidence_source_sha or
            admission.get("runId") != args.admission_run_id or
            admission.get("node") != config["canary"]["node"] or
            admission.get("nodeUid") != placement["nodeUid"] or
            admission.get("bootID") != placement["bootID"] or
            admission.get("placementRunId") != args.placement_run_id or
            admission.get("placementVersionId") != args.placement_version_id or
            not isinstance(admission.get("resourceVersion"), str) or
            not admission["resourceVersion"] or
            not isinstance(admission.get("completedAt"), str) or
            not admission["completedAt"]):
        raise ValueError("selected verified canary admission is missing or unrelated")


def require_unchanged_canary_source(evidence_sha, source_sha, paths):
    ancestors = subprocess.check_output(
        ["git", "--no-replace-objects", "rev-list", "--first-parent", source_sha],
        cwd=ROOT, text=True, timeout=30).splitlines()
    if evidence_sha not in ancestors:
        raise ValueError("selected source is not an ancestor of current first-parent main")
    for relative in paths:
        original = subprocess.check_output(
            ["git", "--no-replace-objects", "show", f"{evidence_sha}:{relative}"],
            cwd=ROOT, timeout=15)
        if original != (ROOT / relative).read_bytes():
            raise ValueError("canary source changed after selected receipt")


ABORT_SOURCE_PATHS = (
        "clusters/homelab/platform/network-policy/preflight/pod.json",
        "clusters/homelab/platform/network-policy/daemonset.yaml",
        "clusters/homelab/platform/network-policy/canary/fixtures.yaml",
        "clusters/homelab/platform/network-policy/kustomization.yaml",
        "clusters/homelab/platform/network-policy/canary/kustomization.yaml",
        "IaC/homelab/us-west-2/apps/platform-network-policy/stack.hcl",
        "IaC/homelab/us-west-2/apps/platform-network-policy-canary/stack.hcl",
)
RELEASE_SOURCE_PATHS = (*ABORT_SOURCE_PATHS,
    "clusters/homelab/platform/network-policy/cleanup/daemonset.yaml",
    "clusters/homelab/platform/network-policy/cleanup/kustomization.yaml",
    "IaC/homelab/us-west-2/apps/platform-network-policy-cleanup/stack.hcl",
)


def require_abort_source(config, evidence_sha, source_sha):
    if config["activationEnabled"] is not False or config["canary"]["node"] != "zimaboard-2":
        raise ValueError("abort requires the reviewed pre-activation configuration")
    require_unchanged_canary_source(evidence_sha, source_sha, ABORT_SOURCE_PATHS)


def require_release_source(config, release_sha, source_sha):
    if config["canary"]["node"] != "zimaboard-2":
        raise ValueError("release recovery requires the reviewed canary Node")
    require_unchanged_canary_source(release_sha, source_sha, RELEASE_SOURCE_PATHS)
    old_config = json.loads(subprocess.check_output(
        ["git", "--no-replace-objects", "show",
         f"{release_sha}:scripts/config/platform-maintenance.json"],
        cwd=ROOT, timeout=15))
    if (not isinstance(old_config, dict) or
            old_config.get("canary") != config["canary"] or
            old_config.get("activationEnabled") != config["activationEnabled"] or
            old_config.get("activationAdmission") != config.get("activationAdmission")):
        raise ValueError("canary release configuration changed after selected receipt")


def validate_release_recovery_receipts(release_attempt, recovery_attempt, proof,
                                       cleanup, ownership, placement, args, config):
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if (not PLATFORM["SHA"].fullmatch(args.release_source_sha or "") or
            not re.fullmatch(r"[1-9][0-9]*", args.release_run_id or "") or
            not re.fullmatch(r"[1-9][0-9]*", args.cleanup_run_id or "") or
            not re.fullmatch(r"[1-9][0-9]*", args.admission_run_id or "") or
            not re.fullmatch(r"[1-9][0-9]*", run_id) or
            args.evidence_source_sha != ownership["evidenceSourceSha"] or
            args.admission_run_id != ownership["admissionRunId"]):
        raise ValueError("release recovery selection is invalid")
    validate_cleanup(cleanup, ownership, placement, config, args.release_source_sha)
    if not isinstance(cleanup.get("cleanupPodUid"), str) or not cleanup["cleanupPodUid"]:
        raise ValueError("verified cleanup Pod UID is missing")
    selected = {"evidenceSourceSha": ownership["evidenceSourceSha"],
                "admissionRunId": ownership["admissionRunId"],
                "captureRunId": ownership["captureRunId"],
                "cleanupRunId": args.cleanup_run_id,
                "cleanupPodUid": cleanup["cleanupPodUid"],
                "placementRunId": placement["placementRunId"],
                "placementVersionId": ownership["placementVersionId"],
                "node": config["canary"]["node"],
                "nodeUid": placement["nodeUid"], "bootID": placement["bootID"]}
    if (not isinstance(release_attempt, dict) or release_attempt.get("format") != 1 or
            release_attempt.get("stage") != "canary-release" or
            release_attempt.get("status") != "attempted" or
            release_attempt.get("verified") is not False or
            release_attempt.get("sourceSha") != args.release_source_sha or
            release_attempt.get("runId") != args.release_run_id or
            any(release_attempt.get(key) != value for key, value in selected.items())):
        raise ValueError("selected release attempt is missing or unrelated")
    recovery_selected = {**selected, "releaseSourceSha": args.release_source_sha,
                         "releaseRunId": args.release_run_id}
    if (not isinstance(recovery_attempt, dict) or recovery_attempt.get("format") != 1 or
            recovery_attempt.get("stage") != "canary-release-recover" or
            recovery_attempt.get("status") != "attempted" or
            recovery_attempt.get("verified") is not False or
            recovery_attempt.get("sourceSha") != args.expected_sha or
            recovery_attempt.get("runId") != run_id or
            not re.fullmatch(r"[0-9a-f]{48}", str(recovery_attempt.get("podToken", ""))) or
            any(recovery_attempt.get(key) != value for key, value in
                recovery_selected.items())):
        raise ValueError("release recovery probe attempt is missing or unrelated")
    capture_key = (f"openclaw-enterprise/platform/{args.expected_sha}/{run_id}/"
                   "firewall-recovery-capture.json")
    if (not isinstance(proof, dict) or proof.get("format") != 1 or
            proof.get("stage") != "firewall-release-recovery-proof" or
            proof.get("status") != "verified" or proof.get("verified") is not True or
            proof.get("sourceSha") != args.expected_sha or
            proof.get("runId") != run_id or
            any(proof.get(key) != value for key, value in recovery_selected.items()) or
            proof.get("firewallBaselineEmpty") is not True or
            proof.get("ownedChains") != 0 or proof.get("ownedSets") != 0 or
            proof.get("podDeleted") is not True or
            proof.get("observedState") not in {"taint-only", "clean"} or
            (proof.get("observedState") == "clean" and
             not isinstance(proof.get("observedPods"), list)) or
            not re.fullmatch(r"[0-9a-f]{64}", str(proof.get("snapshotSha256", ""))) or
            proof.get("captureKey") != capture_key):
        raise ValueError("same-run empty release firewall proof is missing or unrelated")
    try:
        age = (datetime.now(timezone.utc) -
               datetime.fromisoformat(proof["completedAt"])).total_seconds()
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("release firewall proof has invalid completion time") from error
    if not 0 <= age <= 300:
        raise ValueError("release firewall proof is stale or in the future")


def release_recover(args):
    if args.config.resolve() != CONFIG or not PLATFORM["SHA"].fullmatch(args.expected_sha):
        raise ValueError("release recovery requires committed input and exact source SHA")
    PLATFORM["require_reviewed_execution_config"](args.config, args.expected_sha)
    config = PLATFORM["validate_config"](json.loads(args.config.read_text()))
    PLATFORM["protected_context"](args.expected_sha)
    OWNERSHIP["require_owner_attestation"]()
    require_current_main(args.expected_sha)
    directory = PLATFORM["private_directory"](args.receipt_dir)
    placement = PLATFORM["read_private_json"](directory / "placement.json")
    ownership = PLATFORM["read_private_json"](directory / "firewall-ownership.json")
    cleanup = PLATFORM["read_private_json"](directory / "cleanup.json")
    release_attempt = PLATFORM["read_private_json"](directory / "release-attempt.json")
    recovery_attempt = PLATFORM["read_private_json"](directory / "recovery-attempt.json")
    proof = PLATFORM["read_private_json"](directory / "firewall-recovery-proof.json")
    require_release_source(config, args.release_source_sha, args.expected_sha)
    validate_release_recovery_receipts(release_attempt, recovery_attempt, proof, cleanup,
                                       ownership, placement, args, config)
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("release recovery output already exists")
    node, labeled, tainted = node_state(config, placement)
    observed_state = proof["observedState"]
    if labeled or tainted != (observed_state == "taint-only"):
        raise ValueError("release recovery Node isolation state changed since proof")
    if tainted:
        require_admission_marker(node, ownership["evidenceSourceSha"],
                                 ownership["admissionRunId"])
    require_release_runtime_quiesced(config, placement, cleanup["cleanupPodUid"])
    if observed_state == "clean":
        clean_release_pods(config, proof["observedPods"])
    else:
        verify_live_pods(config, placement)
    record = {"format": 1, "stage": "canary-release-recover", "status": "started",
              "verified": False, "sourceSha": args.expected_sha,
              "releaseSourceSha": args.release_source_sha,
              "releaseRunId": args.release_run_id, "cleanupRunId": args.cleanup_run_id,
              "admissionRunId": ownership["admissionRunId"],
              "observedState": observed_state, "mutationPerformed": False,
              "firewallCaptureKey": proof["captureKey"],
              "firewallSnapshotSha256": proof["snapshotSha256"],
              "node": config["canary"]["node"], "nodeUid": placement["nodeUid"],
              "bootID": placement["bootID"], "runId": os.environ["GITHUB_RUN_ID"],
              "startedAt": datetime.now(timezone.utc).isoformat()}
    CLEANUP["write_record"](output, record)
    try:
        require_release_source(config, args.release_source_sha, args.expected_sha)
        if tainted:
            index = next(index for index, item in enumerate(node["spec"]["taints"])
                         if item.get("key") == CANARY)
            patch(node, [{"op": "test", "path": f"/spec/taints/{index}", "value": TAINT},
                         {"op": "test", "path": ADMISSION_PATH, "value":
                          admission_marker(ownership["evidenceSourceSha"],
                                           ownership["admissionRunId"])},
                         {"op": "remove", "path": ADMISSION_PATH},
                         {"op": "remove", "path": f"/spec/taints/{index}"}], args.expected_sha)
            record["mutationPerformed"] = True
        require_current_main(args.expected_sha)
        node, labeled, tainted = node_state(config, placement)
        if labeled or tainted:
            raise ValueError("release recovery Node readback differs")
        require_release_runtime_quiesced(config, placement, cleanup["cleanupPodUid"])
        if observed_state == "clean":
            clean_release_pods(config, proof["observedPods"])
        else:
            verify_live_pods(config, placement)
        record.update({"status": "verified", "verified": True,
                       "observedClean": observed_state == "clean",
                       "resourceVersion": node["metadata"]["resourceVersion"],
                       "completedAt": datetime.now(timezone.utc).isoformat()})
    except (OSError, ValueError, KeyError, TypeError, StopIteration,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        record.update({"status": "interrupted", "verified": False})
        CLEANUP["write_record"](output, record, replace=True)
        raise
    CLEANUP["write_record"](output, record, replace=True)
    return record


def recover(args):
    if args.config.resolve() != CONFIG or not PLATFORM["SHA"].fullmatch(args.expected_sha):
        raise ValueError("canary recovery requires committed input and exact source SHA")
    config = PLATFORM["validate_config"](json.loads(args.config.read_text()))
    if config["canary"]["node"] is None:
        raise ValueError("no admitted canary Node configured")
    PLATFORM["protected_context"](args.expected_sha)
    require_current_main(args.expected_sha)
    abort = args.action == "abort"
    if abort:
        OWNERSHIP["require_owner_attestation"]()
        require_abort_source(config, args.evidence_source_sha, args.expected_sha)
    elif getattr(args, "admission_version_id", None):
        raise ValueError("admission version applies only to verified abort")
    directory = PLATFORM["private_directory"](args.receipt_dir)
    placement = PLATFORM["read_private_json"](directory / "placement.json")
    validate_placement(placement, config, args.evidence_source_sha, False)
    attempt = PLATFORM["read_private_json"](directory / "admission-attempt.json")
    proof = PLATFORM["read_private_json"](directory / "firewall-recovery-proof.json")
    validate_recovery_receipts(attempt, proof, placement, args, config)
    if abort:
        if (not isinstance(args.admission_version_id, str) or
                args.admission_version_id in {"", "null"} or not args.bucket):
            raise ValueError("abort requires the exact verified admission version")
        admission = PLATFORM["read_private_json"](directory / "admission.json")
        validate_abort_receipt(admission, placement, args, config)
        key = (f"openclaw-enterprise/platform/{args.evidence_source_sha}/"
               f"{args.admission_run_id}/canary-admit.json")
        store = OWNERSHIP["PrivateStore"](args.bucket)
        if (store.version(key, True) != args.admission_version_id or
                json.loads(store.read(key, 1048576)) != admission or
                store.version(key, True) != args.admission_version_id):
            raise ValueError("selected admission version or content changed")
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("canary recovery output already exists")
    node, labeled, tainted = node_state(config, placement)
    if labeled and not tainted:
        raise ValueError("unisolated canary label is not recoverable")
    if tainted:
        require_admission_marker(node, args.evidence_source_sha, args.admission_run_id)
    require_runtime_absent(True)
    verify_live_pods(config, placement)
    require_exclusive_canary_label(config, placement, labeled)
    record = {"format": 1, "stage": "canary-abort" if abort else "canary-admit-recover",
              "status": "started",
              "verified": False, "sourceSha": args.expected_sha,
              "evidenceSourceSha": args.evidence_source_sha,
              "runId": os.environ["GITHUB_RUN_ID"],
              "admissionRunId": args.admission_run_id,
              "placementRunId": args.placement_run_id,
              "placementVersionId": args.placement_version_id,
              "firewallCaptureKey": proof["captureKey"],
              "firewallSnapshotSha256": proof["snapshotSha256"],
              "node": config["canary"]["node"], "nodeUid": placement["nodeUid"],
              "bootID": placement["bootID"],
              "startedAt": datetime.now(timezone.utc).isoformat()}
    if abort:
        record["admissionVersionId"] = args.admission_version_id
    CLEANUP["write_record"](output, record)
    try:
        if labeled:
            index = next(index for index, item in enumerate(node["spec"]["taints"])
                         if item.get("key") == CANARY)
            patch(node, [{"op": "test", "path": LABEL_PATH, "value": "true"},
                         {"op": "test", "path": ADMISSION_PATH, "value":
                          admission_marker(args.evidence_source_sha, args.admission_run_id)},
                         {"op": "test", "path": f"/spec/taints/{index}", "value": TAINT},
                         {"op": "remove", "path": LABEL_PATH}], args.expected_sha)
            node, labeled, tainted = node_state(config, placement)
            if labeled or not tainted:
                raise ValueError("canary recovery label readback differs")
            require_runtime_absent(True)
            verify_live_pods(config, placement)
            require_exclusive_canary_label(config, placement, False)
        if tainted:
            if abort:
                require_abort_source(config, args.evidence_source_sha, args.expected_sha)
            index = next(index for index, item in enumerate(node["spec"]["taints"])
                         if item.get("key") == CANARY)
            patch(node, [{"op": "test", "path": f"/spec/taints/{index}", "value": TAINT},
                         {"op": "test", "path": ADMISSION_PATH, "value":
                          admission_marker(args.evidence_source_sha, args.admission_run_id)},
                         {"op": "remove", "path": ADMISSION_PATH},
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
        ownership = PLATFORM["read_private_json"](directory / "firewall-ownership.json")
        validate_cleanup(PLATFORM["read_private_json"](directory / "cleanup.json"),
                         ownership, placement, config, args.expected_sha)
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
        if tainted:
            raise ValueError("existing canary taint requires selected admission recovery")
        require_exclusive_canary_label(config, placement, False)
    elif labeled != tainted:
        raise ValueError("canary label and isolation taint differ")
    if args.action == "release":
        if not labeled:
            raise ValueError("canary Node is not admitted; live firewall proof unavailable")
        require_admission_marker(node, ownership["evidenceSourceSha"],
                                 ownership["admissionRunId"])
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
            taints = node["spec"].get("taints")
            taint_add = {"op": "add", "path": "/spec/taints/-", "value": TAINT} if taints \
                else {"op": "add", "path": "/spec/taints", "value": [TAINT]}
            annotations = node["metadata"].get("annotations")
            marker_add = {"op": "add", "path": ADMISSION_PATH,
                          "value": admission_marker(args.expected_sha, os.environ["GITHUB_RUN_ID"])} \
                if annotations else {"op": "add", "path": "/metadata/annotations",
                                     "value": {ADMISSION: admission_marker(
                                         args.expected_sha, os.environ["GITHUB_RUN_ID"])}}
            patch(node, [taint_add, marker_add], args.expected_sha)
            node, labeled, tainted = node_state(config, placement)
            if labeled or not tainted:
                raise ValueError("canary Node taint readback differs")
            require_admission_marker(node, args.expected_sha, os.environ["GITHUB_RUN_ID"])
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
                             {"op": "test", "path": ADMISSION_PATH, "value":
                              admission_marker(ownership["evidenceSourceSha"],
                                               ownership["admissionRunId"])},
                             {"op": "test", "path": f"/spec/taints/{index}", "value": TAINT},
                             {"op": "remove", "path": LABEL_PATH}], args.expected_sha)
                node = wait_for_cleanup_pod_deletion(config, placement, pod)
                require_runtime_absent(False)
                verify_live_pods(config, placement)
                index = next(index for index, item in enumerate(node["spec"].get("taints", []))
                             if item.get("key") == CANARY)
                patch(node, [{"op": "test", "path": f"/spec/taints/{index}", "value": TAINT},
                             {"op": "test", "path": ADMISSION_PATH, "value":
                              admission_marker(ownership["evidenceSourceSha"],
                                               ownership["admissionRunId"])},
                             {"op": "remove", "path": ADMISSION_PATH},
                             {"op": "remove", "path": f"/spec/taints/{index}"}],
                      args.expected_sha)
        require_current_main(args.expected_sha)
        node, labeled, tainted = node_state(config, placement)
        if (labeled, tainted) != ((True, True) if args.action == "admit" else (False, False)):
            raise ValueError("canary Node readback differs")
        if args.action == "admit":
            try:
                require_admission_marker(node, args.expected_sha, os.environ["GITHUB_RUN_ID"])
                require_exclusive_canary_label(config, placement, True)
                verify_live_pods(config, placement)
            except (OSError, ValueError, KeyError, TypeError,
                    subprocess.CalledProcessError, subprocess.TimeoutExpired):
                require_runtime_absent(True)
                patch(node, [{"op": "test", "path": LABEL_PATH, "value": "true"},
                             {"op": "test", "path": ADMISSION_PATH, "value":
                              admission_marker(args.expected_sha, os.environ["GITHUB_RUN_ID"])},
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
    parser.add_argument("action", choices=("admit", "release", "recover", "abort",
                                           "release-recover"))
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--bucket")
    parser.add_argument("--placement-run-id")
    parser.add_argument("--placement-version-id")
    parser.add_argument("--admission-run-id")
    parser.add_argument("--admission-version-id")
    parser.add_argument("--evidence-source-sha")
    parser.add_argument("--release-source-sha")
    parser.add_argument("--release-run-id")
    parser.add_argument("--cleanup-run-id")
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args()
        if args.action == "release-recover":
            release_recover(args)
        elif args.action in {"recover", "abort"}:
            recover(args)
        else:
            if (args.admission_run_id or args.admission_version_id or
                    args.evidence_source_sha or args.release_source_sha or
                    args.release_run_id or args.cleanup_run_id):
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
