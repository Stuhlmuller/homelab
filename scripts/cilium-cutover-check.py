#!/usr/bin/env python3
"""Check primary-CNI migration coverage in private Kubernetes JSON snapshots."""

import argparse
import ipaddress
import json
from pathlib import Path


def items(path, kind):
    objects = json.loads(path.read_text())["items"]
    if not objects or any(obj.get("kind") != kind for obj in objects):
        raise ValueError(f"{path} must be a nonempty Kubernetes list of {kind} objects")
    return objects


def verify(pods, endpoints, cidr):
    by_name = {}
    for endpoint in endpoints:
        meta = endpoint["metadata"]
        key = meta["namespace"], meta["name"]
        if key in by_name:
            raise ValueError(f"Duplicate CiliumEndpoint {key}")
        by_name[key] = endpoint

    checked = 0
    failures = []
    for pod in pods:
        spec, status, meta = pod["spec"], pod.get("status", {}), pod["metadata"]
        if spec.get("hostNetwork") or status.get("phase") in {"Succeeded", "Failed"}:
            continue
        checked += 1
        key = meta["namespace"], meta["name"]
        endpoint = by_name.get(key, {})
        ownership = endpoint.get("metadata", {}).get("ownerReferences", [])
        primary = status.get("podIP")
        if not primary or ipaddress.ip_address(primary) not in cidr:
            failures.append(f"{'/'.join(key)}: primary IP outside the Cilium pool or missing")
        elif not any(ref.get("kind") == "Pod" and ref.get("uid") == meta["uid"] for ref in ownership):
            failures.append(f"{'/'.join(key)}: missing CiliumEndpoint for current Pod UID")
        else:
            state = endpoint.get("status", {})
            addressing = state.get("networking", {}).get("addressing", [])
            endpoint_ips = {pair.get(f"ipv{cidr.version}") for pair in addressing}
            if state.get("state") != "ready" or primary not in endpoint_ips:
                failures.append(f"{'/'.join(key)}: CiliumEndpoint is unready or has a different IP")

    if not checked:
        raise ValueError("No active non-host-network Pods to verify")
    return checked, failures


def worker_pods(pods, nodes, worker, previous_boot_id):
    matches = [node for node in nodes if node["metadata"]["name"] == worker]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one node named {worker}")
    node = matches[0]
    status = node["status"]
    boot_id = status["nodeInfo"]["bootID"]
    if not boot_id or boot_id == previous_boot_id:
        raise ValueError(f"{worker} has not reported a new boot")
    if node["spec"].get("unschedulable") is not True:
        raise ValueError(f"{worker} must still be cordoned during cutover verification")
    if not any(condition["type"] == "Ready" and condition["status"] == "True"
               for condition in status["conditions"]):
        raise ValueError(f"{worker} is not Ready")
    return [pod for pod in pods if pod["spec"].get("nodeName") == worker]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pods", required=True, type=Path)
    parser.add_argument("--endpoints", required=True, type=Path)
    parser.add_argument("--cidr", required=True, type=ipaddress.ip_network)
    parser.add_argument("--worker", choices=("zimaboard-2",))
    parser.add_argument("--nodes", type=Path)
    parser.add_argument("--previous-boot-id")
    args = parser.parse_args()
    if any((args.worker, args.nodes, args.previous_boot_id)) and not all(
        (args.worker, args.nodes, args.previous_boot_id)
    ):
        parser.error("--worker, --nodes and --previous-boot-id must be supplied together")
    try:
        pods = items(args.pods, "Pod")
        if args.worker:
            pods = worker_pods(pods, items(args.nodes, "Node"), args.worker, args.previous_boot_id)
        count, failures = verify(pods, items(args.endpoints, "CiliumEndpoint"), args.cidr)
    except (OSError, KeyError, ValueError) as error:
        raise SystemExit(f"Cilium cutover check failed: {error}") from None
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Verified primary Cilium endpoint ownership and IPs for {count} active Pods")


if __name__ == "__main__":
    main()
