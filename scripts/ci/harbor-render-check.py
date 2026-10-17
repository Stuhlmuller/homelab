#!/usr/bin/env python3
"""Check cold-start prerequisites in the combined Harbor Helm/Kustomize render.

Read a JSON array from stdin. This checks declared availability and Argo sync
ordering; controller readiness and registry acceptance still need live checks.
"""

import json
import sys
from pathlib import Path


NAMESPACE = "harbor"
WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}
PREREQUISITES = {"Secret", "ConfigMap", "PersistentVolumeClaim"}
PHASES = {"PreSync": 0, "Sync": 1, "PostSync": 2}
MAX_INPUT_BYTES = 4 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUTOMATION = ROOT / "clusters/homelab/apps/harbor/image-automation.json"
DEFAULT_STATE = ROOT / "scripts/config/image-automation-state.json"
HARBOR_PULL_SECRET = "harbor-pull"
HARBOR_PULL_PARAMETER = "/homelab/harbor/robot-pull-password"
HARBOR_PULL_TEMPLATE = (
    '{"auths":{"harbor.stinkyboi.com":{"username":"robot$homelab+pull",'
    '"password":{{ .password | toJson }},"auth":"'
    '{{ printf "robot$homelab+pull:%s" .password | b64enc }}"}}}'
)


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


def _images(value):
    if isinstance(value, dict):
        for key in ("containers", "initContainers", "ephemeralContainers"):
            for container in value.get(key, []):
                image = container.get("image")
                if isinstance(image, str):
                    yield image
        for child in value.values():
            yield from _images(child)
    elif isinstance(value, list):
        for child in value:
            yield from _images(child)


def image_repository(image):
    return image.split("@", 1)[0].rsplit(":", 1)[0]


def harbor_pull_secret_errors(resources):
    """Require the staged Harbor pull credential and exporter reference."""
    providers = [resource for resource in resources
                 if resource.get("kind") == "ExternalSecret"
                 and identity(resource) == ("ExternalSecret", NAMESPACE, HARBOR_PULL_SECRET)]
    errors = []
    if len(providers) != 1:
        errors.append(f"expected one ExternalSecret {NAMESPACE}/{HARBOR_PULL_SECRET}")
    else:
        secret = providers[0]
        spec = secret.get("spec", {})
        revision = secret.get("metadata", {}).get("annotations", {}).get(
            "homelab.stuhlmuller.dev/generated-secret-revision")
        if spec.get("refreshPolicy") != "OnChange" or not revision:
            errors.append("Harbor pull auth must retain its generated-secret revision refresh contract")
        if spec.get("secretStoreRef") != {"kind": "ClusterSecretStore", "name": "aws-ssm"}:
            errors.append("Harbor pull auth must use the aws-ssm ClusterSecretStore")
        if spec.get("data") != [{"secretKey": "password", "remoteRef": {
                "key": HARBOR_PULL_PARAMETER, "conversionStrategy": "Default",
                "decodingStrategy": "None", "metadataPolicy": "None"}}] or spec.get("dataFrom"):
            errors.append("Harbor pull auth must read only the Harbor pull-password parameter")
        target = spec.get("target", {})
        if (target.get("name") != HARBOR_PULL_SECRET or target.get("creationPolicy") != "Owner"
                or target.get("deletionPolicy") != "Retain"):
            errors.append("Harbor pull auth must own and retain its target Secret")
        template = target.get("template", {})
        if (template.get("engineVersion") != "v2" or template.get("mergePolicy", "Replace") != "Replace"
                or template.get("type") != "kubernetes.io/dockerconfigjson"
                or template.get("data") != {".dockerconfigjson": HARBOR_PULL_TEMPLATE}
                or template.get("templateFrom")):
            errors.append("Harbor pull auth must render only the read-only robot Docker config")
        if sync_order(secret) != (PHASES["Sync"], -5):
            errors.append("Harbor pull auth must precede Harbor workloads at sync wave -5")
    exporters = [resource for resource in resources
                 if resource.get("kind") == "Deployment"
                 and identity(resource) == ("Deployment", NAMESPACE, "harbor-vulnerability-exporter")]
    if len(exporters) != 1:
        errors.append("expected one Harbor vulnerability exporter Deployment")
    elif pod_spec(exporters[0]).get("imagePullSecrets") != [{"name": HARBOR_PULL_SECRET}]:
        errors.append("Harbor vulnerability exporter must reference harbor-pull exactly")
    for resource in resources:
        if resource.get("kind") not in WORKLOADS or identity(resource)[1] != NAMESPACE:
            continue
        pod = pod_spec(resource)
        for volume in pod.get("volumes", []):
            refs = [volume.get("secret", {}).get("secretName")]
            refs += [source.get("secret", {}).get("name")
                     for source in volume.get("projected", {}).get("sources", [])]
            if HARBOR_PULL_SECRET in refs:
                errors.append(f"{label(identity(resource))} must not mount harbor-pull")
        containers = pod.get("containers", []) + pod.get("initContainers", [])
        containers += pod.get("ephemeralContainers", [])
        for container in containers:
            refs = [entry.get("secretRef", {}).get("name") for entry in container.get("envFrom", [])]
            refs += [entry.get("valueFrom", {}).get("secretKeyRef", {}).get("name")
                     for entry in container.get("env", [])]
            if HARBOR_PULL_SECRET in refs:
                errors.append(f"{label(identity(resource))} must not expose harbor-pull as environment")
    return errors


def native_harbor_pull_errors(resources, repositories):
    errors = []
    for resource in resources:
        if resource.get("kind") not in WORKLOADS or identity(resource)[1] != NAMESPACE:
            continue
        pod = pod_spec(resource)
        if any(image_repository(image) in repositories for image in _images(pod)) \
                and pod.get("imagePullSecrets") != [{"name": HARBOR_PULL_SECRET}]:
            errors.append(f"{label(identity(resource))} must pull native Harbor images using harbor-pull")
    return errors


def receipt_errors(resources, config_path=DEFAULT_AUTOMATION, state_path=DEFAULT_STATE):
    """Require verified publication before an enrolled Harbor image renders."""
    if not config_path.exists() or not state_path.exists():
        return []
    config = json.loads(config_path.read_text())
    state = json.loads(state_path.read_text())
    enrolled = {
        item["image_id"]: item for item in config.get("images", [])
        if any(consumer.get("image_id") == item.get("image_id")
               and consumer.get("automation_status") == "enrolled"
               for consumer in config.get("consumers", []))
    }
    rendered = set(_images(resources))
    errors = []
    native_repositories = {
        image_repository(image["destination"])
        for image in enrolled.values()
        if image.get("source", "").startswith("cgr.dev/chainguard/")
        and image_repository(image["destination"]).startswith("harbor.stinkyboi.com/homelab/")
    }
    errors.extend(native_harbor_pull_errors(resources, native_repositories))
    for image_id, image in enrolled.items():
        destination = image["destination"]
        repository = image_repository(destination)
        if not any(image_repository(ref) == repository for ref in rendered):
            continue
        receipt = state.get("receipts", {}).get(image_id)
        if not isinstance(receipt, dict) or receipt.get("destination_ref") != destination \
                or receipt.get("consumer_access") is not True:
            errors.append(f"Enrolled Harbor image lacks verified receipt: {image_id}")
    return errors


def main():
    if len(sys.argv) not in (1, 3, 5) or len(sys.argv[1:]) % 2:
        raise ValueError("usage: harbor-render-check.py [--automation-config FILE --automation-state FILE] < combined-render.json")
    options = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    if set(options) - {"--automation-config", "--automation-state"}:
        raise ValueError("unsupported option")
    source = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(source) > MAX_INPUT_BYTES:
        raise ValueError("combined render exceeds the 4 MiB input limit")
    resources = json.loads(source)
    errors = validate(resources)
    errors.extend(harbor_pull_secret_errors(resources))
    errors.extend(receipt_errors(
        resources,
        Path(options.get("--automation-config", DEFAULT_AUTOMATION)),
        Path(options.get("--automation-state", DEFAULT_STATE)),
    ))
    if errors:
        raise ValueError("; ".join(errors))
    print("Harbor rendered prerequisites: required Secrets, ConfigMaps, PVCs and sync ordering verified")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        sys.exit(f"Harbor rendered prerequisites: {error}")
