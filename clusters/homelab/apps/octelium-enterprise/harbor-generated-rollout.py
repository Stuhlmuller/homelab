#!/usr/bin/env python3
"""Roll Octelium-owned service proxies after Harbor admission is active."""
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

NAMESPACE = "octelium"
API = "https://kubernetes.default.svc"
SERVICE_ACCOUNT = "/var/run/secrets/kubernetes.io/serviceaccount"
UPSTREAM_PROBE = "ghcr.io/octelium/octelium-vigil:0.35.0"
HARBOR = "harbor.stinkyboi.com/"
ROLLOUT_ANNOTATION = "homelab.stinkyboi.com/harbor-rollout"
ROLLOUT_MARKER = "generated-proxy-mirror-v1"


def api(method, path, body=None):
    token = open(f"{SERVICE_ACCOUNT}/token", encoding="utf-8").read().strip()
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json-patch+json" if method == "PATCH" else "application/json"},
    )
    context = ssl.create_default_context(cafile=f"{SERVICE_ACCOUNT}/ca.crt")
    with urllib.request.urlopen(request, context=context, timeout=15) as response:
        return json.load(response)


def images(spec):
    return [container["image"] for field in ("initContainers", "containers", "ephemeralContainers")
            for container in spec.get(field, [])]


def generated(deployment):
    name = deployment["metadata"]["name"]
    return (name.startswith(("svc-", "upstream-svc-")) and
            any(owner.get("kind") == "ConfigMap" and owner.get("name", "").startswith("svc-")
                for owner in deployment["metadata"].get("ownerReferences", [])))


def matching_pods(deployment, pods):
    selector = deployment["spec"]["selector"]["matchLabels"]
    if not selector or deployment["spec"]["selector"].get("matchExpressions"):
        raise RuntimeError("Generated service proxy has an unexpected Pod selector")
    return [pod for pod in pods if pod.get("status", {}).get("phase") not in ("Succeeded", "Failed")
            and all(pod["metadata"].get("labels", {}).get(key) == value for key, value in selector.items())]


def current_upstream(deployment, pods):
    return any(not image.startswith(HARBOR) for pod in matching_pods(deployment, pods)
               for image in images(pod["spec"]))


def list_pods():
    return api("GET", f"/api/v1/namespaces/{NAMESPACE}/pods")["items"]


def wait_for_admission():
    pod = {"apiVersion": "v1", "kind": "Pod",
           "metadata": {"generateName": "harbor-rewrite-check-", "namespace": NAMESPACE},
           "spec": {"restartPolicy": "Never", "containers": [{"name": "check", "image": UPSTREAM_PROBE}]}}
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        try:
            result = api("POST", f"/api/v1/namespaces/{NAMESPACE}/pods?dryRun=All", pod)
            if images(result["spec"]) == [
                "harbor.stinkyboi.com/mirror/ghcr.io/octelium/octelium-vigil:0.35.0"
                "@sha256:a8d60479c8d7c0e1deb63c9ef33bb3bb0701b2cf589bc709a2bdef6e5a3f2390"
            ]:
                return
        except (urllib.error.URLError, TimeoutError, KeyError):
            pass
        time.sleep(5)
    raise RuntimeError("Harbor admission did not rewrite the dry-run Pod within ten minutes")


def rollout_marker(deployment):
    return (deployment["spec"]["template"]["metadata"].get("annotations") or {}).get(ROLLOUT_ANNOTATION)


def require_same_owner(actual, expected):
    metadata = actual["metadata"]
    if (not generated(actual) or metadata["uid"] != expected["metadata"]["uid"]
            or metadata.get("ownerReferences") != expected["metadata"].get("ownerReferences")
            or actual["spec"].get("replicas", 1) < 1):
        raise RuntimeError("Generated service proxy ownership or activation changed")


def rollout(deployment):
    name = deployment["metadata"]["name"]
    path = f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments/{urllib.parse.quote(name, safe='')}"
    actual = api("GET", path)
    require_same_owner(actual, deployment)
    if rollout_marker(actual) != ROLLOUT_MARKER:
        metadata = actual["metadata"]
        annotations_path = "/spec/template/metadata/annotations"
        patch = [
            {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
            {"op": "test", "path": "/metadata/resourceVersion", "value": metadata["resourceVersion"]},
        ]
        if actual["spec"]["template"]["metadata"].get("annotations") is None:
            patch.append({"op": "add", "path": annotations_path, "value": {ROLLOUT_ANNOTATION: ROLLOUT_MARKER}})
        else:
            key = ROLLOUT_ANNOTATION.replace("/", "~1")
            patch.append({"op": "add", "path": f"{annotations_path}/{key}", "value": ROLLOUT_MARKER})
        api("PATCH", path, patch)

    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        actual = api("GET", path)
        require_same_owner(actual, deployment)
        if rollout_marker(actual) != ROLLOUT_MARKER:
            raise RuntimeError(f"{name}: rollout marker changed during reconciliation")
        desired = actual["spec"].get("replicas", 1)
        status = actual.get("status", {})
        pods = matching_pods(actual, list_pods())
        ready_mirrored = [
            pod for pod in pods if not pod["metadata"].get("deletionTimestamp")
            and pod["metadata"].get("annotations", {}).get(ROLLOUT_ANNOTATION) == ROLLOUT_MARKER
            and all(image.startswith(HARBOR) for image in images(pod["spec"]))
            and any(condition["type"] == "Ready" and condition["status"] == "True"
                    for condition in pod.get("status", {}).get("conditions", []))
        ]
        if (status.get("observedGeneration", 0) >= actual["metadata"]["generation"]
                and status.get("updatedReplicas", 0) >= desired
                and status.get("availableReplicas", 0) >= desired
                and len(ready_mirrored) >= desired
                and not current_upstream(actual, pods)):
            print(f"{name}: Harbor Pods ready", flush=True)
            return
        time.sleep(5)
    raise RuntimeError(f"{name}: Harbor rollout did not become ready within five minutes")


def main():
    wait_for_admission()
    deployments = api("GET", f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments")["items"]
    candidates = sorted((item for item in deployments if generated(item)
                         and item["spec"].get("replicas", 1) > 0),
                        key=lambda item: item["metadata"]["name"])
    for deployment in candidates:
        if rollout_marker(deployment) == ROLLOUT_MARKER or current_upstream(deployment, list_pods()):
            rollout(deployment)
    print(f"Checked {len(candidates)} generated service proxies", flush=True)


if __name__ == "__main__":
    main()
