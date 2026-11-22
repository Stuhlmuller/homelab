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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pods", required=True, type=Path)
    parser.add_argument("--endpoints", required=True, type=Path)
    parser.add_argument("--cidr", required=True, type=ipaddress.ip_network)
    args = parser.parse_args()
    try:
        count, failures = verify(items(args.pods, "Pod"),
                                 items(args.endpoints, "CiliumEndpoint"), args.cidr)
    except (OSError, KeyError, ValueError) as error:
        raise SystemExit(f"Cilium cutover check failed: {error}") from None
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Verified primary Cilium endpoint ownership and IPs for {count} active Pods")


if __name__ == "__main__":
    main()
