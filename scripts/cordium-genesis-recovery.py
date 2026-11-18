#!/usr/bin/env python3
"""Fenced, one-shot retirement of a stranded Cordium bootstrap identity.

Default mode is read-only. --execute is reserved for an approved operator run
from a clean checkout at the exact reviewed main commit.
"""

import argparse
import http.client
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time


TARGETS = (
    ("clusterrolebinding", "cordium-genesis", "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings/cordium-genesis"),
    ("clusterrole", "cordium-genesis", "/apis/rbac.authorization.k8s.io/v1/clusterroles/cordium-genesis"),
    ("serviceaccount", "cordium-genesis", "/api/v1/namespaces/octelium/serviceaccounts/cordium-genesis"),
)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=45, check=True).stdout


def kubectl_json(*args):
    return json.loads(command("kubectl", "--request-timeout=20s", *args, "-o", "json"))


def kubectl_raw_json(path):
    return json.loads(command("kubectl", "--request-timeout=20s", "get", "--raw", path))


PODS_PATH = "/api/v1/namespaces/octelium/pods?limit=500"
JOBS_PATH = "/apis/batch/v1/namespaces/octelium/jobs?limit=500"


def complete(items, kind):
    if (not isinstance(items, dict) or not isinstance(items.get("items"), list) or
            items.get("kind") != kind or not isinstance(items.get("metadata"), dict) or
            not isinstance(items["metadata"].get("resourceVersion"), str) or
            items["metadata"]["resourceVersion"] in {"", "0"} or
            items["metadata"].get("continue")):
        raise ValueError("Kubernetes inventory is incomplete")
    return items["items"]


def validate_snapshot(application, pods, jobs, resources, expected):
    status = application.get("status", {})
    operation = status.get("operationState", {})
    if (application.get("metadata", {}).get("name") != "cordium-bootstrap" or
            application.get("operation") is not None or
            application.get("spec", {}).get("syncPolicy", {}).get("automated", {}).get("enabled") is not False or
            operation.get("phase") != "Failed" or not operation.get("finishedAt") or
            status.get("sync", {}).get("status") != "Synced"):
        raise ValueError("Cordium bootstrap is not a finished failed sync")
    validate_quiescent(pods, jobs)
    for (kind, name, _), resource, uid in zip(TARGETS, resources, expected, strict=True):
        metadata = resource.get("metadata", {})
        if (metadata.get("name") != name or metadata.get("uid") != uid or
                metadata.get("labels", {}).get("app.kubernetes.io/name") != "cordium" or
                "PostSync" not in metadata.get("annotations", {}).get("argocd.argoproj.io/hook", "") or
                resource.get("kind", "").lower() != kind):
            raise ValueError("Bootstrap identity differs from reviewed target")


def validate_quiescent(pods, jobs):
    if any(p.get("spec", {}).get("serviceAccountName") == "cordium-genesis" and
           p.get("status", {}).get("phase") not in {"Succeeded", "Failed"} for p in pods):
        raise ValueError("A Pod still uses the bootstrap identity")
    if any(j.get("status", {}).get("active", 0) and
           (j.get("metadata", {}).get("name", "").startswith("cordium-genesis") or
            j.get("spec", {}).get("template", {}).get("spec", {}).get("serviceAccountName") == "cordium-genesis")
           for j in jobs):
        raise ValueError("A Cordium genesis Job is still active")


def source_guard(expected_sha):
    if command("git", "remote", "get-url", "origin").strip() != "https://github.com/Stuhlmuller/homelab.git":
        raise ValueError("Unexpected source repository")
    if command("git", "rev-parse", "HEAD").strip() != expected_sha:
        raise ValueError("Local checkout differs from reviewed commit")
    if command("git", "status", "--porcelain").strip():
        raise ValueError("Local checkout is dirty")
    remote = command("git", "ls-remote", "--exit-code", "origin", "refs/heads/main")
    if remote.strip() != f"{expected_sha}\trefs/heads/main":
        raise ValueError("Main differs from reviewed commit")


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__("localhost", timeout=30)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def proxy_request(socket_path, method, path, body=None):
    connection = UnixHTTPConnection(socket_path)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def delete_with_uid(socket_path, path, uid):
    body = json.dumps({"apiVersion": "meta.k8s.io/v1", "kind": "DeleteOptions",
                       "preconditions": {"uid": uid}}).encode()
    if proxy_request(socket_path, "DELETE", path, body) not in {200, 202}:
        raise ValueError("Kubernetes did not accept the guarded deletion")


def verify_absent(socket_path, path):
    for _ in range(20):
        status = proxy_request(socket_path, "GET", path)
        if status == 404:
            return
        if status != 200:
            raise ValueError("Kubernetes object verification failed")
        time.sleep(1)
    raise ValueError("A bootstrap identity resource remains after guarded deletion")


def proxy_start():
    private_dir = tempfile.mkdtemp(prefix="cordium-recovery-")
    socket_path = os.path.join(private_dir, "kubernetes.sock")
    try:
        process = subprocess.Popen(
            ["kubectl", "proxy", f"--unix-socket={socket_path}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        shutil.rmtree(private_dir)
        raise
    for _ in range(100):
        if process.poll() is not None:
            break
        if os.path.exists(socket_path) and stat.S_ISSOCK(os.stat(socket_path).st_mode):
            return process, socket_path, private_dir
        time.sleep(0.1)
    process.terminate()
    process.wait(timeout=5)
    shutil.rmtree(private_dir)
    raise ValueError("Private Kubernetes proxy did not start")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected_main_sha")
    parser.add_argument("clusterrolebinding_uid")
    parser.add_argument("clusterrole_uid")
    parser.add_argument("serviceaccount_uid")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    expected = (args.clusterrolebinding_uid, args.clusterrole_uid, args.serviceaccount_uid)
    if not SHA.fullmatch(args.expected_main_sha) or not all(UUID.fullmatch(uid) for uid in expected):
        parser.error("expected main SHA and all three exact resource UIDs are required")
    source_guard(args.expected_main_sha)
    app = kubectl_json("-n", "argocd", "get", "application", "cordium-bootstrap")
    pods = complete(kubectl_raw_json(PODS_PATH), "PodList")
    jobs = complete(kubectl_raw_json(JOBS_PATH), "JobList")
    resources = [kubectl_json(*(["-n", "octelium"] if kind == "serviceaccount" else []),
                              "get", kind, name) for kind, name, _ in TARGETS]
    validate_snapshot(app, pods, jobs, resources, expected)
    if not args.execute:
        print("Cordium bootstrap identity matches reviewed UIDs; no deletion performed.")
        return
    process, socket_path, private_dir = proxy_start()
    try:
        for (_, _, path), uid in zip(TARGETS, expected, strict=True):
            source_guard(args.expected_main_sha)
            current_app = kubectl_json("-n", "argocd", "get", "application", "cordium-bootstrap")
            if (current_app.get("operation") is not None or
                    current_app.get("spec", {}).get("syncPolicy", {}).get("automated", {}).get("enabled") is not False or
                    current_app.get("status", {}).get("operationState", {}).get("phase") != "Failed" or
                    not current_app.get("status", {}).get("operationState", {}).get("finishedAt")):
                raise ValueError("Cordium bootstrap operation changed during recovery")
            validate_quiescent(
                complete(kubectl_raw_json(PODS_PATH), "PodList"),
                complete(kubectl_raw_json(JOBS_PATH), "JobList"))
            delete_with_uid(socket_path, path, uid)
            verify_absent(socket_path, path)
    finally:
        try:
            process.terminate()
            process.wait(timeout=5)
        finally:
            shutil.rmtree(private_dir)
    print("Cordium bootstrap identity deletion verified; detailed output withheld.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.SubprocessError, OSError, http.client.HTTPException) as error:
        print(f"Cordium bootstrap recovery stopped: {type(error).__name__}; details withheld.", file=sys.stderr)
        sys.exit(1)
