#!/usr/bin/env python3
"""Read-only, fail-closed capacity and native-fleet preflight for Octelium.

A pass is not permission to prune emergency-dataplane.yaml. Direct native Pod-IP
probes, the public end-to-end check, and a reviewed GitOps change remain required.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROLLING_HEADROOM_BYTES = 2765 * 1024 * 1024  # 2.7 GiB observed native-fleet p95.
MIN_NATIVE_TWINS = 25
DECLARED_EMERGENCY_NAMES = re.findall(
    r"^  name: (emergency-[a-z0-9-]+)$",
    (Path(__file__).resolve().parents[1] / "clusters/homelab/apps/octelium-enterprise/emergency-dataplane.yaml").read_text(),
    re.MULTILINE)


def quantity_bytes(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(Ki|Mi|Gi|Ti|[kMGT]|)", value or "")
    if not match:
        raise ValueError(f"unsupported memory quantity: {value!r}")
    unit = match.group(2)
    multiplier = {"": 1, "k": 1000, "M": 1000**2, "G": 1000**3,
                  "T": 1000**4, "Ki": 1024, "Mi": 1024**2,
                  "Gi": 1024**3, "Ti": 1024**4}[unit]
    return int(float(match.group(1)) * multiplier)


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def pod_request_bytes(pod):
    spec = pod["spec"]
    request = lambda c: quantity_bytes(c.get("resources", {}).get("requests", {}).get("memory", "0"))
    sidecars = 0
    startup = 0
    for container in spec.get("initContainers", []):
        if container.get("restartPolicy") == "Always":
            sidecars += request(container)
            startup = max(startup, sidecars)
        else:
            startup = max(startup, sidecars + request(container))
    regular = sum(map(request, spec.get("containers", []))) + sidecars
    pod_level = quantity_bytes(spec.get("resources", {}).get("requests", {}).get("memory", "0"))
    overhead = quantity_bytes(spec.get("overhead", {}).get("memory", "0"))
    return max(regular, startup, pod_level) + overhead


def owner_uid(item, kind):
    owners = [o["uid"] for o in item["metadata"].get("ownerReferences", [])
              if o.get("kind") == kind and o.get("controller")]
    return owners[0] if len(owners) == 1 else None


def evaluate(workloads, nodes, metrics, all_pods, now):
    failures = []
    deployments = [x for x in workloads["items"] if x["kind"] == "Deployment"]
    replicasets = [x for x in workloads["items"] if x["kind"] == "ReplicaSet"]
    pods = [x for x in workloads["items"] if x["kind"] == "Pod"]
    emergency = [x for x in deployments if x["metadata"]["name"].startswith("emergency-")]
    native = [x for x in deployments if x not in emergency]
    if (len(DECLARED_EMERGENCY_NAMES) != MIN_NATIVE_TWINS
            or len(set(DECLARED_EMERGENCY_NAMES)) != MIN_NATIVE_TWINS):
        failures.append("declared emergency Deployment inventory is incomplete or duplicated")
    if {x["metadata"]["name"] for x in emergency} != set(DECLARED_EMERGENCY_NAMES) or len(emergency) != MIN_NATIVE_TWINS:
        failures.append(f"expected {MIN_NATIVE_TWINS} declared emergency Deployments; found {len(emergency)} or drift")
    selected_nodes = set()
    seen_native_uids = set()
    matched = 0
    for fallback in emergency:
        labels = fallback["spec"]["template"]["metadata"].get("labels", {})
        component, service_uid = labels.get("octelium.com/component"), labels.get("octelium.com/svc-uid")
        twins = [d for d in native if
                 d["spec"]["template"]["metadata"].get("labels", {}).get("octelium.com/component") == component
                 and (not service_uid or d["spec"]["template"]["metadata"].get("labels", {}).get("octelium.com/svc-uid") == service_uid)]
        name = fallback["metadata"]["name"]
        if not component or len(twins) != 1:
            failures.append(f"{name}: exact native Deployment missing or ambiguous")
            continue
        twin = twins[0]
        twin_uid = twin["metadata"]["uid"]
        if twin_uid in seen_native_uids:
            failures.append(f"{name}: native Deployment reused by another fallback")
            continue
        seen_native_uids.add(twin_uid)
        status = twin.get("status", {})
        if (twin["spec"].get("replicas", 1) != 1
                or any(status.get(field) != 1 for field in ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas"))
                or status.get("unavailableReplicas", 0) != 0
                or status.get("observedGeneration", 0) < twin["metadata"].get("generation", 1)):
            failures.append(f"{name}: native Deployment not converged to one Ready replica")
            continue
        rs_uids = {r["metadata"]["uid"] for r in replicasets if owner_uid(r, "Deployment") == twin_uid}
        owned = [p for p in pods if owner_uid(p, "ReplicaSet") in rs_uids]
        if len(owned) != 1 or owned[0].get("status", {}).get("phase") != "Running" or owned[0]["metadata"].get("deletionTimestamp"):
            failures.append(f"{name}: expected one non-terminating owned Running native Pod; found {len(owned)}")
            continue
        pod = owned[0]
        conditions = [c for c in pod["status"].get("conditions", []) if c.get("type") == "Ready"]
        containers = pod["status"].get("containerStatuses", [])
        init_containers = pod["status"].get("initContainerStatuses", [])
        if (len(conditions) != 1 or conditions[0].get("status") != "True"
                or not conditions[0].get("lastTransitionTime")
                or now - timestamp(conditions[0]["lastTransitionTime"]) < timedelta(hours=24)
                or len(containers) != len(pod["spec"].get("containers", []))
                or len(init_containers) != len(pod["spec"].get("initContainers", []))
                or any(not c.get("ready") or c.get("restartCount") != 0 for c in containers)
                or any(c.get("restartCount") != 0 for c in init_containers)
                or not pod["status"].get("podIP") or not pod["spec"].get("nodeName")):
            failures.append(f"{name}: native Pod lacks 24h uninterrupted Ready/zero-restart evidence")
            continue
        selected_nodes.add(pod["spec"].get("nodeName"))
        matched += 1
    if len(selected_nodes) != 1:
        failures.append(f"native twins must share one worker; found {sorted(selected_nodes)}")
    else:
        node_name = next(iter(selected_nodes))
        node = next((n for n in nodes["items"] if n["metadata"]["name"] == node_name), None)
        metric = next((m for m in metrics["items"] if m["metadata"]["name"] == node_name), None)
        if not node or not metric:
            failures.append(f"{node_name}: node or fresh metrics unavailable")
        else:
            labels = node["metadata"].get("labels", {})
            conditions = node["status"].get("conditions", [])
            ready = [c for c in conditions if c.get("type") == "Ready"]
            pressure_conditions = {
                kind: [c for c in conditions if c.get("type") == kind]
                for kind in ("MemoryPressure", "DiskPressure", "PIDPressure")}
            pressures_clear = all(
                len(items) == 1 and items[0].get("status") == "False"
                for items in pressure_conditions.values())
            scheduling_blocked = node.get("spec", {}).get("unschedulable") or any(
                t.get("effect") in ("NoSchedule", "NoExecute") for t in node.get("spec", {}).get("taints", []))
            if (node_name == "acer" or "octelium.com/node-mode-dataplane" not in labels
                    or scheduling_blocked or not pressures_clear
                    or len(ready) != 1 or ready[0].get("status") != "True"):
                failures.append(f"{node_name}: not a Ready native dataplane worker")
            elif (not ready[0].get("lastTransitionTime")
                  or now - timestamp(ready[0]["lastTransitionTime"]) < timedelta(hours=24)):
                failures.append(f"{node_name}: native worker has not remained Ready for 24h")
            if not metric.get("timestamp") or abs(now - timestamp(metric["timestamp"])) > timedelta(minutes=5):
                failures.append(f"{node_name}: node memory metrics older than five minutes")
            allocatable = quantity_bytes(node["status"]["allocatable"]["memory"])
            used = quantity_bytes(metric["usage"]["memory"])
            requested = sum(pod_request_bytes(p) for p in all_pods["items"]
                            if p["spec"].get("nodeName") == node_name
                            and p.get("status", {}).get("phase") not in ("Succeeded", "Failed"))
            if allocatable - used < ROLLING_HEADROOM_BYTES:
                failures.append(f"{node_name}: observed memory margin {(allocatable-used)//1048576}Mi < 2765Mi")
            if allocatable - requested < ROLLING_HEADROOM_BYTES:
                failures.append(f"{node_name}: request margin {(allocatable-requested)//1048576}Mi < 2765Mi")
    return matched, failures


def kubectl_json(*args):
    return json.loads(subprocess.check_output(["kubectl", *args], text=True, timeout=30))


def main():
    try:
        now = datetime.now(timezone.utc)
        workloads = kubectl_json("-n", "octelium", "get", "deploy,rs,pods", "-o", "json")
        nodes = kubectl_json("get", "nodes", "-o", "json")
        metrics = kubectl_json("get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes")
        all_pods = kubectl_json("get", "pods", "-A", "-o", "json")
        matched, failures = evaluate(workloads, nodes, metrics, all_pods, now)
    except (KeyError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"BLOCK: incomplete or invalid live evidence: {exc}", file=sys.stderr)
        return 1
    print(f"Native twins with 24h uninterrupted Ready evidence: {matched}/{MIN_NATIVE_TWINS}")
    for failure in failures:
        print(f"BLOCK: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("PREFLIGHT PASS: direct native Pod-IP probes and scripts/octelium-e2e-check.sh remain required before a reviewed emergency-dataplane removal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
