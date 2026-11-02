#!/usr/bin/env python3
"""Read-only activation evidence for one bounded Descheduler eviction."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CAPACITY = runpy.run_path(str(ROOT / "scripts/network-policy-candidate-report.py"))
POLICY = runpy.run_path(str(Path(__file__).with_name("descheduler-policy-check.py")))
NODES = {"acer", "zimaboard-0", "zimaboard-1", "zimaboard-2"}


def require(value, category):
    if not value:
        raise ValueError(category)


def runtime_changed(paths):
    return any(not path.endswith(".md") and (
        path.startswith("clusters/homelab/apps/descheduler/") or
        path.startswith("IaC/") and "/descheduler/" in path or path in {
            "scripts/ci/descheduler-release-check.py", "scripts/ci/descheduler-release-check-test.py",
            "scripts/ci/descheduler-policy-check.py", "scripts/ci/descheduler-cadence-check.sh",
            "scripts/network-policy-candidate-report.py", ".github/workflows/terragrunt-plan.yml",
        }) for path in paths)


def fresh(value, now, seconds):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(stamp.tzinfo is not None and 0 <= (now - stamp).total_seconds() <= seconds, "stale_evidence")
    return stamp


def items(document, kind):
    require(document.get("kind") == kind + "List" and isinstance(document.get("items"), list)
            and isinstance(document.get("metadata", {}).get("resourceVersion"), str)
            and bool(document["metadata"]["resourceVersion"])
            and not document["metadata"].get("continue"), "incomplete_inventory")
    rows = document["items"]
    identities = [row["metadata"]["uid"] for row in rows]
    require(all(isinstance(uid, str) and uid for uid in identities)
            and len(set(identities)) == len(identities), "invalid_inventory_identity")
    return rows


def active(obj):
    return not any(item.get("type") in {"Complete", "Failed"} and item.get("status") == "True"
                   for item in obj.get("status", {}).get("conditions", []))


def owned(obj, owner, kind):
    return obj["metadata"].get("namespace") == owner["metadata"].get("namespace") and any(
        ref.get("controller") is True and ref.get("kind") == kind
        and ref.get("uid") == owner["metadata"]["uid"] for ref in obj["metadata"].get("ownerReferences", []))


def eligible(spec, node):
    if not all(node["metadata"]["labels"].get(key) == value
               for key, value in spec.get("nodeSelector", {}).items()):
        return False
    tolerations = spec.get("tolerations", [])
    for item in tolerations:
        require(item.get("operator", "Equal") in {"Equal", "Exists"}
                and item.get("effect", "") in {"", "NoSchedule", "NoExecute", "PreferNoSchedule"}
                and all(isinstance(item.get(key, ""), str) for key in ("key", "value")), "invalid_toleration")
    for taint in node.get("spec", {}).get("taints", []):
        require(taint["effect"] in {"NoSchedule", "NoExecute", "PreferNoSchedule"}, "invalid_taint")
        if taint["effect"] == "PreferNoSchedule":
            continue
        if not any(item.get("effect", "") in {"", taint["effect"]}
                   and (item.get("operator", "Equal") == "Exists"
                        and item.get("key", "") in {"", taint["key"]}
                        or item.get("operator", "Equal") == "Equal"
                        and item.get("key", "") == taint["key"]
                        and item.get("value", "") == taint.get("value", "")) for item in tolerations):
            return False
    return True


def demand(pod):
    spec = pod["spec"]
    require(spec.get("schedulerName", "default-scheduler") == "default-scheduler"
            and not any(spec.get(key) for key in ("affinity", "topologySpreadConstraints", "schedulingGates",
                                                  "resources", "ephemeralContainers", "hostNetwork")),
            "unsupported_placement_or_resources")
    request = CAPACITY["pod_memory_request"](pod)
    limit = CAPACITY["memory_bytes"](spec.get("overhead", {}).get("memory", "0"))
    # Sum every init phase too: over-reserving is safer than a second resource scheduler.
    for container in [*spec["containers"], *spec.get("initContainers", [])]:
        require(not any(port.get("hostPort") for port in container.get("ports", [])), "unsupported_host_port")
        resources = container.get("resources", {})
        bound = CAPACITY["memory_bytes"](resources.get("limits", {}).get("memory", "0"))
        require(bound > 0 and bound >= CAPACITY["resource_memory"](container), "unbounded_memory_demand")
        for status in [*pod.get("status", {}).get("containerStatuses", []),
                       *pod.get("status", {}).get("initContainerStatuses", [])]:
            current = status.get("resources", {}).get("limits", {}).get("memory")
            if status["name"] == container["name"] and current is not None:
                require(CAPACITY["memory_bytes"](current) == bound, "in_place_limit_changed")
        limit += bound
    require(limit >= request, "unbounded_memory_demand")
    return request, limit


def candidate(pod, owner_counts):
    meta, spec = pod["metadata"], pod["spec"]
    annotations = meta.get("annotations", {})
    if "descheduler.alpha.kubernetes.io/evict" in annotations:
        raise ValueError("forced_eviction_bypasses_guards")
    owners = meta.get("ownerReferences", [])
    if ("kubernetes.io/config.mirror" in annotations or not owners
            or any(ref.get("kind") == "DaemonSet" for ref in owners)
            or spec.get("priority", 0) >= 2000000000
            or any(any(key in volume for key in ("persistentVolumeClaim", "hostPath", "emptyDir"))
                   for volume in spec.get("volumes", []))):
        return False
    # Native minReplicas counts cached Pods by owner UID, including terminal Pods.
    return len(owners) != 1 or owner_counts[owners[0]["uid"]] >= 2


def check_nodes(nodes, leases, now):
    require({node["metadata"]["name"] for node in nodes} == NODES and len(nodes) == len(NODES),
            "unexpected_nodes")
    for node in nodes:
        name = node["metadata"]["name"]
        require(not node.get("spec", {}).get("unschedulable"), "unschedulable_node")
        conditions = node["status"]["conditions"]
        for kind, expected in (("Ready", "True"), ("MemoryPressure", "False"),
                               ("DiskPressure", "False"), ("PIDPressure", "False")):
            require([row.get("status") for row in conditions if row.get("type") == kind] == [expected],
                    "unhealthy_node")
        fresh(next(row["lastHeartbeatTime"] for row in conditions if row["type"] == "Ready"), now, 360)
        lease = [row for row in leases if row["metadata"]["name"] == name]
        require(len(lease) == 1 and lease[0]["spec"]["holderIdentity"] == name
                and any(ref.get("kind") == "Node" and ref.get("uid") == node["metadata"]["uid"]
                        for ref in lease[0]["metadata"].get("ownerReferences", [])), "invalid_node_lease")
        fresh(lease[0]["spec"]["renewTime"], now, 90)


def check(nodes, leases, pods, crons, jobs, summaries, now):
    check_nodes(nodes, leases, now)
    live = [pod for pod in pods if pod["status"]["phase"] not in {"Succeeded", "Failed"}]
    require(all(pod["status"]["phase"] == "Running" and pod["spec"].get("nodeName") in NODES
                and not pod["metadata"].get("deletionTimestamp")
                and any(row.get("type") == "Ready" and row.get("status") == "True"
                        for row in pod["status"].get("conditions", [])) for pod in live), "unsettled_placement")
    owners = Counter(ref["uid"] for pod in pods for ref in pod["metadata"].get("ownerReferences", []))
    candidates = [(pod, demand(pod)) for pod in live if candidate(pod, owners)]
    classified = set()
    for node in nodes:
        name = node["metadata"]["name"]
        summary = summaries[name]
        require(summary["node"]["nodeName"] == name, "wrong_summary_node")
        memory = summary["node"]["memory"]
        node_time = fresh(memory["time"], now, 120)
        require(type(memory.get("availableBytes")) is int and 0 <= memory["availableBytes"] <= CAPACITY["memory_bytes"](node["status"]["capacity"]["memory"]),
                "invalid_available_memory")
        bound = [pod for pod in live if pod["spec"]["nodeName"] == name]

        def measured(pod):
            matches = [row for row in summary["pods"] if row.get("podRef") == {
                "name": pod["metadata"]["name"], "namespace": pod["metadata"]["namespace"],
                "uid": pod["metadata"]["uid"]}]
            require(len(matches) == 1, "missing_pod_measurement")
            value = matches[0]["memory"]
            stamp = fresh(value["time"], now, 120)
            require(abs((node_time - stamp).total_seconds()) <= 30
                    and type(value.get("workingSetBytes")) is int and value["workingSetBytes"] >= 0,
                    "invalid_pod_measurement")
            return value["workingSetBytes"]

        for pod, (_, limit) in candidates:
            if pod["spec"]["nodeName"] == name:
                require(measured(pod) <= limit, "candidate_exceeds_bound")
        reserved_request = reserved_limit = 0
        for cron in crons:
            require(type(cron["spec"].get("suspend", False)) is bool, "invalid_cron_suspend")
            current = [job for job in jobs if active(job) and owned(job, cron, "CronJob")]
            classified.update(job["metadata"]["uid"] for job in current)
            templates = [job["spec"] for job in current]
            if not cron["spec"].get("suspend", False):
                templates.append(cron["spec"]["jobTemplate"]["spec"])
            require(all(not template["template"]["spec"].get("nodeName") for template in templates),
                    "unsupported_job_placement")
            templates = [template for template in templates if eligible(template["template"]["spec"], node)]
            present = [pod for pod in bound if any(owned(pod, job, "Job") for job in current)]
            if not templates and not present:
                continue
            require(cron["spec"].get("concurrencyPolicy") == "Forbid" and len(current) <= 1,
                    "unbounded_recurring_overlap")
            demands = []
            for template in templates:
                require(type(template.get("parallelism", 1)) is int and template.get("parallelism", 1) == 1
                        and type(template.get("completions", 1)) is int and template.get("completions", 1) == 1
                        and template.get("completionMode", "NonIndexed") == "NonIndexed", "unsupported_job_placement")
                demands.append(demand(template["template"]))
            require(len(present) <= 1, "overlapping_job_pods")
            demands.extend(demand(pod) for pod in present)
            used = sum(measured(pod) for pod in present)
            maximum = max(limit for _, limit in demands)
            require(used <= maximum, "job_exceeds_bound")
            reserved_request += max(0, max(request for request, _ in demands)
                                    - sum(CAPACITY["pod_memory_request"](pod) for pod in present))
            reserved_limit += maximum - used
        moving = [size for pod, size in candidates if pod["spec"]["nodeName"] != name and eligible(pod["spec"], node)]
        wanted_request = max((request for request, _ in moving), default=0) + reserved_request
        wanted_limit = max((limit for _, limit in moving), default=0) + reserved_limit
        available = CAPACITY["memory_bytes"](node["status"]["allocatable"]["memory"])
        require(available >= sum(CAPACITY["pod_memory_request"](pod) for pod in bound) + wanted_request,
                "insufficient_request_headroom")
        require(memory["availableBytes"] >= wanted_limit, "insufficient_physical_headroom")
    require(all(not active(job) or job["metadata"]["uid"] in classified for job in jobs), "unclassified_job")


def read_json(*args):
    result = subprocess.run(["kubectl", "--request-timeout=15s", *args], capture_output=True,
                            text=True, timeout=25, check=True)
    require(len(result.stdout) <= 16 * 1024 * 1024, "response_too_large")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    args = parser.parse_args()
    try:
        paths = subprocess.run(["git", "diff", "--name-only", "-z", f"{args.base_ref}...HEAD"],
                               capture_output=True, text=True, timeout=15, check=True).stdout.split("\0")
        if not runtime_changed(paths):
            print("Descheduler runtime unchanged; activation check not applicable.")
            return 0
        values = json.loads(subprocess.run(["yq", "-o=json", ".",
                            str(ROOT / "clusters/homelab/apps/descheduler/values.yaml")],
                            capture_output=True, text=True, timeout=15, check=True).stdout)
        POLICY["check"]({"apiVersion": "descheduler/v1alpha2", "kind": "DeschedulerPolicy",
                         **values["deschedulerPolicy"]})
        require(values["kind"] == "Deployment" and values["deschedulingInterval"] == "30m", "policy_changed")
        started = time.monotonic()
        nodes = items(read_json("get", "--raw", "/api/v1/nodes?limit=0"), "Node")
        leases = items(read_json("get", "--raw", "/apis/coordination.k8s.io/v1/namespaces/kube-node-lease/leases?limit=0"), "Lease")
        check_nodes(nodes, leases, datetime.now(timezone.utc))
        pods = items(read_json("get", "--raw", "/api/v1/pods?limit=0"), "Pod")
        crons = items(read_json("get", "--raw", "/apis/batch/v1/cronjobs?limit=0"), "CronJob")
        jobs = items(read_json("get", "--raw", "/apis/batch/v1/jobs?limit=0"), "Job")
        summaries = {name: read_json("get", "--raw", f"/api/v1/nodes/{name}/proxy/stats/summary") for name in sorted(NODES)}
        after = items(read_json("get", "--raw", "/api/v1/nodes?limit=0"), "Node")
        def identities(rows):
            return sorted((row["metadata"]["name"], row["metadata"]["uid"],
                           row["status"]["nodeInfo"]["bootID"]) for row in rows)
        require(identities(nodes) == identities(after) and time.monotonic() - started <= 60, "inventory_changed")
        check(after, leases, pods, crons, jobs, summaries, datetime.now(timezone.utc))
        print("Descheduler one-eviction activation evidence passed; N-1 capacity remains unproven.")
        return 0
    except (AssertionError, OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError,
            AttributeError, IndexError, ArithmeticError):
        print("::error::Descheduler readiness or bounded capacity is unverified; private diagnostics withheld.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
