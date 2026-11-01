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
QUALIFY = OWNERSHIP["QUALIFY"]
NODE = PLACEMENT["NODE"]
RUN_ID = re.compile(r"[1-9][0-9]*\Z")
MANIFESTS = tuple(PLACEMENT["MANIFESTS"])
BASELINE = PLACEMENT["BASELINE"]
EMPTY = ("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
         "resources: []\n").encode()
ENFORCER_SOURCE = ("apiVersion: kustomize.config.k8s.io/v1beta1\n"
                   "kind: Kustomization\nresources:\n  - daemonset.yaml\n").encode()
FIXTURE_SOURCE = ("apiVersion: kustomize.config.k8s.io/v1beta1\n"
                  "kind: Kustomization\nresources:\n  - fixtures.yaml\n").encode()


def require_source_phase(source_sha, phase):
    if phase not in {"fixtures", "enforcer"}:
        raise ValueError("unreviewed activation phase")
    sources = {
        "clusters/homelab/platform/network-policy/kustomization.yaml":
            EMPTY if phase == "fixtures" else ENFORCER_SOURCE,
        "clusters/homelab/platform/network-policy/canary/kustomization.yaml":
            FIXTURE_SOURCE,
    }
    for relative, expected in sources.items():
        committed = subprocess.check_output(
            ["git", "--no-replace-objects", "show", f"{source_sha}:{relative}"],
            cwd=ROOT, timeout=15)
        if (ROOT / relative).read_bytes() != committed or committed != expected:
            raise ValueError("activation GitOps source phase differs from reviewed order")


def require_application(name, source_sha=None):
    app = CLEANUP["kubernetes_json"]("-n", "argocd", "get", "application", name)
    metadata, spec, status = (app.get(key, {}) for key in ("metadata", "spec", "status"))
    source = {"repoURL": "https://github.com/Stuhlmuller/homelab.git",
              "path": "clusters/homelab/platform/network-policy" +
                      ("/canary" if name == "platform-network-policy-canary" else ""),
              "targetRevision": "main"}
    sync_policy = spec.get("syncPolicy", {})
    automated = sync_policy.get("automated", {})
    expected = ({"enabled": True, "prune": True, "allowEmpty": False,
                 "selfHeal": True} if source_sha is not None else
                {"enabled": False, "prune": False, "allowEmpty": False,
                 "selfHeal": True})
    sync = status.get("sync", {})
    revisions = sync.get("revisions", [sync.get("revision")])
    if (metadata.get("name") != name or metadata.get("namespace") != "argocd" or
            metadata.get("deletionTimestamp") or
            spec.get("project") != "homelab" or
            spec.get("destination") != {"server": "https://kubernetes.default.svc",
                                         "namespace": "network-policy-canary" if
                                         source_sha is not None else "kube-system"} or
            sync_policy.get("syncOptions") != ["CreateNamespace=false",
                                               "ServerSideApply=true"] or
            spec.get("sources") != [source] or automated != expected or
            (source_sha is not None and (
                sync.get("status") != "Synced" or
                status.get("health", {}).get("status") != "Healthy" or
                revisions != [source_sha]))):
        raise ValueError("network-policy Application differs from reviewed phase")



def fixture_capacity(placement):
    server = PLACEMENT["fixture_node"]()
    identity = (server["metadata"]["uid"], server["status"]["nodeInfo"]["bootID"])
    if identity != (placement["fixtureNodeUid"], placement["fixtureBootID"]):
        raise ValueError("fixture Node changed since selected placement")
    measured = PLACEMENT["fixture_capacity"](server)
    after = PLACEMENT["fixture_node"]()
    if ((after["metadata"]["uid"], after["status"]["nodeInfo"]["bootID"]) != identity or
            after["status"].get("allocatable") != server["status"].get("allocatable")):
        raise ValueError("fixture Node changed during capacity measurement")
    return measured


def verified_fixtures(config, placement):
    node, server, pods, firewall, policy_hash = QUALIFY["inspect"](config, False)
    if (firewall is not None or (node["metadata"]["uid"],
            node["status"]["nodeInfo"]["bootID"]) != (
            placement["nodeUid"], placement["bootID"]) or
            (server["metadata"]["uid"], server["status"]["nodeInfo"]["bootID"]) != (
            placement["fixtureNodeUid"], placement["fixtureBootID"])):
        raise ValueError("reviewed fixture Nodes differ from selected placement")
    client = pods["npq-client"]
    CANARY["verify_live_pods"](config, placement, client["metadata"]["uid"])
    signature = {}
    for name, pod in pods.items():
        status, = pod["status"]["containerStatuses"]
        if (not isinstance(status.get("containerID"), str) or
                not status["containerID"] or
                not isinstance(status.get("imageID"), str) or
                not re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}",
                                 status["imageID"]) or
                type(status.get("restartCount")) is not int or
                status["restartCount"] != 0):
            raise ValueError("fixture first-pull container identity is incomplete")
        signature[name] = {"uid": pod["metadata"]["uid"],
                           "node": pod["spec"]["nodeName"],
                           "podIP": pod["status"]["podIP"],
                           "containerID": status["containerID"],
                           "imageID": status["imageID"]}
    return client, {"pods": signature, "policySha256": policy_hash,
                    "fixtureNodeUid": placement["fixtureNodeUid"],
                    "fixtureBootID": placement["fixtureBootID"]}


def reviewed_config(source_sha, phase):
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
    require_source_phase(source_sha, phase)
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


def activation_firewall_baseline(args, store, admission, placement, proof, fixtures):
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
               "placementVersionId": proof["placementVersionId"],
               "fixtureClientUid": fixtures["pods"]["npq-client"]["uid"],
               "fixtureNodeUid": placement["fixtureNodeUid"],
               "fixtureBootID": placement["fixtureBootID"]}
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
            result.get("fixtureClientUid") != fixtures["pods"]["npq-client"]["uid"] or
            result.get("fixtureNodeUid") != placement["fixtureNodeUid"] or
            result.get("fixtureBootID") != placement["fixtureBootID"] or
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
            capture.get("fixtureClientUid") != fixtures["pods"]["npq-client"]["uid"] or
            capture.get("fixtureNodeUid") != placement["fixtureNodeUid"] or
            capture.get("fixtureBootID") != placement["fixtureBootID"] or
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


def execute(args):
    config, admission = reviewed_config(args.expected_sha, args.phase)
    if not RUN_ID.fullmatch(os.environ.get("GITHUB_RUN_ID", "")):
        raise ValueError("protected apply run ID is missing")
    store = OWNERSHIP["PrivateStore"](args.bucket)
    store.store.check()
    placement, proof, admission_key, placement_key = selected_placement(
        store, config, admission)
    require_admitted(config, placement)
    firewall = None
    fixtures = None
    if args.phase == "fixtures":
        require_application("platform-network-policy")
        CANARY["require_runtime_absent"](True)
        CANARY["verify_live_pods"](config, placement)
        measured = PLACEMENT["capacity"](placement)
        fixture_measured = fixture_capacity(placement)
    else:
        require_application("platform-network-policy-canary", args.expected_sha)
        CANARY["require_runtime_absent"](True, allow_reviewed_fixtures=True)
        client, fixtures = verified_fixtures(config, placement)
        # Reserve the full enforcer-plus-client peak. Credit only the exact
        # Ready client already included in Node usage, never another Pod.
        PLACEMENT["capacity"](placement, client=client)
        fixture_capacity(placement)
        firewall = activation_firewall_baseline(
            args, store, admission, placement, proof, fixtures)
        require_application("platform-network-policy-canary", args.expected_sha)
        CANARY["require_runtime_absent"](True, allow_reviewed_fixtures=True)
        client_after, fixtures_after = verified_fixtures(config, placement)
        if fixtures_after != fixtures or client_after["metadata"]["uid"] != client["metadata"]["uid"]:
            raise ValueError("fixture identity changed during firewall baseline")
        measured = PLACEMENT["capacity"](placement, client=client_after)
        fixture_measured = fixture_capacity(placement)
    require_admitted(config, placement)
    if args.phase == "fixtures":
        require_application("platform-network-policy")
        CANARY["require_runtime_absent"](True)
        CANARY["verify_live_pods"](config, placement)
    else:
        require_application("platform-network-policy-canary", args.expected_sha)
        CANARY["require_runtime_absent"](True, allow_reviewed_fixtures=True)
        _, final_fixtures = verified_fixtures(config, placement)
        if final_fixtures != fixtures:
            raise ValueError("fixture identity changed during capacity measurement")
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
              "fixtureNode": placement["fixtureNode"],
              "fixtureNodeUid": placement["fixtureNodeUid"],
              "fixtureBootID": placement["fixtureBootID"],
              "fixtures": fixtures,
              "firewallBaseline": firewall,
              "capacity": measured, "fixtureCapacity": fixture_measured,
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
