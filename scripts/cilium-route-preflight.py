#!/usr/bin/env python3
"""Reject overlaps between the proposed Cilium pool and existing routes."""

import argparse
import ipaddress
import json
from pathlib import Path


def read_list(path, kind):
    data = json.loads(path.read_text())
    entries = data["items"]
    if not entries or any(entry.get("kind") != kind for entry in entries):
        raise ValueError(f"Expected a nonempty {kind} list from {path}")
    return entries


def check(pool, nodes, services, routes):
    node_names = {node["metadata"]["name"] for node in nodes}
    if node_names != set(routes):
        raise ValueError("Route snapshots must cover exactly the nodes in the Kubernetes inventory")
    prefixes = []
    for node in nodes:
        name = node["metadata"]["name"]
        pod_cidrs = node["spec"]["podCIDRs"]
        if not pod_cidrs:
            raise ValueError(f"{name} has no recorded Pod CIDRs")
        prefixes.extend((f"{name} Pod CIDR", prefix) for prefix in pod_cidrs)
        host = [ipaddress.ip_network(value, strict=False) for value in routes[name]]
        specific = [route for route in host if route.prefixlen and route.version == pool.version]
        if not specific:
            raise ValueError(f"{name} has no nondefault routes in the proposed address family")
        prefixes.extend((f"{name} host route", route) for route in specific)
    for service in services:
        prefixes.extend((f'{service["metadata"]["name"]} Service CIDR', prefix)
                        for prefix in service["spec"]["cidrs"])
    if not any(source.endswith("Service CIDR") for source, _ in prefixes):
        raise ValueError("The Service CIDR inventory is empty")
    return [(source, str(network)) for source, prefix in prefixes
            if pool.overlaps(network := ipaddress.ip_network(prefix))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", required=True, type=ipaddress.ip_network)
    parser.add_argument("--nodes", required=True, type=Path)
    parser.add_argument("--service-cidrs", required=True, type=Path)
    parser.add_argument("--node-routes", action="append", required=True, metavar="NODE=FILE",
                        help="one file per node containing one Talos route prefix per line")
    args = parser.parse_args()
    try:
        routes = {}
        for item in args.node_routes:
            name, path = item.split("=", 1)
            if name in routes:
                raise ValueError(f"Duplicate route snapshot for {name}")
            routes[name] = Path(path).read_text().split()
        conflicts = check(args.pool, read_list(args.nodes, "Node"),
                          read_list(args.service_cidrs, "ServiceCIDR"), routes)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"Cilium route preflight failed: {error}") from None
    if conflicts:
        raise SystemExit("\n".join(f"{args.pool} overlaps {source}: {prefix}" for source, prefix in conflicts))
    print(f"No overlap with the Kubernetes CIDRs or {len(routes)} host route snapshots")


if __name__ == "__main__":
    main()
