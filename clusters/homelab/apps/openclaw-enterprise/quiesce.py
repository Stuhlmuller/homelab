#!/usr/bin/env python3
"""Fence the stock API and worker before the chart's migration hook."""

import json
import os
import ssl
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

NAMESPACE = "openclaw-system"
RELEASE = "oce"
COMPONENTS = ("api", "worker")
LABELS = {"app.kubernetes.io/name": "openclaw-enterprise", "app.kubernetes.io/instance": RELEASE}
def api(path, method="GET", body=None, missing=False):
    token = Path("/var/run/secrets/kubernetes.io/serviceaccount/token").read_text().strip()
    ca = ssl.create_default_context(cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
    base = (f"https://{os.environ['KUBERNETES_SERVICE_HOST']}:"
            f"{os.environ['KUBERNETES_SERVICE_PORT']}")
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    request = Request(
        base + path,
        data=payload,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, context=ca, timeout=5) as response:
            return json.load(response)
    except HTTPError as error:
        if missing and error.code == 404:
            return None
        raise RuntimeError(f"Kubernetes {method} {path} returned HTTP {error.code}") from None


def deployment_name(component):
    return f"openclaw-enterprise-{component}"


def deployment_path(component):
    return f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments/{deployment_name(component)}"


def pods():
    response = api(f"/api/v1/namespaces/{NAMESPACE}/pods")
    metadata = response.get("metadata") if isinstance(response, dict) else None
    if (not isinstance(response, dict) or response.get("kind") != "PodList" or
            not isinstance(metadata, dict) or
            not isinstance(metadata.get("resourceVersion"), str) or
            metadata["resourceVersion"] in ("", "0") or
            metadata.get("continue") not in (None, "") or
            not isinstance(response.get("items"), list)):
        raise RuntimeError("API/worker Pod list is incomplete or invalid")
    candidates = []
    for pod in response["items"]:
        if not isinstance(pod, dict) or not isinstance(pod.get("metadata"), dict):
            raise RuntimeError("API/worker Pod list is incomplete or invalid")
        pod_meta = pod["metadata"]
        labels = pod_meta.get("labels") or {}
        name = pod_meta.get("name")
        if not isinstance(labels, dict) or not isinstance(name, str):
            raise RuntimeError("API/worker Pod list is incomplete or invalid")
        if ((all(labels.get(key) == value for key, value in LABELS.items()) and
             labels.get("app.kubernetes.io/component") in COMPONENTS) or
                any(name.startswith(deployment_name(component) + "-") for component in COMPONENTS)):
            candidates.append(pod)
    return candidates


def owned(deployment, component, require_observed=True):
    metadata = deployment.get("metadata", {})
    spec = deployment.get("spec", {})
    expected = {**LABELS, "app.kubernetes.io/component": component}
    for labels in (metadata.get("labels", {}), spec.get("selector", {}).get("matchLabels", {}),
                   spec.get("template", {}).get("metadata", {}).get("labels", {})):
        if any(labels.get(key) != value for key, value in expected.items()):
            raise RuntimeError(f"{deployment_name(component)} has unexpected release/component identity")
    if metadata.get("name") != deployment_name(component) or metadata.get("namespace") != NAMESPACE:
        raise RuntimeError(f"{deployment_name(component)} has unexpected namespace/name")
    if not metadata.get("uid") or metadata.get("deletionTimestamp"):
        raise RuntimeError(f"{deployment_name(component)} lacks stable identity")
    if spec.get("replicas") not in (0, 1):
        raise RuntimeError(f"{deployment_name(component)} replicas are outside {{0,1}}")
    if require_observed and deployment.get("status", {}).get("observedGeneration", 0) < metadata.get("generation", 0):
        raise RuntimeError(f"{deployment_name(component)} generation is not observed")


def check_pod_identity(pod):
    labels = pod.get("metadata", {}).get("labels", {})
    component = labels.get("app.kubernetes.io/component")
    name = pod.get("metadata", {}).get("name", "")
    owners = [owner for owner in pod.get("metadata", {}).get("ownerReferences", [])
              if owner.get("controller") is True]
    if (component not in COMPONENTS or any(labels.get(key) != value for key, value in LABELS.items())
            or len(owners) != 1 or owners[0].get("kind") != "ReplicaSet"
            or not owners[0].get("name", "").startswith(deployment_name(component) + "-")
            or not name.startswith(owners[0]["name"] + "-")):
        raise RuntimeError("matching Pod has uncertain release/component ownership")
    if pod.get("status", {}).get("phase") == "Unknown":
        raise RuntimeError("matching Pod has unknown writer state")


def scale_zero(component, deployment):
    path = deployment_path(component) + "/scale"
    scale = api(path)
    metadata = scale.get("metadata", {})
    if metadata.get("uid") != deployment["metadata"]["uid"]:
        raise RuntimeError(f"{deployment_name(component)} scale identity changed")
    if (not isinstance(metadata.get("resourceVersion"), str) or
            metadata["resourceVersion"] in ("", "0")):
        raise RuntimeError(f"{deployment_name(component)} scale lacks resourceVersion")
    if scale.get("spec", {}).get("replicas") not in (0, 1):
        raise RuntimeError(f"{deployment_name(component)} scale replicas are outside {{0,1}}")
    if scale["spec"]["replicas"] == 0:
        return
    scale["spec"]["replicas"] = 0
    updated = api(path, method="PUT", body=scale)
    if updated.get("spec", {}).get("replicas") != 0:
        raise RuntimeError(f"{deployment_name(component)} scale update was not accepted")


def main():
    deployments = {component: api(deployment_path(component), missing=True) for component in COMPONENTS}
    if all(deployment is None for deployment in deployments.values()):
        if pods():
            raise RuntimeError("first install has unexpected API/worker Pods")
        print("openclaw-enterprise-quiesce: empty first install")
        return
    if any(deployment is None for deployment in deployments.values()):
        raise RuntimeError("only one API/worker Deployment exists")
    for component, deployment in deployments.items():
        owned(deployment, component)
    existing_pods = pods()
    for pod in existing_pods:
        check_pod_identity(pod)
    if any(sum(pod["metadata"]["labels"].get("app.kubernetes.io/component") == component
               for pod in existing_pods) > 1 for component in COMPONENTS):
        raise RuntimeError("multiple API/worker Pods make writer ownership uncertain")

    for component, deployment in deployments.items():
        scale_zero(component, deployment)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        current = {component: api(deployment_path(component)) for component in COMPONENTS}
        for component, deployment in current.items():
            owned(deployment, component, require_observed=False)
            if deployment["metadata"]["uid"] != deployments[component]["metadata"]["uid"]:
                raise RuntimeError(f"{deployment_name(component)} identity changed during quiesce")
        remaining = pods()
        for pod in remaining:
            check_pod_identity(pod)
        if all(deployment["spec"]["replicas"] == 0 for deployment in current.values()) and not remaining:
            print("openclaw-enterprise-quiesce: no API/worker writers remain")
            return
        time.sleep(2)
    raise RuntimeError("API/worker Pods did not terminate before migration")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"openclaw-enterprise-quiesce: {error}", file=sys.stderr)
        sys.exit(1)
