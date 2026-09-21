#!/usr/bin/env python3
"""Check cold-start prerequisites in the combined Harbor Helm/Kustomize render.

Read a JSON array from stdin. This checks declared availability and Argo sync
ordering; controller readiness and registry acceptance still need live checks.
"""

import json
import sys


NAMESPACE = "harbor"
WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}
PREREQUISITES = {"Secret", "ConfigMap", "PersistentVolumeClaim"}
PHASES = {"PreSync": 0, "Sync": 1, "PostSync": 2}
MAX_INPUT_BYTES = 4 * 1024 * 1024


def identity(resource):
    metadata = resource.get("metadata", {})
    return (resource.get("kind"), metadata.get("namespace") or NAMESPACE, metadata.get("name"))


def label(key):
    kind, namespace, name = key
    return f"{kind} {namespace}/{name}"


def sync_order(resource):
    annotations = resource.get("metadata", {}).get("annotations", {}) or {}
    hook = annotations.get("argocd.argoproj.io/hook", "Sync")
    if hook in {"Skip", "SyncFail", "PostDelete"}:
        return None  # These resources do not run during a successful installation.
    if hook not in PHASES:
        raise ValueError(f"{label(identity(resource))} has an unsupported sync hook")
    try:
        wave = int(annotations.get("argocd.argoproj.io/sync-wave", "0"))
    except (TypeError, ValueError):
        raise ValueError(f"{label(identity(resource))} has an invalid sync wave") from None
    return PHASES[hook], wave


def pod_spec(resource):
    spec = resource.get("spec", {})
    if resource["kind"] == "Pod":
        return spec
    if resource["kind"] == "CronJob":
        spec = spec.get("jobTemplate", {}).get("spec", {})
    return spec.get("template", {}).get("spec", {})


def required_references(pod):
    """Only Kubernetes references that can block these pods from starting."""
    references = set()

    def add(kind, reference, name_key="name"):
        if reference is not None and reference.get("optional") is not True:
            references.add((kind, reference.get(name_key)))

    for volume in pod.get("volumes", []):
        add("Secret", volume.get("secret"), "secretName")
        add("ConfigMap", volume.get("configMap"))
        add("PersistentVolumeClaim", volume.get("persistentVolumeClaim"), "claimName")
        for source in volume.get("projected", {}).get("sources", []):
            add("Secret", source.get("secret"))
            add("ConfigMap", source.get("configMap"))
    for reference in pod.get("imagePullSecrets", []):
        add("Secret", reference)
    for field in ("containers", "initContainers", "ephemeralContainers"):
        for container in pod.get(field, []):
            for variable in container.get("env", []):
                source = variable.get("valueFrom", {})
                add("Secret", source.get("secretKeyRef"))
                add("ConfigMap", source.get("configMapKeyRef"))
            for source in container.get("envFrom", []):
                add("Secret", source.get("secretRef"))
                add("ConfigMap", source.get("configMapRef"))
    return references


def validate(resources):
    if not isinstance(resources, list) or len(resources) > 1000:
        raise ValueError("expected a JSON array of at most 1000 rendered resources")
    if any(not isinstance(resource, dict) for resource in resources):
        raise ValueError("every rendered resource must be a JSON object")
    providers = {}
    workloads = []
    errors = []
    for resource in resources:
        key = identity(resource)
        kind, namespace, name = key
        if namespace != NAMESPACE:
            continue
        if kind not in PREREQUISITES | WORKLOADS | {"ExternalSecret", "Certificate"}:
            continue
        if not isinstance(name, str) or not name:
            raise ValueError("a Harbor prerequisite or workload lacks metadata.name")
        order = sync_order(resource)
        if order is None:
            continue
        if kind in WORKLOADS:
            workloads.append((resource, order))
        produced = None
        if kind in PREREQUISITES:
            produced = key
        elif kind == "ExternalSecret":
            target = resource.get("spec", {}).get("target", {})
            # Merge/None do not create a missing Secret on a fresh cluster.
            if target.get("creationPolicy", "Owner") in {"Owner", "Orphan"}:
                produced = ("Secret", namespace, target.get("name") or name)
        elif kind == "Certificate":
            produced = ("Secret", namespace, resource.get("spec", {}).get("secretName"))
        if produced is not None:
            if not isinstance(produced[2], str) or not produced[2]:
                errors.append(f"{label(key)} has no target Secret name")
            elif produced in providers:
                errors.append(f"{label(produced)} has multiple producers in the combined render")
            else:
                providers[produced] = (order, key)
    if not workloads:
        errors.append("the combined render contains no Harbor workloads")
    for resource, consumer_order in workloads:
        consumer = label(identity(resource))
        pod = pod_spec(resource)
        if not pod.get("containers"):
            errors.append(f"{consumer} has no rendered pod containers")
        for kind, name in sorted(required_references(pod), key=lambda ref: (ref[0], str(ref[1]))):
            prerequisite = (kind, NAMESPACE, name)
            if prerequisite not in providers:
                errors.append(f"{consumer} requires {label(prerequisite)}, absent from the combined render")
                continue
            producer_order, producer = providers[prerequisite]
            if producer_order > consumer_order:
                errors.append(
                    f"{consumer} requires {label(prerequisite)} before its producer "
                    f"{label(producer)} is applied (phase/wave {producer_order} > {consumer_order})"
                )
    return errors


def main():
    if len(sys.argv) != 1:
        raise ValueError("usage: harbor-render-check.py < combined-render.json")
    source = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(source) > MAX_INPUT_BYTES:
        raise ValueError("combined render exceeds the 4 MiB input limit")
    resources = json.loads(source)
    errors = validate(resources)
    if errors:
        raise ValueError("; ".join(errors))
    print("Harbor rendered prerequisites: required Secrets, ConfigMaps, PVCs and sync ordering verified")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        sys.exit(f"Harbor rendered prerequisites: {error}")
