#!/usr/bin/env python3
"""Fenced, one-shot retirement of a stranded Cordium bootstrap identity.

Default mode is read-only. --execute is reserved for an approved operator run
from a clean checkout at the exact reviewed main commit.
"""

import argparse
import json
import re
import select
import subprocess
import sys
import time
import urllib.error
import urllib.request


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


def complete(items):
    if (not isinstance(items, dict) or not isinstance(items.get("items"), list) or
            not isinstance(items.get("metadata"), dict) or items["metadata"].get("continue")):
        raise ValueError("Kubernetes inventory is incomplete")
    return items["items"]


def validate_snapshot(application, pods, jobs, resources, expected):
    status = application.get("status", {})
    operation = status.get("operationState", {})
    if (application.get("metadata", {}).get("name") != "cordium-bootstrap" or
            application.get("operation") is not None or
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
    if any(j.get("metadata", {}).get("name", "").startswith("cordium-genesis") and
           j.get("status", {}).get("active", 0) for j in jobs):
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


def delete_with_uid(proxy_url, path, uid):
    body = json.dumps({"apiVersion": "meta.k8s.io/v1", "kind": "DeleteOptions",
                       "preconditions": {"uid": uid}}).encode()
    request = urllib.request.Request(proxy_url + path, data=body, method="DELETE",
                                     headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        if response.status not in {200, 202}:
            raise ValueError("Kubernetes did not accept the guarded deletion")


def verify_absent(proxy_url, path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(20):
        try:
            with opener.open(proxy_url + path, timeout=10):
                pass
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return
            raise
        time.sleep(1)
    raise ValueError("A bootstrap identity resource remains after guarded deletion")


def proxy_start():
    process = subprocess.Popen(
        ["kubectl", "proxy", "--address=127.0.0.1", "--port=0", "--accept-hosts=^127\\.0\\.0\\.1$"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    if not select.select([process.stdout], [], [], 10)[0]:
        process.terminate()
        raise ValueError("Local Kubernetes proxy did not start")
    line = process.stdout.readline().strip()
    match = re.fullmatch(r"Starting to serve on 127\.0\.0\.1:([0-9]+)", line)
    if not match:
        process.terminate()
        raise ValueError("Local Kubernetes proxy returned an unexpected address")
    return process, f"http://127.0.0.1:{match.group(1)}"


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
    pods = complete(kubectl_json("-n", "octelium", "get", "pods", "--chunk-size=0"))
    jobs = complete(kubectl_json("-n", "octelium", "get", "jobs", "--chunk-size=0"))
    resources = [kubectl_json(*(["-n", "octelium"] if kind == "serviceaccount" else []),
                              "get", kind, name) for kind, name, _ in TARGETS]
    validate_snapshot(app, pods, jobs, resources, expected)
    if not args.execute:
        print("Cordium bootstrap identity matches reviewed UIDs; no deletion performed.")
        return
    process, url = proxy_start()
    try:
        for (_, _, path), uid in zip(TARGETS, expected, strict=True):
            source_guard(args.expected_main_sha)
            current_app = kubectl_json("-n", "argocd", "get", "application", "cordium-bootstrap")
            if (current_app.get("operation") is not None or
                    current_app.get("status", {}).get("operationState", {}).get("phase") != "Failed" or
                    not current_app.get("status", {}).get("operationState", {}).get("finishedAt")):
                raise ValueError("Cordium bootstrap operation changed during recovery")
            validate_quiescent(
                complete(kubectl_json("-n", "octelium", "get", "pods", "--chunk-size=0")),
                complete(kubectl_json("-n", "octelium", "get", "jobs", "--chunk-size=0")))
            delete_with_uid(url, path, uid)
            verify_absent(url, path)
    finally:
        process.terminate()
        process.wait(timeout=5)
    print("Cordium bootstrap identity deletion verified; detailed output withheld.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.SubprocessError, OSError, urllib.error.URLError) as error:
        print(f"Cordium bootstrap recovery stopped: {type(error).__name__}; details withheld.", file=sys.stderr)
        sys.exit(1)
