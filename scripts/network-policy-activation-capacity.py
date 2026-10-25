#!/usr/bin/env python3
"""Prove admitted canary capacity immediately before each protected GitOps apply."""

import argparse
import json
import os
import re
import runpy
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts/config/platform-maintenance.json"
PLATFORM = runpy.run_path(str(ROOT / "scripts/platform-maintenance.py"))
PLACEMENT = runpy.run_path(str(ROOT / "scripts/network-policy-placement.py"))
CANARY = PLACEMENT["CANARY"]
CLEANUP = PLACEMENT["CLEANUP"]
OWNERSHIP = PLACEMENT["OWNERSHIP"]
NODE = PLACEMENT["NODE"]
ENFORCER = CLEANUP["ENFORCER"]
RUN_ID = re.compile(r"[1-9][0-9]*\Z")
IMAGE = ("harbor.stinkyboi.com/mirror/docker.io/cloudnativelabs/kube-router:"
         "64da9a538d29e13780e256ce3897a52932a68657793bef009063bbeb2762146a"
         "@sha256:64da9a538d29e13780e256ce3897a52932a68657793bef009063bbeb2762146a")
ARGS = ["--run-router=false", "--run-service-proxy=false", "--run-loadbalancer=false",
        "--run-firewall=true", "--enable-cni=false", "--netpol-default-deny=true",
        "--use-nftables-for-netpol=false", "--enable-ipv4=true", "--enable-ipv6=false",
        "--health-addr=127.0.0.1"]
MANIFESTS = tuple(PLACEMENT["MANIFESTS"])
BASELINE = PLACEMENT["BASELINE"]


def reviewed_config(source_sha):
    PLATFORM["require_reviewed_execution_config"](CONFIG, source_sha)
    config = PLATFORM["validate_config"](json.loads(CONFIG.read_text()))
    admission = config.get("activationAdmission")
    if (config["activationEnabled"] is not True or config["canary"]["node"] != NODE or
            not isinstance(admission, dict) or
            set(admission) != {"sourceSha", "runId", "versionId"} or
            not PLATFORM["SHA"].fullmatch(str(admission["sourceSha"])) or
            not RUN_ID.fullmatch(str(admission["runId"])) or
            not isinstance(admission["versionId"], str) or
            admission["versionId"] in {"", "null"}):
        raise ValueError("reviewed activation and selected admission are required")
    PLATFORM["protected_context"](source_sha)
    CLEANUP["require_current_main"](source_sha)
    PLACEMENT["pinned_manifests"](source_sha)
    ancestors = subprocess.check_output(
        ["git", "--no-replace-objects", "rev-list", "--first-parent", source_sha],
        cwd=ROOT, text=True, timeout=30).splitlines()
    if admission["sourceSha"] == source_sha or admission["sourceSha"] not in ancestors:
        raise ValueError("admission source is not a prior main commit")
    for relative in MANIFESTS:
        previous = subprocess.check_output(
            ["git", "--no-replace-objects", "show", f"{admission['sourceSha']}:{relative}"],
            cwd=ROOT, timeout=15)
        if previous != (ROOT / relative).read_bytes():
            raise ValueError("runtime manifest changed after canary admission")
    return config, admission


def selected_placement(store, config, admission):
    evidence_sha, run_id = admission["sourceSha"], admission["runId"]
    key = f"openclaw-enterprise/platform/{evidence_sha}/{run_id}/canary-admit.json"
    if store.version(key, True) != admission["versionId"]:
        raise ValueError("selected admission version differs")
    proof = json.loads(store.read(key, 1048576))
    if store.version(key, True) != admission["versionId"]:
        raise ValueError("selected admission changed during read")
    placement_run = proof.get("placementRunId") if isinstance(proof, dict) else None
    placement_version = proof.get("placementVersionId") if isinstance(proof, dict) else None
    if (not isinstance(proof, dict) or proof.get("format") != 1 or
            proof.get("stage") != "canary-admit" or proof.get("status") != "verified" or
            proof.get("verified") is not True or proof.get("sourceSha") != evidence_sha or
            proof.get("runId") != run_id or proof.get("node") != NODE or
            not isinstance(proof.get("nodeUid"), str) or not proof["nodeUid"] or
            not isinstance(proof.get("bootID"), str) or not proof["bootID"] or
            not RUN_ID.fullmatch(str(placement_run)) or
            not isinstance(placement_version, str) or
            placement_version in {"", "null"} or
            not isinstance(proof.get("resourceVersion"), str) or
            not proof["resourceVersion"] or
            not isinstance(proof.get("completedAt"), str)):
        raise ValueError("selected verified canary admission is missing")
    completed = datetime.fromisoformat(proof["completedAt"].replace("Z", "+00:00"))
    if (completed.utcoffset() is None or completed.utcoffset().total_seconds() != 0 or
            completed > datetime.now(timezone.utc)):
        raise ValueError("selected admission completion timestamp is invalid")
    placement_key = (f"openclaw-enterprise/platform/receipts/{evidence_sha}/"
                     f"placement/{placement_run}.json")
    if store.version(placement_key, True) != placement_version:
        raise ValueError("selected placement version differs")
    placement = json.loads(store.read(placement_key, 1048576))
    if store.version(placement_key, True) != placement_version:
        raise ValueError("selected placement changed during read")
    CANARY["validate_placement"](placement, config, evidence_sha, False)
    if (placement["placementRunId"] != placement_run or
            (placement["nodeUid"], placement["bootID"]) !=
            (proof["nodeUid"], proof["bootID"])):
        raise ValueError("admission and placement Node identity differ")
    return placement, proof, key, placement_key


def require_admitted(config, placement):
    node, labeled, tainted = CANARY["node_state"](config, placement)
    if not (labeled and tainted):
        raise ValueError("reviewed canary Node is not admitted")
    CANARY["require_exclusive_canary_label"](config, placement, True)
    return node


def activation_firewall_baseline(args, store, admission, placement, proof):
    """Use the pinned protected probe, then verify its deleted-Pod capture."""
    run_id = os.environ["GITHUB_RUN_ID"]
    prefix = f"openclaw-enterprise/platform/{args.expected_sha}/{run_id}"
    attempt = {"format": 1, "stage": "firewall-activation-baseline",
               "status": "attempted", "verified": False,
               "sourceSha": args.expected_sha, "runId": run_id, "node": NODE,
               "nodeUid": placement["nodeUid"], "bootID": placement["bootID"],
               "podToken": secrets.token_hex(24),
               "admissionSourceSha": admission["sourceSha"],
               "admissionRunId": admission["runId"],
               "admissionVersionId": admission["versionId"],
               "placementRunId": proof["placementRunId"],
               "placementVersionId": proof["placementVersionId"]}
    with tempfile.TemporaryDirectory(prefix="activation-baseline-") as directory:
        private = Path(directory)
        private.chmod(0o700)
        attempt_path, placement_path = private / "attempt.json", private / "placement.json"
        for path, record in ((attempt_path, attempt), (placement_path, placement)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(record, stream, sort_keys=True)
                stream.write("\n")
        # This durable token/UID marker precedes every live Pod create. The
        # existing protected firewall-baseline-recover stage can remove an
        # orphan after runner interruption without admitting a replacement.
        attempt_key = f"{prefix}/baseline-attempt.json"
        store.write_once(attempt_key, attempt, 1048576)
        attempt_version = store.version(attempt_key, True)
        result = BASELINE["execute"](argparse.Namespace(
            config=CONFIG, expected_sha=args.expected_sha, bucket=args.bucket,
            attempt=attempt_path, output=private / "baseline.json",
            recovery_placement=None, activation_placement=placement_path,
            evidence_source_sha=admission["sourceSha"]))
    capture_key = f"{prefix}/firewall-activation-capture.json"
    if (result.get("format") != 1 or result.get("stage") != "firewall-activation-baseline" or
            result.get("status") != "verified" or result.get("verified") is not True or
            result.get("sourceSha") != args.expected_sha or result.get("runId") != run_id or
            result.get("nodeUid") != placement["nodeUid"] or
            result.get("bootID") != placement["bootID"] or
            result.get("admissionVersionId") != admission["versionId"] or
            result.get("placementVersionId") != proof["placementVersionId"] or
            result.get("firewallBaselineEmpty") is not True or
            result.get("ownedChains") != 0 or result.get("ownedSets") != 0 or
            result.get("podDeleted") is not True or result.get("captureKey") != capture_key):
        raise ValueError("fresh admitted firewall baseline is incomplete")
    capture_version = store.version(capture_key, True)
    capture = json.loads(store.read(capture_key, OWNERSHIP["MAX_CAPTURE"]))
    if (store.version(capture_key, True) != capture_version or
            capture.get("format") != 1 or
            capture.get("stage") != "firewall-activation-baseline" or
            capture.get("status") != "verified" or capture.get("verified") is not True or
            capture.get("sourceSha") != args.expected_sha or capture.get("runId") != run_id or
            capture.get("nodeUid") != placement["nodeUid"] or
            capture.get("bootID") != placement["bootID"] or
            capture.get("evidenceSourceSha") != admission["sourceSha"] or
            capture.get("admissionRunId") != admission["runId"] or
            capture.get("admissionVersionId") != admission["versionId"] or
            capture.get("placementVersionId") != proof["placementVersionId"] or
            capture.get("placementRunId") != proof["placementRunId"] or
            capture.get("systemDaemonSetPods") != placement["systemDaemonSetPods"] or
            capture.get("firewallBaselineEmpty") is not True or
            capture.get("ownedChains") != 0 or capture.get("ownedSets") != 0 or
            capture.get("podDeleted") is not True or
            capture.get("completedAt") != result.get("completedAt") or
            capture.get("snapshotSha256") != result.get("snapshotSha256") or
            capture.get("snapshotSha256") != CLEANUP["snapshot_sha256"](
                capture.get("snapshot")) or any(CLEANUP["cleanup_plan"](capture["snapshot"]))):
        raise ValueError("fresh admitted firewall capture differs")
    PLACEMENT["fresh"](capture.get("completedAt"), 120)
    return {"attemptKey": attempt_key, "attemptVersionId": attempt_version,
            "captureKey": capture_key, "captureVersionId": capture_version,
            "snapshotSha256": capture["snapshotSha256"],
            "completedAt": capture["completedAt"]}


def require_fixture_absent():
    raw = CLEANUP["command"]("kubectl", "--request-timeout=20s", "get", "namespace",
                             "network-policy-canary", "--ignore-not-found", "-o", "json")
    if raw.strip():
        raise ValueError("canary fixtures already exist")


def require_enforcer_spec(spec):
    def reviewed_probe(probe):
        if not isinstance(probe, dict):
            return False
        http = probe.get("httpGet", {})
        return (isinstance(http, dict) and
                all(http.get(key) == value for key, value in
                    (("host", "127.0.0.1"), ("path", "/healthz"), ("port", "health"))) and
                http.get("scheme", "HTTP") == "HTTP" and
                probe.get("initialDelaySeconds") == 10 and
                probe.get("periodSeconds") == 10 and
                probe.get("timeoutSeconds", 1) == 1 and
                probe.get("failureThreshold", 3) == 3 and
                probe.get("successThreshold", 1) == 1 and
                not probe.get("exec") and not probe.get("tcpSocket") and
                not probe.get("grpc"))

    if (not isinstance(spec, dict) or spec.get("nodeSelector") !=
            {CANARY["CANARY"]: "true"} or spec.get("hostNetwork") is not True or
            spec.get("dnsPolicy") != "ClusterFirstWithHostNet" or
            spec.get("hostPID") is True or spec.get("hostIPC") is True or
            spec.get("serviceAccountName") != ENFORCER or
            spec.get("priorityClassName") != "system-node-critical" or
            {**CANARY["TAINT"], "operator": "Equal"} not in
            spec.get("tolerations", []) or
            spec.get("initContainers") or spec.get("ephemeralContainers") or
            not isinstance(spec.get("containers"), list) or
            len(spec["containers"]) != 1):
        raise ValueError("enforcer placement differs from reviewed manifest")
    container = spec["containers"][0]
    if (container.get("name") != "kube-router" or container.get("image") != IMAGE or
            container.get("args") != ARGS or
            container.get("command") not in (None, []) or
            container.get("imagePullPolicy") != "IfNotPresent" or
            container.get("lifecycle") not in (None, {}) or
            container.get("securityContext", {}).get("privileged") is not True or
            container.get("ports") != [{"name": "health", "containerPort": 20244,
                                        "protocol": "TCP"}] or
            not reviewed_probe(container.get("readinessProbe")) or
            not reviewed_probe(container.get("livenessProbe")) or
            container.get("resources") != {"requests": {"cpu": "250m", "memory": "250Mi"},
                                           "limits": {"memory": "512Mi"}}):
        raise ValueError("enforcer image, behavior, or resource budget differs")
    mounts = container.get("volumeMounts", [])
    volumes = spec.get("volumes", [])
    lock_mount = {"name": "xtables-lock", "mountPath": "/run/xtables.lock"}
    lock_volume = {"name": "xtables-lock", "hostPath": {
        "path": "/run/xtables.lock", "type": "FileOrCreate"}}
    if (not isinstance(mounts, list) or not isinstance(volumes, list) or
            sum(isinstance(mount, dict) and
                {key: mount.get(key) for key in lock_mount} == lock_mount and
                mount.get("readOnly", False) is False for mount in mounts) != 1 or
            sum(volume == lock_volume for volume in volumes) != 1 or
            any(not isinstance(mount, dict) or
                (mount.get("name") != "xtables-lock" and
                 (not str(mount.get("name", "")).startswith("kube-api-access-") or
                  mount.get("mountPath") !=
                  "/var/run/secrets/kubernetes.io/serviceaccount" or
                  mount.get("readOnly") is not True)) for mount in mounts) or
            any(not isinstance(volume, dict) or
                (volume.get("name") != "xtables-lock" and
                 (not str(volume.get("name", "")).startswith("kube-api-access-") or
                  "projected" not in volume)) for volume in volumes)):
        raise ValueError("enforcer has an unreviewed host mount")


def verify_enforcer(config, placement):
    CANARY["require_preflight_absent"]()
    require_fixture_absent()
    cleanup = CLEANUP["command"]("kubectl", "--request-timeout=20s", "-n", "kube-system",
                                 "get", "daemonset", CLEANUP["CLEANUP"],
                                 "--ignore-not-found", "-o", "json")
    if cleanup.strip():
        raise ValueError("cleanup DaemonSet is present during activation")
    daemonset = CLEANUP["kubernetes_json"]("-n", "kube-system", "get", "daemonset", ENFORCER)
    metadata, status = daemonset.get("metadata", {}), daemonset.get("status", {})
    if (metadata.get("namespace") != "kube-system" or metadata.get("name") != ENFORCER or
            not isinstance(metadata.get("uid"), str) or not metadata["uid"] or
            type(metadata.get("generation")) is not int or
            status.get("observedGeneration", -1) < metadata["generation"] or
            any(status.get(name) != value for name, value in
                (("desiredNumberScheduled", 1), ("numberReady", 1),
                 ("numberAvailable", 1), ("numberMisscheduled", 0)))):
        raise ValueError("enforcer DaemonSet is not exclusively Ready")
    template = daemonset.get("spec", {}).get("template", {})
    require_enforcer_spec(template.get("spec"))
    listing = CLEANUP["kubernetes_json"]("get", "pods", "-A", "--field-selector",
                                         f"spec.nodeName={NODE}", "--chunk-size=0")
    system, enforcers = [], []
    for pod in CLEANUP["complete_items"](listing, "activation assigned Pod"):
        meta, spec = pod.get("metadata", {}), pod.get("spec", {})
        if (not isinstance(meta, dict) or not isinstance(spec, dict) or
                spec.get("nodeName") != NODE or meta.get("deletionTimestamp") or
                not isinstance(meta.get("uid"), str) or not meta["uid"]):
            raise ValueError("activation assigned Pod identity is invalid")
        if meta.get("namespace") == "kube-system" and meta.get("name", "").startswith(
                ENFORCER + "-"):
            owners = meta.get("ownerReferences", [])
            if (not any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                        owner.get("name") == ENFORCER and owner.get("uid") == metadata["uid"] and
                        owner.get("controller") is True for owner in owners) or
                    pod.get("status", {}).get("phase") != "Running" or
                    not CLEANUP["ready"](pod)):
                raise ValueError("enforcer Pod is not owned and Ready")
            require_enforcer_spec(spec)
            enforcers.append(pod)
        else:
            owners = meta.get("ownerReferences", [])
            if (meta.get("namespace") not in CANARY["SYSTEM_NAMESPACES"] or
                    not any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                            owner.get("controller") is True and
                            (owner.get("name") == "ztunnel" if
                             meta["namespace"] == "istio-system" else
                             owner.get("name") not in {ENFORCER, CLEANUP["CLEANUP"]})
                            for owner in owners)):
                raise ValueError("foreign Pod is present on the canary Node")
            system.append({key: meta[key] for key in ("namespace", "name", "uid")})
    system.sort(key=lambda item: (item["namespace"], item["name"]))
    if system != placement["systemDaemonSetPods"] or len(enforcers) != 1:
        raise ValueError("canary Pod inventory differs from reviewed placement")
    enforcer = enforcers[0]
    labeled = CLEANUP["kubernetes_json"]("-n", "kube-system", "get", "pods", "-l",
                                         f"app.kubernetes.io/name={ENFORCER}",
                                         "--chunk-size=0")
    if [(pod.get("metadata", {}).get("uid")) for pod in
        CLEANUP["complete_items"](labeled, "enforcer Pod")] != [enforcer["metadata"]["uid"]]:
        raise ValueError("enforcer Pod inventory is ambiguous")
    return enforcer


def execute(args):
    config, admission = reviewed_config(args.expected_sha)
    if not RUN_ID.fullmatch(os.environ.get("GITHUB_RUN_ID", "")):
        raise ValueError("protected apply run ID is missing")
    store = OWNERSHIP["PrivateStore"](args.bucket)
    store.store.check()
    placement, proof, admission_key, placement_key = selected_placement(
        store, config, admission)
    require_admitted(config, placement)
    firewall = None
    if args.phase == "enforcer":
        CANARY["require_runtime_absent"](True)
        CANARY["verify_live_pods"](config, placement)
        # Do not create even the short-lived host probe on a node that cannot
        # already reserve the reviewed full canary runtime budget.
        PLACEMENT["capacity"](placement)
        firewall = activation_firewall_baseline(args, store, admission, placement, proof)
        enforcer = None
    else:
        enforcer = verify_enforcer(config, placement)
    measured = PLACEMENT["capacity"](placement, enforcer)
    require_admitted(config, placement)
    if args.phase == "enforcer":
        CANARY["require_runtime_absent"](True)
        CANARY["verify_live_pods"](config, placement)
    elif verify_enforcer(config, placement)["metadata"]["uid"] != enforcer["metadata"]["uid"]:
        raise ValueError("enforcer Pod changed during capacity measurement")
    if (store.version(admission_key, True) != admission["versionId"] or
            store.version(placement_key, True) != proof["placementVersionId"]):
        raise ValueError("selected evidence changed during capacity measurement")
    PLACEMENT["fresh"](measured["nodeMetricsTimestamp"], 120)
    PLACEMENT["fresh"](measured["nodeFsTimestamp"], 120)
    if measured["kubeletSummaryTimestamp"] is not None:
        PLACEMENT["fresh"](measured["kubeletSummaryTimestamp"], 120)
    if firewall is not None:
        PLACEMENT["fresh"](firewall["completedAt"], 120)
    CLEANUP["require_current_main"](args.expected_sha)
    record = {"format": 1, "stage": "activation-capacity", "phase": args.phase,
              "status": "verified", "verified": True, "sourceSha": args.expected_sha,
              "runId": os.environ["GITHUB_RUN_ID"], "node": NODE,
              "nodeUid": placement["nodeUid"], "bootID": placement["bootID"],
              "admissionSourceSha": admission["sourceSha"],
              "admissionRunId": admission["runId"],
              "admissionVersionId": admission["versionId"],
              "placementRunId": proof["placementRunId"],
              "placementVersionId": proof["placementVersionId"],
              "enforcerPodUid": enforcer["metadata"]["uid"] if enforcer else None,
              "firewallBaseline": firewall,
              "capacity": measured,
              "measuredAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    key = (f"openclaw-enterprise/platform/{args.expected_sha}/"
           f"{os.environ['GITHUB_RUN_ID']}/activation-capacity-{args.phase}.json")
    store.write_once(key, record, 1048576)
    CLEANUP["require_current_main"](args.expected_sha)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("enforcer", "fixtures"), required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--bucket", required=True)
    args = parser.parse_args()
    try:
        execute(args)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"activation capacity blocked: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
