#!/usr/bin/env python3
"""Read-only two-Pod LiteLLM rollout capacity check for the protected PR pipeline."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CAPACITY = runpy.run_path(str(ROOT / "scripts/network-policy-candidate-report.py"))
GIB = 1024 ** 3


def require(value, category):
    if not value:
        raise ValueError(category)


def runtime_changed(paths):
    return any(not path.endswith(".md") and (
        path.startswith("clusters/homelab/apps/litellm/") or
        path.startswith("IaC/") and "/litellm/" in path or
        path in {"scripts/ci/litellm-release-check.py", "scripts/ci/litellm-release-check-test.py",
                 "scripts/ci/litellm-runtime-hardening-check.py", "scripts/network-policy-candidate-report.py",
                 ".github/workflows/terragrunt-plan.yml"}) for path in paths)


def fresh(value, now, seconds):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(stamp.tzinfo is not None and 0 <= (now - stamp).total_seconds() <= seconds,
            "evidence_stale")


def items(document, kind):
    require(document.get("kind") == kind + "List" and not document.get("metadata", {}).get("continue")
            and bool(document.get("metadata", {}).get("resourceVersion"))
            and isinstance(document.get("items"), list), "inventory_incomplete")
    values = document["items"]
    identities = [item["metadata"]["uid"] for item in values]
    require(all(isinstance(uid, str) and uid for uid in identities)
            and len(set(identities)) == len(identities), "inventory_identity_invalid")
    return values


def owned(obj, uid, kind):
    return any(ref.get("controller") is True and ref.get("kind") == kind and ref.get("uid") == uid
               for ref in obj["metadata"].get("ownerReferences", []))


def pod_request(pod):
    spec = pod["spec"]
    require(isinstance(spec, dict) and spec.get("schedulerName", "default-scheduler") == "default-scheduler",
            "pod_scheduling_unsupported")
    for obj in [spec, *spec.get("containers", []), *spec.get("initContainers", [])]:
        resources = obj.get("resources", {})
        require(isinstance(resources, dict), "resource_schema_invalid")
        require(all(isinstance(resources.get(key, {}), dict) for key in ("requests", "limits")),
                "resource_schema_invalid")
    require(isinstance(spec.get("overhead", {}), dict), "resource_schema_invalid")
    return CAPACITY["pod_memory_request"](pod)


def eligible(spec, node):
    return spec.get("nodeName") in (None, "", "acer") and all(
        node["metadata"]["labels"].get(key) == value for key, value in spec.get("nodeSelector", {}).items())


def active_job(job):
    return not any(item.get("type") in {"Complete", "Failed"} and item.get("status") == "True"
                   for item in job.get("status", {}).get("conditions", []))


def recurring_reservation(crons, jobs, bound, node):
    reserve = 0
    classified = set()
    for cron in crons:
        require(type(cron["spec"].get("suspend", False)) is bool, "recurring_contract_invalid")
        namespace = cron["metadata"]["namespace"]
        owned_jobs = [job for job in jobs if job["metadata"]["namespace"] == namespace
                      and owned(job, cron["metadata"]["uid"], "CronJob") and active_job(job)]
        classified.update(job["metadata"]["uid"] for job in owned_jobs)
        candidates = [job["spec"] for job in owned_jobs]
        if not cron["spec"].get("suspend", False):
            candidates.append(cron["spec"]["jobTemplate"]["spec"])
        candidates = [candidate for candidate in candidates if eligible(candidate["template"]["spec"], node)]
        if not candidates:
            continue
        # Old active Job templates still own future demand after the CronJob changes.
        require(cron["spec"].get("concurrencyPolicy") == "Forbid" and len(owned_jobs) <= 1,
                "recurring_overlap_unsupported")
        demands = []
        for candidate in candidates:
            require(type(candidate.get("parallelism", 1)) is int and candidate.get("parallelism", 1) == 1
                    and type(candidate.get("completions", 1)) is int and candidate.get("completions", 1) == 1
                    and candidate.get("completionMode", "NonIndexed") == "NonIndexed",
                    "recurring_parallelism_unsupported")
            wanted = pod_request(candidate["template"])
            require(wanted > 0, "recurring_request_missing")
            demands.append(wanted)
        # Ignoring affinity/taints/windows over-reserves; it cannot invent non-overlap.
        present = sum(pod_request(pod) for pod in bound if pod["metadata"]["namespace"] == namespace
                      and not pod["metadata"].get("deletionTimestamp")
                      and any(owned(pod, job["metadata"]["uid"], "Job") for job in owned_jobs))
        reserve += max(0, max(demands) - present)
    require(not any(active_job(job) and job["metadata"]["uid"] not in classified
                    and eligible(job["spec"]["template"]["spec"], node) for job in jobs),
            "unclassified_active_job")
    return reserve


def check(node, lease, pods, crons, jobs, deployment, sets, summary, values, now):
    require(values.get("nodeSelector") == {"kubernetes.io/hostname": "acer"}
            and values.get("resources") == {"requests": {"memory": "1Gi"}}
            and not values.get("affinity") and not values.get("tolerations")
            and values.get("schedulerName", "default-scheduler") == "default-scheduler",
            "candidate_contract_changed")
    require(node["metadata"]["name"] == "acer" and not node.get("spec", {}).get("unschedulable")
            and not any(taint.get("effect") in {"NoSchedule", "NoExecute"}
                        for taint in node.get("spec", {}).get("taints", [])), "target_unschedulable")
    conditions = node["status"].get("conditions", [])
    for name, expected in (("Ready", "True"), ("MemoryPressure", "False"),
                           ("DiskPressure", "False"), ("PIDPressure", "False")):
        require([item.get("status") for item in conditions if item.get("type") == name] == [expected],
                "target_unhealthy")
    fresh(next(item["lastHeartbeatTime"] for item in conditions if item.get("type") == "Ready"), now, 360)
    require(lease["metadata"]["name"] == "acer" and lease["spec"]["holderIdentity"] == "acer",
            "target_identity_changed")
    fresh(lease["spec"]["renewTime"], now, 90)
    require(deployment["metadata"]["name"] == "litellm" and deployment["metadata"]["namespace"] == "ai"
            and deployment["spec"].get("replicas", 1) == 1
            and deployment["status"].get("observedGeneration") == deployment["metadata"]["generation"],
            "gateway_baseline_unverified")
    strategy = deployment["spec"].get("strategy", {})
    rolling = strategy.get("rollingUpdate", {})
    require(strategy.get("type", "RollingUpdate") == "RollingUpdate"
            and rolling.get("maxSurge", "25%") in (1, "25%")
            and rolling.get("maxUnavailable", "25%") in (0, "25%"), "gateway_strategy_changed")
    owned_sets = [item for item in sets if item["metadata"]["namespace"] == "ai"
                  and owned(item, deployment["metadata"]["uid"], "Deployment")]
    current = [item for item in owned_sets if item["spec"].get("replicas") == 1
               and item["spec"]["template"]["spec"] == deployment["spec"]["template"]["spec"]]
    require(len(current) == 1, "gateway_baseline_unverified")
    require(not any(not pod["spec"].get("nodeName")
                    and pod["status"]["phase"] not in {"Succeeded", "Failed"}
                    and all(node["metadata"]["labels"].get(key) == value
                            for key, value in pod["spec"].get("nodeSelector", {}).items())
                    for pod in pods), "pending_placement_unverified")
    bound = [pod for pod in pods if pod["spec"].get("nodeName") == "acer"
             and pod["status"]["phase"] not in {"Succeeded", "Failed"}]
    gateway = [pod for pod in bound if pod["metadata"]["namespace"] == "ai"
               and any(owned(pod, item["metadata"]["uid"], "ReplicaSet") for item in owned_sets)]
    require(len(gateway) == 1 and not gateway[0]["metadata"].get("deletionTimestamp")
            and owned(gateway[0], current[0]["metadata"]["uid"], "ReplicaSet")
            and any(item.get("type") == "Ready" and item.get("status") == "True"
                    for item in gateway[0]["status"].get("conditions", [])), "gateway_baseline_unverified")
    # Account for the serving Pod before replacing its reservation with two complete Pods.
    require(pod_request(gateway[0]) <= GIB, "gateway_request_contract_changed")
    other = [pod for pod in bound if pod is not gateway[0]]
    recurring = recurring_reservation(crons, jobs, other, node)
    available = CAPACITY["memory_bytes"](node["status"]["allocatable"]["memory"])
    available -= sum(pod_request(pod) for pod in other) + recurring
    require(available >= 2 * GIB, "two_pod_reservation_insufficient")
    require(summary["node"]["nodeName"] == "acer", "metrics_identity_changed")
    memory = summary["node"]["memory"]
    fresh(memory["time"], now, 120)
    measured = [item for item in summary["pods"] if item.get("podRef") == {
        "uid": gateway[0]["metadata"]["uid"], "namespace": "ai", "name": gateway[0]["metadata"]["name"]}]
    require(len(measured) == 1, "gateway_metrics_identity_unverified")
    gateway_memory = measured[0]["memory"]
    fresh(gateway_memory["time"], now, 120)
    node_time = datetime.fromisoformat(memory["time"].replace("Z", "+00:00"))
    pod_time = datetime.fromisoformat(gateway_memory["time"].replace("Z", "+00:00"))
    require(abs((node_time - pod_time).total_seconds()) <= 30, "metrics_collection_skew")
    working = gateway_memory.get("workingSetBytes")
    require(type(working) is int and 0 <= working <= GIB, "gateway_usage_exceeds_reservation")
    # The serving gateway already consumes node memory; credit only its exact fresh Pod measurement.
    require(type(memory.get("availableBytes")) is int and memory["availableBytes"] >= 2 * GIB - working + recurring,
            "actual_memory_margin_insufficient")


def read_json(*args):
    result = subprocess.run(["kubectl", "--request-timeout=15s", *args], capture_output=True,
                            text=True, timeout=25, check=True)
    require(len(result.stdout) <= 16 * 1024 * 1024, "inventory_too_large")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    args = parser.parse_args()
    try:
        paths = subprocess.run(["git", "diff", "--name-only", "-z", f"{args.base_ref}...HEAD"],
                               capture_output=True, text=True, timeout=15, check=True).stdout.split("\0")
        if not runtime_changed(paths):
            print("LiteLLM runtime unchanged; capacity check not applicable.")
            return 0
        started = time.monotonic()
        node = read_json("get", "node", "acer", "-o", "json")
        lease = read_json("-n", "kube-node-lease", "get", "lease", "acer", "-o", "json")
        pods = items(read_json("get", "pods", "-A", "--chunk-size=0", "-o", "json"), "Pod")
        crons = items(read_json("get", "cronjobs", "-A", "--chunk-size=0", "-o", "json"), "CronJob")
        jobs = items(read_json("get", "jobs", "-A", "--chunk-size=0", "-o", "json"), "Job")
        deployment = read_json("-n", "ai", "get", "deployment", "litellm", "-o", "json")
        sets = items(read_json("-n", "ai", "get", "replicasets", "--chunk-size=0", "-o", "json"), "ReplicaSet")
        summary = read_json("get", "--raw", "/api/v1/nodes/acer/proxy/stats/summary")
        values = json.loads(subprocess.run(["yq", "-o=json", ".", str(ROOT / "clusters/homelab/apps/litellm/values.yaml")],
                                          capture_output=True, text=True, timeout=15, check=True).stdout)
        require(time.monotonic() - started <= 120, "collection_stale")
        check(node, lease, pods, crons, jobs, deployment, sets, summary, values, datetime.now(timezone.utc))
        print("LiteLLM two-Pod rollout capacity check passed; failure-domain capacity remains unproven.")
        return 0
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, IndexError, AttributeError, ArithmeticError):
        print("::error::LiteLLM rollout capacity is insufficient or unverified; private diagnostics withheld.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
