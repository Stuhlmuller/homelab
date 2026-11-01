#!/usr/bin/env python3
"""Read-only capacity and Pod inventory for a possible NetworkPolicy canary."""

import argparse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import json
import re
import runpy
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
CLEANUP = runpy.run_path(str(ROOT / "scripts/network-policy-cleanup.py"))
API_SERVER = "https://10.1.0.199:6443"
MAX_RESPONSE = 8 * 1024 * 1024
NODE_NAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
QUANTITY = re.compile(r"([0-9]+(?:\.[0-9]+)?)(?:([eE][+-]?[0-9]+)|(Ki|Mi|Gi|Ti|Pi|Ei|k|M|G|T|P|E|m|u|n))?\Z")
UNITS = {
    None: 1, "n": Decimal("0.000000001"), "u": Decimal("0.000001"),
    "m": Decimal("0.001"), "k": 1000, "M": 1000**2,
    "G": 1000**3, "T": 1000**4, "P": 1000**5, "E": 1000**6,
    "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3,
    "Ti": 1024**4, "Pi": 1024**5, "Ei": 1024**6,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def memory_bytes(value):
    require(isinstance(value, str), "memory quantity must be a string")
    match = QUANTITY.fullmatch(value)
    require(match is not None, "unsupported memory quantity")
    factor = Decimal(10) ** int(match[2][1:]) if match[2] else UNITS[match[3]]
    size = Decimal(match[1]) * factor
    return int(size.to_integral_value(rounding=ROUND_CEILING))


def resource_memory(container):
    resources = container.get("resources") or {}
    require(isinstance(resources, dict), "container resources are invalid")
    requests, limits = resources.get("requests") or {}, resources.get("limits") or {}
    require(isinstance(requests, dict) and isinstance(limits, dict),
            "container resource maps are invalid")
    # Admission normally copies a limit into an absent request; retain that
    # conservative value if a fixture or older API response has not done so.
    value = requests.get("memory", limits.get("memory", "0"))
    return memory_bytes(value)


def check_resize_status(pod, containers, init_containers):
    status = pod.get("status") or {}
    require(isinstance(status, dict), "Pod status is invalid")
    require(not status.get("resize"), "in-place resized Pod needs separate review")
    expected = {container["name"]: resource_memory(container)
                for container in [*containers, *init_containers]}
    for field in ("containerStatuses", "initContainerStatuses"):
        entries = status.get(field) or []
        require(isinstance(entries, list), "container status list is invalid")
        for entry in entries:
            require(isinstance(entry, dict) and entry.get("name") in expected,
                    "container status identity is invalid")
            current = entry.get("resources") or {}
            allocated = entry.get("allocatedResources") or {}
            require(isinstance(current, dict) and isinstance(allocated, dict),
                    "resized container resources are invalid")
            current_requests = current.get("requests") or {}
            require(isinstance(current_requests, dict),
                    "resized container request map is invalid")
            for value in (current_requests.get("memory"), allocated.get("memory")):
                if value is not None:
                    require(memory_bytes(value) == expected[entry["name"]],
                            "in-place resized Pod request differs from its spec")


def pod_memory_request(pod):
    # Kubernetes v1.34 component-helpers/resource/helpers.go computes the max
    # app/init phase, then applies a Pod-level request and Pod overhead.
    spec = pod.get("spec")
    require(isinstance(spec, dict), "Pod spec is invalid")
    containers, init_containers = spec.get("containers"), spec.get("initContainers") or []
    require(isinstance(containers, list) and bool(containers)
            and isinstance(init_containers, list), "Pod container lists are invalid")
    all_containers = [*containers, *init_containers]
    require(all(isinstance(item, dict) and isinstance(item.get("name"), str)
                and item["name"] for item in all_containers)
            and len({item["name"] for item in all_containers}) == len(all_containers),
            "Pod container identity is invalid")
    check_resize_status(pod, containers, init_containers)
    app_sum = sum(resource_memory(item) for item in containers)
    sidecars = 0
    maximum = app_sum
    for item in init_containers:
        request = resource_memory(item)
        if item.get("restartPolicy") == "Always":
            sidecars += request
            maximum = max(maximum, sidecars)
        else:
            require(item.get("restartPolicy") in (None, "Never", "OnFailure"),
                    "unknown init container restart policy")
            maximum = max(maximum, sidecars + request)
    maximum = max(maximum, app_sum + sidecars)
    pod_resources = spec.get("resources") or {}
    require(isinstance(pod_resources, dict), "Pod-level resources are invalid")
    pod_requests = pod_resources.get("requests") or {}
    require(isinstance(pod_requests, dict), "Pod-level request map is invalid")
    if "memory" in pod_requests:
        maximum = memory_bytes(pod_requests["memory"])
    overhead = spec.get("overhead") or {}
    require(isinstance(overhead, dict), "Pod overhead is invalid")
    return maximum + memory_bytes(overhead.get("memory", "0"))


def allowed_system_daemonset(pod):
    metadata = pod["metadata"]
    namespace = metadata["namespace"]
    owners = metadata.get("ownerReferences") or []
    if (namespace not in {"kube-system", "istio-system"} or
            metadata.get("deletionTimestamp") or
            not isinstance(owners, list)):
        return False
    return any(
        isinstance(owner, dict) and owner.get("kind") == "DaemonSet"
        and owner.get("controller") is True
        and isinstance(owner.get("name"), str) and bool(owner["name"])
        and (owner["name"] in CLEANUP["ISTIO_SYSTEM_DAEMONSETS"]
             if namespace == "istio-system"
             else owner["name"] not in {CLEANUP["ENFORCER"], CLEANUP["CLEANUP"]})
        for owner in owners)


def complete_pods(listing, node_name):
    require(isinstance(listing, dict) and listing.get("kind") == "PodList"
            and isinstance(listing.get("metadata"), dict)
            and isinstance(listing["metadata"].get("resourceVersion"), str)
            and bool(listing["metadata"]["resourceVersion"])
            and not listing["metadata"].get("continue")
            and isinstance(listing.get("items"), list),
            "assigned Pod inventory is incomplete")
    seen = set()
    rows = []
    for pod in listing["items"]:
        require(isinstance(pod, dict) and isinstance(pod.get("metadata"), dict)
                and isinstance(pod.get("spec"), dict)
                and isinstance(pod.get("status"), dict),
                "assigned Pod entry is invalid")
        meta, spec, status = pod["metadata"], pod["spec"], pod["status"]
        identity = (meta.get("namespace"), meta.get("name"), meta.get("uid"))
        require(all(isinstance(value, str) and value for value in identity)
                and identity not in seen and spec.get("nodeName") == node_name
                and isinstance(status.get("phase"), str),
                "assigned Pod identity or node differs")
        seen.add(identity)
        request = pod_memory_request(pod)
        terminal = status["phase"] in {"Succeeded", "Failed"}
        rows.append({"namespace": identity[0], "name": identity[1], "uid": identity[2],
                     "phase": status["phase"], "allowedSystemDaemonSet":
                     allowed_system_daemonset(pod), "effectiveRequestBytes": request,
                     "scheduledRequestBytes": 0 if terminal else request})
    return sorted(rows, key=lambda row: (row["namespace"], row["name"], row["uid"]))


def positive_integer(value, label):
    require(type(value) is int and value >= 0, label + " must be a nonnegative integer")
    return value


def build_report(node_name, node, pods, summary, captured_at):
    require(isinstance(node, dict) and node.get("kind") == "Node"
            and isinstance(node.get("metadata"), dict)
            and isinstance(node.get("status"), dict),
            "Node response is invalid")
    meta, status = node["metadata"], node["status"]
    require(meta.get("name") == node_name and isinstance(meta.get("uid"), str)
            and bool(meta["uid"]) and isinstance(meta.get("resourceVersion"), str)
            and bool(meta["resourceVersion"]), "Node identity is invalid")
    boot_id = status.get("nodeInfo", {}).get("bootID")
    require(isinstance(boot_id, str) and bool(boot_id), "Node boot ID is invalid")
    capacity, allocatable = status.get("capacity"), status.get("allocatable")
    require(isinstance(capacity, dict) and isinstance(allocatable, dict),
            "Node memory budgets are invalid")
    physical = memory_bytes(capacity.get("memory"))
    pod_budget = memory_bytes(allocatable.get("memory"))
    require(physical > 0 and 0 < pod_budget <= physical, "Node memory budgets disagree")
    require(isinstance(summary, dict) and isinstance(summary.get("node"), dict)
            and summary["node"].get("nodeName") == node_name,
            "kubelet Summary node identity differs")
    memory, fs = summary["node"].get("memory"), summary["node"].get("fs")
    require(isinstance(memory, dict) and isinstance(fs, dict),
            "kubelet Summary metrics are incomplete")
    working = positive_integer(memory.get("workingSetBytes"), "node working set")
    fs_free = positive_integer(fs.get("availableBytes"), "node filesystem available")
    fs_size = positive_integer(fs.get("capacityBytes"), "node filesystem capacity")
    require(fs_size > 0 and fs_free <= fs_size, "node filesystem metrics disagree")
    assigned = complete_pods(pods, node_name)
    scheduled = sum(pod["scheduledRequestBytes"] for pod in assigned)
    conditions = status.get("conditions") or []
    require(isinstance(conditions, list), "Node conditions are invalid")
    ready = any(isinstance(condition, dict) and condition.get("type") == "Ready"
                and condition.get("status") == "True" for condition in conditions)
    return {
        "format": 1, "purpose": "read-only-candidate-observation",
        "admission": "unproven",
        "capturedAt": captured_at,
        "node": {"name": node_name, "uid": meta["uid"], "bootID": boot_id,
                 "resourceVersion": meta["resourceVersion"], "ready": ready,
                 "physicalMemoryBytes": physical, "allocatableMemoryBytes": pod_budget,
                 "workingSetBytes": working,
                 "physicalHeadroomBytes": physical - working,
                 "scheduledPodRequestsBytes": scheduled,
                 "requestHeadroomBytes": pod_budget - scheduled,
                 "filesystemAvailableBytes": fs_free, "filesystemCapacityBytes": fs_size},
        "podListResourceVersion": pods["metadata"]["resourceVersion"],
        "assignedPods": assigned,
        "foreignPods": [pod for pod in assigned if not pod["allowedSystemDaemonSet"]],
    }


def kubectl(*args):
    result = subprocess.run(["kubectl", "--request-timeout=20s", *args],
                            capture_output=True, text=True, timeout=30, check=True)
    require(len(result.stdout) <= MAX_RESPONSE, "Kubernetes response is too large")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, help="existing homelab worker to inspect")
    args = parser.parse_args()
    try:
        require(NODE_NAME.fullmatch(args.node) is not None, "invalid Node name")
        server = kubectl("config", "view", "--minify", "-o",
                         "jsonpath={.clusters[0].cluster.server}").strip()
        require(server == API_SERVER, "authenticated homelab Kubernetes context required")
        node = json.loads(kubectl("get", "node", args.node, "-o", "json"))
        pod_path = "/api/v1/pods?" + urlencode({"fieldSelector": "spec.nodeName=" + args.node,
                                                  "limit": "0"})
        pods = json.loads(kubectl("get", "--raw", pod_path))
        summary = json.loads(kubectl("get", "--raw", "/api/v1/nodes/" + args.node +
                                     "/proxy/stats/summary"))
        captured = datetime.now(timezone.utc).isoformat()
        print(json.dumps(build_report(args.node, node, pods, summary, captured),
                         sort_keys=True, separators=(",", ":")))
        return 0
    except ValueError as error:
        print("Read-only candidate report blocked: " + str(error), file=sys.stderr)
        return 1
    except (TypeError, KeyError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Read-only candidate report blocked; inspect Kubernetes responses",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
