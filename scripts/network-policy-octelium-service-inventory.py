#!/usr/bin/env python3
"""Read-only Octelium Service and emergency fallback inventory.

The output contains Kubernetes object identities and readiness, never endpoint
addresses, ports, upstream URLs, or credentials. It is an observation, not an
evacuation receipt or proof that a client can reach a Service.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FALLBACK_SOURCE = ROOT / "clusters/homelab/apps/octelium-enterprise/emergency-dataplane.yaml"
API_SERVER = "https://10.1.0.199:6443"
NAMESPACE = "octelium"
NATIVE_NODE = "zimaboard-0"
FALLBACK_NODE = "acer"
FALLBACK_LABEL = "homelab.rst.io/emergency-dataplane"
EXPECTED_FALLBACK_DEPLOYMENTS = 25
REQUIRED_FALLBACKS = {"ingress": "emergency-octelium-ingress",
                      "octovigil": "emergency-octelium-octovigil"}
MAX_RESPONSE = 8 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def complete_list(value, kind):
    require(isinstance(value, dict) and value.get("kind") == kind and
            isinstance(value.get("metadata"), dict) and
            isinstance(value["metadata"].get("resourceVersion"), str) and
            bool(value["metadata"]["resourceVersion"]) and
            not value["metadata"].get("continue") and
            isinstance(value.get("items"), list), kind + " is incomplete")
    for item in value["items"]:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        require(isinstance(metadata, dict) and
                metadata.get("namespace") == NAMESPACE and
                isinstance(metadata.get("name"), str) and bool(metadata["name"]),
                kind + " contains an invalid object")
    return value["items"]


def labels_match(selector, labels):
    return all(labels.get(key) == value for key, value in selector.items())


def fallback_sources(documents):
    """Read the source-owned fallback Pod labels without copying private data."""
    require(isinstance(documents, list) and bool(documents),
            "emergency fallback source is empty")
    result = {}
    names = set()
    for item in documents:
        require(isinstance(item, dict) and item.get("kind") == "Deployment",
                "emergency fallback source contains a non-Deployment")
        metadata, spec = item.get("metadata"), item.get("spec")
        require(isinstance(metadata, dict) and isinstance(spec, dict) and
                metadata.get("namespace") == NAMESPACE and
                isinstance(metadata.get("name"), str) and
                metadata["name"].startswith("emergency-octelium-") and
                metadata["name"] not in names and spec.get("replicas") == 1,
                "emergency fallback Deployment is invalid")
        names.add(metadata["name"])
        template = spec.get("template")
        pod_spec = template.get("spec") if isinstance(template, dict) else None
        pod_meta = template.get("metadata") if isinstance(template, dict) else None
        labels = pod_meta.get("labels") if isinstance(pod_meta, dict) else None
        selector = spec.get("selector")
        selected = selector.get("matchLabels") if isinstance(selector, dict) else None
        require(isinstance(pod_spec, dict) and
                pod_spec.get("nodeSelector") == {"kubernetes.io/hostname": FALLBACK_NODE} and
                isinstance(labels, dict) and labels and
                all(isinstance(k, str) and isinstance(v, str) and v
                    for k, v in labels.items()) and
                isinstance(selected, dict) and bool(selected) and
                labels_match(selected, labels),
                "emergency fallback Pod contract is invalid")
        marker = labels.get(FALLBACK_LABEL)
        require(isinstance(marker, str) and marker and marker not in result,
                "emergency fallback marker is missing or duplicated")
        result[marker] = {"deployment": metadata["name"], "labels": labels}
    require(len(result) == EXPECTED_FALLBACK_DEPLOYMENTS,
            "emergency fallback Deployment count differs from reviewed source")
    require(all(result.get(marker, {}).get("deployment") == name
                for marker, name in REQUIRED_FALLBACKS.items()),
            "critical emergency fallback source is missing")
    return result


def object_pods(pod_list):
    pods = {}
    for item in complete_list(pod_list, "PodList"):
        metadata, spec, status = item["metadata"], item.get("spec"), item.get("status")
        uid, name = metadata.get("uid"), metadata["name"]
        labels = metadata.get("labels")
        node = spec.get("nodeName", "") if isinstance(spec, dict) else None
        require(isinstance(uid, str) and uid and isinstance(spec, dict) and
                isinstance(node, str) and
                isinstance(status, dict) and isinstance(labels, dict) and
                all(isinstance(k, str) and isinstance(v, str)
                    for k, v in labels.items()) and (name, uid) not in pods,
                "Pod identity, placement, or labels are invalid")
        conditions = status.get("conditions") or []
        require(isinstance(conditions, list), "Pod conditions are invalid")
        ready = (not metadata.get("deletionTimestamp") and
                 status.get("phase") == "Running" and
                 any(isinstance(condition, dict) and condition.get("type") == "Ready"
                     and condition.get("status") == "True" for condition in conditions))
        pods[(name, uid)] = {"uid": uid, "node": node,
                             "labels": labels, "ready": ready}
    return pods


def service_inventory(service_list, pod_list, slice_list, source, native_node,
                      captured_at):
    require(native_node == NATIVE_NODE, "native Node must be zimaboard-0")
    fallback = fallback_sources(source)
    pods = object_pods(pod_list)
    services = {}
    for item in complete_list(service_list, "ServiceList"):
        metadata, spec = item["metadata"], item.get("spec")
        name, uid = metadata["name"], metadata.get("uid")
        selector = spec.get("selector") if isinstance(spec, dict) else None
        require(isinstance(uid, str) and uid and isinstance(spec, dict) and
                (selector is None or isinstance(selector, dict)) and
                all(isinstance(k, str) and k and isinstance(v, str)
                    for k, v in (selector or {}).items()) and name not in services,
                "Service identity or selector is invalid")
        services[name] = {"id": NAMESPACE + "/" + name, "uid": uid,
                          "selector": selector or {}, "ready": set()}

    for item in complete_list(slice_list, "EndpointSliceList"):
        metadata = item["metadata"]
        labels = metadata.get("labels")
        name = labels.get("kubernetes.io/service-name") if isinstance(labels, dict) else None
        require(isinstance(name, str) and name in services,
                "EndpointSlice has no listed Service")
        service = services[name]
        owners = metadata.get("ownerReferences")
        require(isinstance(owners, list) and any(
            isinstance(owner, dict) and owner.get("kind") == "Service" and
            owner.get("name") == name and owner.get("uid") == service["uid"]
            for owner in owners),
            "EndpointSlice is not owned by the current Service UID")
        endpoints = item.get("endpoints")
        require(isinstance(endpoints, list), "EndpointSlice endpoints are invalid")
        for endpoint in endpoints:
            require(isinstance(endpoint, dict), "EndpointSlice endpoint is invalid")
            conditions = endpoint.get("conditions") or {}
            require(isinstance(conditions, dict), "EndpointSlice conditions are invalid")
            require(conditions.get("ready") is None or
                    type(conditions["ready"]) is bool,
                    "EndpointSlice Ready condition is invalid")
            if conditions.get("ready") is False:
                continue
            target = endpoint.get("targetRef")
            key = ((target.get("name"), target.get("uid"))
                   if isinstance(target, dict) and target.get("kind") == "Pod" and
                   target.get("namespace", NAMESPACE) == NAMESPACE else None)
            pod = pods.get(key)
            require(conditions.get("terminating") is not True and
                    conditions.get("serving") is not False and pod and
                    pod["ready"] and service["selector"] and
                    labels_match(service["selector"], pod["labels"]) and
                    (endpoint.get("nodeName") is None or
                     endpoint["nodeName"] == pod["node"]),
                    "Ready endpoint identity, selector, or Pod readiness differs")
            marker = pod["labels"].get(FALLBACK_LABEL)
            require(marker is None or
                    (marker in fallback and pod["node"] == FALLBACK_NODE and
                     labels_match(fallback[marker]["labels"], pod["labels"])),
                    "Ready fallback endpoint differs from source")
            service["ready"].add((pod["node"], pod["uid"]))

    mapping = {name: [] for name in services}
    unmapped = []
    for marker, definition in fallback.items():
        matches = [name for name, service in services.items()
                   if service["selector"] and
                   labels_match(service["selector"], definition["labels"])]
        if len(matches) != 1:
            unmapped.append(definition["deployment"])
        else:
            mapping[matches[0]].append(marker)

    rows = []
    for name, service in sorted(services.items()):
        selector = service["selector"]
        selected = sorted(pod["uid"] for pod in pods.values()
                          if selector and labels_match(selector, pod["labels"]))
        selected_native = sorted(pod["uid"] for pod in pods.values()
                                 if pod["node"] == native_node and selector and
                                 labels_match(selector, pod["labels"]))
        ready_native = sorted(uid for node, uid in service["ready"]
                              if node == native_node)
        ready_fallback = sorted(uid for node, uid in service["ready"]
                                if node == FALLBACK_NODE and
                                any(pod["uid"] == uid and
                                    pod["labels"].get(FALLBACK_LABEL) in mapping[name] and
                                    labels_match(fallback[pod["labels"][FALLBACK_LABEL]]["labels"],
                                                 pod["labels"])
                                    for pod in pods.values()))
        ready_other = sorted(uid for node, uid in service["ready"]
                             if node != native_node and uid not in ready_fallback)
        declared = bool(mapping[name])
        if len(mapping[name]) > 1:
            classification = "unresolved"
        elif declared and ready_fallback and not ready_other:
            classification = "fallback-ready"
        elif declared:
            classification = "fallback-unready"
        elif ready_native and not ready_other:
            classification = "native-only"
        elif selected_native or ready_native or not service["ready"]:
            classification = "unresolved"
        else:
            classification = "not-native-dependent"
        rows.append({"id": service["id"], "uid": service["uid"],
                     "selectorSha256": digest(selector),
                     "declaredFallback": declared, "classification": classification,
                     "selectedPodUids": selected,
                     "selectedNativePodUids": selected_native,
                     "readyNativePodUids": ready_native,
                     "readyFallbackPodUids": ready_fallback,
                     "readyOtherPodUids": ready_other})

    identities = [{"id": row["id"], "uid": row["uid"],
                   "selectorSha256": row["selectorSha256"]} for row in rows]
    counts = {kind: sum(row["classification"] == kind for row in rows)
              for kind in ("fallback-ready", "fallback-unready", "native-only",
                           "not-native-dependent", "unresolved")}
    return {"format": 1, "purpose": "read-only-octelium-service-observation",
            "admission": "unproven", "baselineQualified": False,
            "capturedAt": captured_at, "nativeNode": native_node,
            "fallbackNode": FALLBACK_NODE,
            "resourceVersions": {"services": service_list["metadata"]["resourceVersion"],
                                 "pods": pod_list["metadata"]["resourceVersion"],
                                 "endpointSlices": slice_list["metadata"]["resourceVersion"]},
            "sourceFallbackDeployments": sorted(item["deployment"]
                                                for item in fallback.values()),
            "unmappedFallbackDeployments": sorted(unmapped),
            "serviceIdentitySha256": digest(identities),
            "observationSha256": digest(rows), "counts": counts,
            "nativeOnlyServices": [row["id"] for row in rows
                                   if row["classification"] == "native-only"],
            "services": rows}


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True,
                            timeout=30, check=True)
    require(len(result.stdout.encode()) <= MAX_RESPONSE,
            "read-only input exceeds size limit")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-node", required=True)
    args = parser.parse_args()
    try:
        server = command("kubectl", "config", "view", "--minify", "-o",
                         "jsonpath={.clusters[0].cluster.server}").strip()
        require(server == API_SERVER, "authenticated homelab Kubernetes context required")
        source_bytes = FALLBACK_SOURCE.read_bytes()
        require(0 < len(source_bytes) <= MAX_RESPONSE, "fallback source size is invalid")
        source = json.loads(command("yq", "ea", "-o=json", "-I=0", "[.]",
                                    str(FALLBACK_SOURCE)))
        paths = ("/api/v1/namespaces/octelium/services?limit=0",
                 "/api/v1/namespaces/octelium/pods?limit=0",
                 "/apis/discovery.k8s.io/v1/namespaces/octelium/endpointslices?limit=0")
        snapshots = [json.loads(command("kubectl", "--request-timeout=20s",
                                       "get", "--raw", path)) for path in paths]
        captured_at = datetime.now(timezone.utc).isoformat()
        report = service_inventory(*snapshots, source, args.native_node, captured_at)
        report["sourceFallbackSha256"] = hashlib.sha256(source_bytes).hexdigest()
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0
    except ValueError as error:
        print("Read-only Octelium Service inventory blocked: " + str(error),
              file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Read-only Octelium Service inventory blocked; inspect inputs privately",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
