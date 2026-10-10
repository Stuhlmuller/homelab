"""Release only the stranded Pods on a physically powered-off worker."""

import argparse
import json
import re
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = "zimaboard-2"
NODE_IP = "10.1.0.202"
NODE_UID = "30e383bf-7a29-436e-b02c-e2b9687f2cb5"
TARGETS = (
    ("argocd", "argocd-application-controller-0", "0c06413e-96d0-4f91-b65d-f8cf729eed26",
     "StatefulSet", "argocd-application-controller", None),
    ("automation", "n8n-postgres-0", "99f91c1f-2318-47e6-946d-eaac65f7b823",
     "StatefulSet", "n8n-postgres", "data-n8n-postgres-0"),
    ("nofx", "nofx-backend-8486bdcf96-xsw9g", "a6be1f63-b7bc-441d-a544-bd59a408d8ce",
     "ReplicaSet", "nofx-backend-8486bdcf96", "nofx-data"),
)


def command(*args, input=None):
    return subprocess.run(args, input=input, text=True, capture_output=True,
                          check=True, timeout=30).stdout


def preflight(expected_sha, target):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise ValueError("Expected SHA must be a full commit ID")
    if command("git", "-C", str(ROOT), "rev-parse", "HEAD").strip() != expected_sha:
        raise ValueError("Checkout is not the approved revision")
    if command("gh", "api", "repos/Stuhlmuller/homelab/commits/main", "--jq", ".sha").strip() != expected_sha:
        raise ValueError("Main has changed")
    if command("git", "-C", str(ROOT), "status", "--porcelain").strip():
        raise ValueError("Checkout is dirty")
    if command("kubectl", "config", "view", "--minify", "-o",
               "jsonpath={.clusters[0].cluster.server}") != "https://10.1.0.199:6443":
        raise ValueError("Unexpected Kubernetes API")
    nodes = json.loads(command("kubectl", "get", "nodes", "-o", "json"))["items"]
    if {node["metadata"]["name"] for node in nodes} != {NODE, "acer", "zimaboard-0", "zimaboard-1"}:
        raise ValueError("Unexpected node inventory")
    for node in nodes:
        ready = next(condition["status"] for condition in node["status"]["conditions"]
                     if condition["type"] == "Ready")
        if node["metadata"]["name"] == NODE:
            if node["metadata"]["uid"] != NODE_UID or ready != "Unknown" or not any(
                    taint["key"] == "node.kubernetes.io/unreachable"
                    for taint in node["spec"].get("taints", [])):
                raise ValueError("Fenced node identity or status changed")
        elif ready != "True":
            raise ValueError("Another node is not Ready")
    try:
        with socket.create_connection((NODE_IP, 50000), timeout=2):
            raise ValueError("Talos API still answers; worker is not fenced")
    except OSError:
        pass
    namespace, name, uid, kind, owner, claim = target
    pod = json.loads(command("kubectl", "-n", namespace, "get", "pod", name, "-o", "json"))
    metadata = pod["metadata"]
    if (metadata["uid"] != uid or not metadata.get("deletionTimestamp")
            or pod["spec"]["nodeName"] != NODE or metadata.get("finalizers")
            or not any(ref["kind"] == kind and ref["name"] == owner
                       for ref in metadata.get("ownerReferences", []))):
        raise ValueError(f"Stranded Pod identity changed: {namespace}/{name}")
    claims = {volume["persistentVolumeClaim"]["claimName"] for volume in pod["spec"].get("volumes", [])
              if "persistentVolumeClaim" in volume}
    if claims != ({claim} if claim else set()):
        raise ValueError(f"Pod PVC contract changed: {namespace}/{name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--target", required=True, choices=[f"{ns}/{name}" for ns, name, *_ in TARGETS])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--fence-confirmation")
    args = parser.parse_args()
    if args.execute and args.fence_confirmation != "zimaboard-2 powered off":
        parser.error("Physical power-off confirmation is required")
    target = next(item for item in TARGETS if f"{item[0]}/{item[1]}" == args.target)
    preflight(args.expected_sha, target)
    if not args.execute:
        print("Preflight passed; no Pods deleted")
        return
    preflight(args.expected_sha, target)
    namespace, name, uid, _, _, _ = target
    options = json.dumps({"apiVersion": "v1", "kind": "DeleteOptions", "gracePeriodSeconds": 0,
                          "preconditions": {"uid": uid}})
    command("kubectl", "delete", "--raw", f"/api/v1/namespaces/{namespace}/pods/{name}",
            "-f", "-", input=options)
    print(f"Released fenced Pod {namespace}/{name}")


if __name__ == "__main__":
    main()
