#!/usr/bin/env python3
"""Capture the pre-enable kube-router firewall baseline on zimaboard-2."""

import argparse
import hashlib
import http.client
import json
import os
import runpy
import socket
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts/config/platform-maintenance.json"
MANIFEST = ROOT / "clusters/homelab/platform/network-policy/preflight/pod.json"
MANIFEST_SHA256 = "d8fcdc23f45be107880d3d1eec51c3a969cc5a98e65ec0d1b49c5e43ce77a0a4"
CLEANUP = runpy.run_path(str(ROOT / "scripts/network-policy-cleanup.py"))
CANARY = runpy.run_path(str(ROOT / "scripts/network-policy-canary-node.py"))
OWNERSHIP = runpy.run_path(str(ROOT / "scripts/network-policy-ownership.py"))
PLATFORM = CLEANUP["PLATFORM"]
NODE = "zimaboard-2"
POD = "kube-router-firewall-baseline"
RUN_ANNOTATION = "homelab.stinkyboi.com/firewall-baseline-run"
POD_API_PATH = f"/api/v1/namespaces/kube-system/pods/{POD}"
CANARY_TOLERATION = {"key": CLEANUP["CANARY"], "operator": "Equal",
                    "value": "true", "effect": "NoSchedule"}


def require_reviewed_manifest(source_sha):
    relative = MANIFEST.relative_to(ROOT).as_posix()
    committed = CLEANUP["command"]("git", "-C", str(ROOT), "--no-replace-objects",
                                   "show", f"{source_sha}:{relative}")
    content = MANIFEST.read_bytes()
    if (content != committed.encode() or
            hashlib.sha256(content).hexdigest() != MANIFEST_SHA256):
        raise ValueError("preflight Pod differs from the exact pinned source")
    return json.loads(content)


def node_identity():
    node = CLEANUP["kubernetes_json"]("get", "node", NODE)
    metadata, spec, status = node["metadata"], node["spec"], node["status"]
    uid, boot_id = metadata.get("uid"), status.get("nodeInfo", {}).get("bootID")
    if (metadata.get("name") != NODE or not isinstance(uid, str) or not uid or
            not isinstance(boot_id, str) or not boot_id or
            metadata.get("deletionTimestamp") or spec.get("unschedulable") is True or
            not CLEANUP["ready"](node) or
            metadata.get("labels", {}).get("kubernetes.io/hostname") != NODE or
            metadata.get("labels", {}).get(CLEANUP["CANARY"]) is not None or
            any(item.get("key") == CLEANUP["CANARY"] for item in
                spec.get("taints", []))):
        raise ValueError("preflight Node identity, readiness, or isolation changed")
    listing = CLEANUP["kubernetes_json"]("get", "nodes", "-l",
                                         f"kubernetes.io/hostname={NODE}", "--chunk-size=0")
    matches = [(item.get("metadata", {}).get("name"), item.get("metadata", {}).get("uid"))
               for item in CLEANUP["complete_items"](listing, "preflight hostname")]
    if matches != [(NODE, uid)]:
        raise ValueError("preflight hostname selector is ambiguous")
    return uid, boot_id


def recovery_node_identity(placement, evidence_sha, admission_run_id, release=False,
                           release_clean=False):
    node, labeled, tainted = CANARY["node_state"]({"canary": {"node": NODE}}, placement)
    if release and (labeled or tainted == release_clean):
        raise ValueError("release probe Node isolation state changed")
    if tainted:
        CANARY["require_admission_marker"](node, evidence_sha, admission_run_id)
    uid = node["metadata"]["uid"]
    listing = CLEANUP["kubernetes_json"]("get", "nodes", "-l",
                                        f"kubernetes.io/hostname={NODE}", "--chunk-size=0")
    matches = [(item.get("metadata", {}).get("name"), item.get("metadata", {}).get("uid"))
               for item in CLEANUP["complete_items"](listing, "preflight hostname")]
    if matches != [(NODE, uid)]:
        raise ValueError("recovery probe hostname selector is ambiguous")
    return uid, node["status"]["nodeInfo"]["bootID"]


def system_pods():
    listing = CLEANUP["kubernetes_json"]("get", "pods", "-A", "--field-selector",
                                         f"spec.nodeName={NODE}", "--chunk-size=0")
    pods = CLEANUP["complete_items"](listing, "preflight assigned Pod")
    identities = [{"namespace": pod["metadata"]["namespace"],
                   "name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"]}
                  for pod in pods]
    CANARY["verify_live_pods"]({"canary": {"node": NODE}},
                               {"systemDaemonSetPods": identities})
    return sorted(identities, key=lambda item: (item["namespace"], item["name"]))


def get_pod():
    raw = CLEANUP["command"]("kubectl", "--request-timeout=20s", "-n", "kube-system",
                             "get", "pod", POD, "--ignore-not-found", "-o", "json")
    return json.loads(raw) if raw.strip() else None


def read_attempt(path, source_sha, run_id, stage="firewall-baseline"):
    attempt = PLATFORM["read_private_json"](path)
    token = attempt.get("podToken") if isinstance(attempt, dict) else None
    allowed_stages = (("firewall-baseline", "canary-admit-recover", "canary-abort",
                       "canary-release-recover")
                      if stage is None else stage if isinstance(stage, tuple) else (stage,))
    if (not isinstance(attempt, dict) or attempt.get("format") != 1 or
            attempt.get("stage") not in allowed_stages or
            attempt.get("status") != "attempted" or
            attempt.get("verified") is not False or
            attempt.get("sourceSha") != source_sha or
            attempt.get("runId") != run_id or attempt.get("node") != NODE or
            not isinstance(token, str) or len(token) != 48 or
            any(character not in "0123456789abcdef" for character in token)):
        raise ValueError("private preflight ownership marker is missing or unrelated")
    return attempt


def read_recovery_attempt(path, source_sha, evidence_sha, run_id, placement,
                          release=False):
    attempt = read_attempt(path, source_sha, run_id,
                           "canary-release-recover" if release else
                           ("canary-admit-recover", "canary-abort"))
    if (not isinstance(attempt.get("admissionRunId"), str) or
            not OWNERSHIP["RUN_ID"].fullmatch(attempt["admissionRunId"]) or
            attempt.get("evidenceSourceSha") != evidence_sha or
            not isinstance(attempt.get("placementRunId"), str) or
            attempt["placementRunId"] != placement.get("placementRunId") or
            not isinstance(attempt.get("placementVersionId"), str) or
            attempt["placementVersionId"] in ("", "null") or
            attempt.get("nodeUid") != placement.get("nodeUid") or
            attempt.get("bootID") != placement.get("bootID")):
        raise ValueError("recovery probe attempt differs from selected placement")
    if release and (not PLATFORM["SHA"].fullmatch(attempt.get("releaseSourceSha", "")) or
                    not OWNERSHIP["RUN_ID"].fullmatch(attempt.get("releaseRunId", "")) or
                    not OWNERSHIP["RUN_ID"].fullmatch(attempt.get("cleanupRunId", "")) or
                    not OWNERSHIP["RUN_ID"].fullmatch(attempt.get("captureRunId", "")) or
                    not isinstance(attempt.get("cleanupPodUid"), str) or
                    not attempt["cleanupPodUid"] or
                    attempt.get("node") != NODE):
        raise ValueError("release recovery probe selection is incomplete")
    return attempt


def require_probe_owner(pod, token, uid=None):
    metadata = pod["metadata"]
    if (metadata.get("name") != POD or metadata.get("namespace") != "kube-system" or
            metadata.get("annotations", {}).get(RUN_ANNOTATION) != token or
            not isinstance(metadata.get("uid"), str) or not metadata["uid"] or
            (uid is not None and metadata["uid"] != uid)):
        raise ValueError("preflight Pod ownership token or UID changed")
    return metadata["uid"]


def require_probe_pod(pod, token, uid=None, running=False, recovery=False):
    pod_uid = require_probe_owner(pod, token, uid)
    metadata, spec = pod["metadata"], pod["spec"]
    containers = spec.get("containers", [])
    container = containers[0] if isinstance(containers, list) and len(containers) == 1 else {}
    tolerations = spec.get("tolerations", [])
    if (metadata.get("deletionTimestamp") or
            metadata.get("ownerReferences") or
            spec.get("nodeName") not in (None, NODE) or spec.get("hostNetwork") is not True or
            spec.get("hostPID") is True or spec.get("hostIPC") is True or
            spec.get("automountServiceAccountToken") is not False or
            spec.get("activeDeadlineSeconds") != 480 or
            spec.get("terminationGracePeriodSeconds") != 0 or
            spec.get("nodeSelector") != {"kubernetes.io/hostname": NODE} or
            spec.get("volumes") or
            (recovery and (not isinstance(tolerations, list) or
                           CANARY_TOLERATION not in tolerations)) or
            (recovery and any(not isinstance(item, dict) or
                              item.get("key") == CLEANUP["CANARY"] and
                              item != CANARY_TOLERATION
                              for item in tolerations)) or
            not container or
            set(container) - {"name", "image", "imagePullPolicy", "command", "args",
                              "resources", "securityContext", "terminationMessagePath",
                              "terminationMessagePolicy"} or
            container.get("image") != CLEANUP["IMAGE"] or
            container.get("name") != "cleanup" or
            container.get("command") != ["/bin/sh", "-c"] or
            container.get("args") != ["sleep 300"] or
            container.get("securityContext") != {
                "runAsUser": 0, "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"], "add": ["NET_ADMIN"]},
                "seccompProfile": {"type": "RuntimeDefault"}} or
            spec.get("initContainers") or spec.get("ephemeralContainers")):
        raise ValueError("preflight Pod identity or fixed command changed")
    if running and (spec.get("nodeName") != NODE or
                    pod.get("status", {}).get("phase") != "Running" or
                    not CLEANUP["ready"](pod)):
        raise ValueError("preflight Pod is not Ready")
    return pod_uid


def wait_ready(token, uid, timeout_seconds=180, recovery=False):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pod = get_pod()
        if pod is None:
            raise ValueError("preflight Pod disappeared before firewall inspection")
        require_probe_pod(pod, token, uid, recovery=recovery)
        if pod.get("status", {}).get("phase") in {"Failed", "Succeeded"}:
            raise ValueError("preflight Pod exited before firewall inspection")
        if CLEANUP["ready"](pod):
            require_probe_pod(pod, token, uid, running=True, recovery=recovery)
            return
        time.sleep(2)
    raise ValueError("preflight Pod did not become Ready")


def request_uid_delete(socket_path, uid):
    class LocalConnection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(str(socket_path))

    connection = LocalConnection("localhost", timeout=20)
    try:
        body = json.dumps({"apiVersion": "meta.k8s.io/v1", "kind": "DeleteOptions",
                           "preconditions": {"uid": uid}})
        connection.request("DELETE", POD_API_PATH, body=body,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        if len(response.read(8193)) > 8192:
            raise ValueError("Kubernetes DELETE response exceeds bound")
        if response.status == 409:
            raise ValueError("preflight Pod UID changed before deletion")
        if response.status not in {200, 202, 404}:
            raise ValueError("Kubernetes UID-precondition DELETE was not accepted")
    finally:
        connection.close()


def delete_with_uid(uid, private_dir):
    """DELETE this Pod through a private proxy with API-enforced UID precondition."""
    # Unix socket path limits are small on macOS; the fallback stays mode 0700.
    socket_parent = private_dir if len(os.fsencode(private_dir)) < 64 else Path("/tmp")
    with tempfile.TemporaryDirectory(prefix=".fbd-", dir=socket_parent) as directory:
        socket_path = Path(directory) / "api.sock"
        log_path = Path(directory) / "proxy.log"
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as log:
            proxy = subprocess.Popen([
                "kubectl", "--request-timeout=20s", "proxy",
                f"--unix-socket={socket_path}",
                f"--accept-paths=^{POD_API_PATH}$",
                "--reject-methods=^(GET|POST|PUT|PATCH)$",
            ], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 15
                while True:
                    if proxy.poll() is not None or time.monotonic() >= deadline:
                        raise ValueError("private Kubernetes DELETE proxy did not start")
                    if socket_path.exists():
                        info = socket_path.lstat()
                        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                            raise ValueError("private Kubernetes DELETE socket is unsafe")
                        try:
                            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                                probe.settimeout(1)
                                probe.connect(str(socket_path))
                            break
                        except OSError:
                            pass
                    time.sleep(0.1)
                request_uid_delete(socket_path, uid)
            finally:
                proxy.terminate()
                try:
                    proxy.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proxy.kill()
                    proxy.wait(timeout=5)


def delete_probe(token, private_dir, uid=None, timeout_seconds=120):
    pod = get_pod()
    if pod is None:
        return
    actual_uid = require_probe_owner(pod, token, uid)
    delete_with_uid(actual_uid, private_dir)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pod = get_pod()
        if pod is None:
            return
        if pod.get("metadata", {}).get("uid") != actual_uid:
            raise ValueError("preflight Pod name was reused during deletion")
        time.sleep(2)
    raise ValueError("preflight Pod deletion was not observed")


def execute(args):
    recovery = getattr(args, "recovery_placement", None) is not None
    release = bool(getattr(args, "release_recovery", False))
    if release and not recovery:
        raise ValueError("release probe requires selected placement")
    PLATFORM["require_reviewed_execution_config"](args.config, args.expected_sha)
    config = PLATFORM["validate_config"](json.loads(args.config.read_text()))
    if config["canary"]["node"] != NODE or (not release and
                                               config["activationEnabled"] is not False):
        raise ValueError("baseline requires pre-enable canary configuration")
    PLATFORM["protected_context"](args.expected_sha)
    if release:
        OWNERSHIP["require_owner_attestation"]()
    CLEANUP["require_current_main"](args.expected_sha)
    manifest = require_reviewed_manifest(args.expected_sha)
    placement = None
    if recovery:
        if not PLATFORM["SHA"].fullmatch(args.evidence_source_sha or ""):
            raise ValueError("recovery probe requires original admission SHA")
        placement = PLATFORM["read_private_json"](args.recovery_placement)
        CANARY["validate_placement"](placement, config, args.evidence_source_sha, False)
        attempt = read_recovery_attempt(args.attempt, args.expected_sha,
                                        args.evidence_source_sha,
                                        os.environ["GITHUB_RUN_ID"], placement, release)
        if release:
            CANARY["require_release_source"](config, attempt["releaseSourceSha"],
                                              args.expected_sha)
        manifest["spec"]["tolerations"] = [CANARY_TOLERATION]
    else:
        attempt = read_attempt(args.attempt, args.expected_sha, os.environ["GITHUB_RUN_ID"])
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("baseline output already exists")
    store = OWNERSHIP["PrivateStore"](args.bucket)
    store.store.check()
    def require_runtime():
        if release:
            CANARY["require_release_runtime_quiesced"](
                config, placement, attempt["cleanupPodUid"])
        else:
            CANARY["require_runtime_absent"](True)

    require_runtime()
    release_clean = False
    if release:
        node, labeled, tainted = CANARY["node_state"](config, placement)
        if labeled:
            raise ValueError("release probe requires unlabeled canary Node")
        release_clean = not tainted
    inspect_identity = (lambda: recovery_node_identity(
        placement, args.evidence_source_sha, attempt["admissionRunId"], release,
        release_clean)) \
        if recovery else node_identity
    identity = inspect_identity()
    inventory = (lambda: CANARY["clean_release_pods"](config)) if release_clean else system_pods
    assigned = inventory()
    if recovery and not release_clean and assigned != placement["systemDaemonSetPods"]:
        raise ValueError("recovery probe system Pods differ from selected placement")
    record = {"format": 1, "stage": "firewall-release-recovery-proof" if release else
              "firewall-recovery-proof" if recovery else
              "firewall-baseline", "status": "started",
              "verified": False, "sourceSha": args.expected_sha, "runId":
              os.environ["GITHUB_RUN_ID"], "node": NODE,
              "nodeUid": identity[0], "bootID": identity[1],
              "startedAt": datetime.now(timezone.utc).isoformat()}
    if recovery:
        record.update(evidenceSourceSha=args.evidence_source_sha,
                      admissionRunId=attempt["admissionRunId"],
                      placementRunId=attempt["placementRunId"],
                      placementVersionId=attempt["placementVersionId"])
    if release:
        record.update(releaseSourceSha=attempt["releaseSourceSha"],
                      releaseRunId=attempt["releaseRunId"],
                      cleanupRunId=attempt["cleanupRunId"],
                      captureRunId=attempt["captureRunId"],
                      cleanupPodUid=attempt["cleanupPodUid"],
                      observedState="clean" if release_clean else "taint-only")
        if release_clean:
            record["observedPods"] = assigned
    CLEANUP["write_record"](output, record)
    token = attempt["podToken"]
    manifest["metadata"]["annotations"][RUN_ANNOTATION] = token
    pod_file = output.parent / "firewall-baseline-pod.json"
    CLEANUP["write_record"](pod_file, manifest)
    created_uid = None
    create_attempted = False
    try:
        try:
            CLEANUP["require_current_main"](args.expected_sha)
            if inspect_identity() != identity or inventory() != assigned:
                raise ValueError("preflight Node identity or assigned Pods changed before creation")
            create_attempted = True
            created = CLEANUP["kubernetes_json"]("-n", "kube-system", "create", "-f",
                                                 str(pod_file))
            created_uid = require_probe_pod(created, token, recovery=recovery)
            wait_ready(token, created_uid, recovery=recovery)
            if inspect_identity() != identity:
                raise ValueError("preflight Node identity changed during inspection")
            require_probe_pod(get_pod(), token, created_uid, running=True, recovery=recovery)
            state = CLEANUP["snapshot"](POD)
            require_probe_pod(get_pod(), token, created_uid, running=True, recovery=recovery)
            operations, chains, sets = CLEANUP["cleanup_plan"](state)
            if operations or chains or sets:
                raise ValueError("kube-router firewall baseline is not empty")
            if inspect_identity() != identity:
                raise ValueError("preflight Node identity changed after inspection")
            CLEANUP["require_current_main"](args.expected_sha)
        finally:
            if create_attempted:
                delete_probe(token, output.parent, created_uid)
            pod_file.unlink(missing_ok=True)
        require_runtime()
        if inspect_identity() != identity or inventory() != assigned:
            raise ValueError("preflight Node or assigned Pods changed")
        if release:
            CANARY["require_release_source"](config, attempt["releaseSourceSha"],
                                              args.expected_sha)
        CLEANUP["require_current_main"](args.expected_sha)
        capture = dict(record, status="verified", verified=True,
                       firewallBaselineEmpty=True, ownedChains=0, ownedSets=0,
                       backend=state["backend"], snapshot=state,
                       snapshotSha256=CLEANUP["snapshot_sha256"](state),
                       **({} if release_clean else {"systemDaemonSetPods": assigned}),
                       podDeleted=True,
                       completedAt=datetime.now(timezone.utc).isoformat())
        key = (f"openclaw-enterprise/platform/{args.expected_sha}/"
               f"{os.environ['GITHUB_RUN_ID']}/"
               f"{'firewall-recovery-capture' if recovery else 'firewall-baseline-capture'}.json")
        store.write_once(key, capture, OWNERSHIP["MAX_CAPTURE"])
        record.update({key_: capture[key_] for key_ in
                       ("status", "verified", "firewallBaselineEmpty", "ownedChains",
                        "ownedSets", "backend", "snapshotSha256", "podDeleted",
                        "completedAt")})
        record["captureKey"] = key
        CLEANUP["write_record"](output, record, replace=True)
        return record
    except Exception:
        record.update(status="interrupted", verified=False)
        CLEANUP["write_record"](output, record, replace=True)
        raise


def recover(args):
    if (not PLATFORM["SHA"].fullmatch(args.baseline_source_sha or "") or
            not args.baseline_run_id or not args.baseline_run_id.isdigit() or
            args.baseline_run_id.startswith("0")):
        raise ValueError("baseline recovery requires exact reviewed inputs")
    PLATFORM["require_reviewed_execution_config"](args.config, args.expected_sha)
    PLATFORM["protected_context"](args.expected_sha)
    CLEANUP["require_current_main"](args.expected_sha)
    attempt = read_attempt(args.attempt, args.baseline_source_sha,
                           args.baseline_run_id, stage=None)
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("baseline recovery output already exists")
    record = {"format": 1, "stage": "firewall-baseline-recover", "status": "started",
              "verified": False, "sourceSha": args.expected_sha,
              "runId": os.environ["GITHUB_RUN_ID"],
              "baselineSourceSha": args.baseline_source_sha,
              "baselineRunId": args.baseline_run_id,
              "node": NODE, "startedAt": datetime.now(timezone.utc).isoformat()}
    CLEANUP["write_record"](output, record)
    try:
        existing = get_pod()
        if existing is not None:
            uid = require_probe_owner(existing, attempt["podToken"])
            CLEANUP["require_current_main"](args.expected_sha)
            delete_probe(attempt["podToken"], output.parent, uid)
            record["recoveredPodUid"] = uid
        CANARY["require_preflight_absent"]()
        CLEANUP["require_current_main"](args.expected_sha)
        record.update(status="verified", verified=True, podDeleted=True,
                      completedAt=datetime.now(timezone.utc).isoformat())
        CLEANUP["write_record"](output, record, replace=True)
        return record
    except Exception:
        record.update(status="interrupted", verified=False)
        CLEANUP["write_record"](output, record, replace=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("capture", "recover"), default="capture")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--recovery-placement", type=Path)
    parser.add_argument("--release-recovery", action="store_true")
    parser.add_argument("--evidence-source-sha")
    parser.add_argument("--baseline-source-sha")
    parser.add_argument("--baseline-run-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "recover" and (args.recovery_placement or args.evidence_source_sha or
                                         args.release_recovery):
            raise ValueError("orphan probe cleanup does not use placement evidence")
        if args.action != "recover" and not args.recovery_placement and args.evidence_source_sha:
            raise ValueError("baseline capture does not use admission evidence")
        recover(args) if args.action == "recover" else execute(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, http.client.HTTPException) as exc:
        print(f"firewall baseline blocked: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
