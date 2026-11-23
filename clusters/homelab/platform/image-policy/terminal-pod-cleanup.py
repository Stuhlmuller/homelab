"""Retire the reviewed terminal Pods that still advertise upstream images."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import ssl
from urllib.error import HTTPError
from urllib.request import Request, urlopen

CONTAINERS = ("initContainers", "containers", "ephemeralContainers")
STATUSES = ("initContainerStatuses", "containerStatuses", "ephemeralContainerStatuses")


def eligible(pod, replica_set, cutoff):
    metadata, spec, status = (pod[key] for key in ("metadata", "spec", "status"))
    if status["phase"] not in {"Succeeded", "Failed"} or metadata.get("deletionTimestamp"):
        return False
    if metadata.get("finalizers"):
        return False
    if not any(
        owner.get("controller") and owner["kind"] == "ReplicaSet" and owner["name"] == replica_set
        for owner in metadata.get("ownerReferences", [])
    ):
        return False
    if all(
        container["image"].startswith("harbor.stinkyboi.com/")
        for group in CONTAINERS
        for container in spec.get(group, [])
    ):
        return False
    finished = [
        datetime.fromisoformat(timestamp)
        for group in STATUSES
        for container in status.get(group, [])
        if (timestamp := container["state"].get("terminated", {}).get("finishedAt"))
    ]
    return bool(finished) and max(finished) < cutoff


def request(method, path, context, headers, body=None):
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.environ["KUBERNETES_SERVICE_PORT"]
    url = f"https://{host}:{port}{path}"
    data = None if body is None else json.dumps(body).encode()
    try:
        with urlopen(Request(url, data, headers, method=method), context=context, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def clean(targets, api, now):
    cutoff = now - timedelta(days=30)
    for namespace, entries in targets.items():
        for target in entries:
            name = target["name"]
            path = f"/api/v1/namespaces/{namespace}/pods/{name}"
            pod = api("GET", path)
            if pod is None:
                continue
            if not eligible(pod, target["replicaSet"], cutoff):
                print(f"Skipped {namespace}/{name}: cleanup guards no longer match.")
                continue
            metadata = pod["metadata"]
            api("DELETE", path, {
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "preconditions": {
                    "uid": metadata["uid"],
                    "resourceVersion": metadata["resourceVersion"],
                },
            })
            print(f"Retired {namespace}/{name}.")


def main():
    account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    context = ssl.create_default_context(cafile=str(account / "ca.crt"))
    headers = {
        "Authorization": "Bearer " + (account / "token").read_text().strip(),
        "Content-Type": "application/json",
    }
    targets = json.loads(Path("/cleanup/terminal-pod-targets.json").read_text())

    def api(method, path, body=None):
        return request(method, path, context, headers, body)

    clean(targets, api, datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
