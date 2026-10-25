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


def read_attempt(path, source_sha, run_id):
    attempt = PLATFORM["read_private_json"](path)
    token = attempt.get("podToken") if isinstance(attempt, dict) else None
    if (not isinstance(attempt, dict) or attempt.get("format") != 1 or
            attempt.get("stage") != "firewall-baseline" or
            attempt.get("status") != "attempted" or
            attempt.get("verified") is not False or
            attempt.get("sourceSha") != source_sha or
            attempt.get("runId") != run_id or attempt.get("node") != NODE or
            not isinstance(token, str) or len(token) != 48 or
            any(character not in "0123456789abcdef" for character in token)):
        raise ValueError("private preflight ownership marker is missing or unrelated")
    return attempt


def require_probe_owner(pod, token, uid=None):
    metadata = pod["metadata"]
    if (metadata.get("name") != POD or metadata.get("namespace") != "kube-system" or
            metadata.get("annotations", {}).get(RUN_ANNOTATION) != token or
            not isinstance(metadata.get("uid"), str) or not metadata["uid"] or
            (uid is not None and metadata["uid"] != uid)):
        raise ValueError("preflight Pod ownership token or UID changed")
    return metadata["uid"]


def require_probe_pod(pod, token, uid=None, running=False):
    pod_uid = require_probe_owner(pod, token, uid)
    metadata, spec = pod["metadata"], pod["spec"]
    containers = spec.get("containers", [])
    container = containers[0] if isinstance(containers, list) and len(containers) == 1 else {}
    if (metadata.get("deletionTimestamp") or
            metadata.get("ownerReferences") or
            spec.get("nodeName") not in (None, NODE) or spec.get("hostNetwork") is not True or
            spec.get("hostPID") is True or spec.get("hostIPC") is True or
            spec.get("automountServiceAccountToken") is not False or
            spec.get("activeDeadlineSeconds") != 480 or
            spec.get("terminationGracePeriodSeconds") != 0 or
            spec.get("nodeSelector") != {"kubernetes.io/hostname": NODE} or
            spec.get("volumes") or
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


def wait_ready(token, uid, timeout_seconds=180):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pod = get_pod()
        if pod is None:
            raise ValueError("preflight Pod disappeared before firewall inspection")
        require_probe_pod(pod, token, uid)
        if pod.get("status", {}).get("phase") in {"Failed", "Succeeded"}:
            raise ValueError("preflight Pod exited before firewall inspection")
        if CLEANUP["ready"](pod):
            require_probe_pod(pod, token, uid, running=True)
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
    PLATFORM["require_reviewed_execution_config"](args.config, args.expected_sha)
    config = PLATFORM["validate_config"](json.loads(args.config.read_text()))
    if config["activationEnabled"] is not False or config["canary"]["node"] is not None:
        raise ValueError("baseline requires pre-enable canary configuration")
    PLATFORM["protected_context"](args.expected_sha)
    CLEANUP["require_current_main"](args.expected_sha)
    manifest = require_reviewed_manifest(args.expected_sha)
    attempt = read_attempt(args.attempt, args.expected_sha, os.environ["GITHUB_RUN_ID"])
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("baseline output already exists")
    store = OWNERSHIP["PrivateStore"](args.bucket)
    store.store.check()
    CANARY["require_runtime_absent"](True)
    identity = node_identity()
    assigned = system_pods()
    record = {"format": 1, "stage": "firewall-baseline", "status": "started",
              "verified": False, "sourceSha": args.expected_sha, "runId":
              os.environ["GITHUB_RUN_ID"], "node": NODE,
              "nodeUid": identity[0], "bootID": identity[1],
              "startedAt": datetime.now(timezone.utc).isoformat()}
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
            if node_identity() != identity or system_pods() != assigned:
                raise ValueError("preflight Node identity or assigned Pods changed before creation")
            create_attempted = True
            created = CLEANUP["kubernetes_json"]("-n", "kube-system", "create", "-f",
                                                 str(pod_file))
            created_uid = require_probe_pod(created, token)
            wait_ready(token, created_uid)
            if node_identity() != identity:
                raise ValueError("preflight Node identity changed during inspection")
            require_probe_pod(get_pod(), token, created_uid, running=True)
            state = CLEANUP["snapshot"](POD)
            require_probe_pod(get_pod(), token, created_uid, running=True)
            operations, chains, sets = CLEANUP["cleanup_plan"](state)
            if operations or chains or sets:
                raise ValueError("kube-router firewall baseline is not empty")
            if node_identity() != identity:
                raise ValueError("preflight Node identity changed after inspection")
            CLEANUP["require_current_main"](args.expected_sha)
        finally:
            if create_attempted:
                delete_probe(token, output.parent, created_uid)
            pod_file.unlink(missing_ok=True)
        CANARY["require_runtime_absent"](True)
        if node_identity() != identity or system_pods() != assigned:
            raise ValueError("preflight Node or assigned Pods changed")
        CLEANUP["require_current_main"](args.expected_sha)
        capture = dict(record, status="verified", verified=True,
                       firewallBaselineEmpty=True, ownedChains=0, ownedSets=0,
                       backend=state["backend"], snapshot=state,
                       snapshotSha256=CLEANUP["snapshot_sha256"](state),
                       systemDaemonSetPods=assigned,
                       podDeleted=True,
                       completedAt=datetime.now(timezone.utc).isoformat())
        key = (f"openclaw-enterprise/platform/{args.expected_sha}/"
               f"{os.environ['GITHUB_RUN_ID']}/firewall-baseline-capture.json")
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
    attempt = read_attempt(args.attempt, args.baseline_source_sha, args.baseline_run_id)
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
    parser.add_argument("--baseline-source-sha")
    parser.add_argument("--baseline-run-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        recover(args) if args.action == "recover" else execute(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, http.client.HTTPException) as exc:
        print(f"firewall baseline blocked: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
