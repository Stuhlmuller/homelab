#!/usr/bin/env python3
"""Flag broad destinations in Cilium egress policies from JSON snapshots."""

import argparse
import ipaddress
import json
from pathlib import Path


KINDS = {"CiliumNetworkPolicy", "CiliumClusterwideNetworkPolicy"}
PEERS = {"toEndpoints", "toEntities", "toCIDR", "toCIDRSet", "toFQDNs",
         "toServices", "toNodes", "toGroups"}
BROAD_ENTITIES = {"all", "world", "world-ipv4", "world-ipv6", "cluster", "unmanaged"}


def findings(rule):
    if not any(rule.get(peer) for peer in PEERS):
        yield "rule has no explicit destination"
    for entity in sorted(set(rule.get("toEntities", [])) & BROAD_ENTITIES):
        yield f"broad destination entity {entity}"
    for field in ("toEndpoints", "toNodes"):
        for selector in rule.get(field, []):
            if not selector.get("matchLabels") and not any(
                expression.get("operator") in {"In", "Exists"}
                for expression in selector.get("matchExpressions", [])
            ):
                yield f"{field} contains an empty or negative-only selector"
    for prefix in [*rule.get("toCIDR", []),
                   *(entry["cidr"] for entry in rule.get("toCIDRSet", []) if entry.get("cidr"))]:
        if ipaddress.ip_network(prefix, strict=False).prefixlen == 0:
            yield f"default-route destination {prefix}"
    for name in rule.get("toFQDNs", []):
        pattern = name.get("matchPattern", "")
        if pattern and not pattern.strip("*."):
            yield f"unbounded FQDN pattern {pattern}"
    for destination in rule.get("toServices", []):
        service = destination.get("k8sService")
        if not service or not service.get("serviceName") or not service.get("namespace"):
            yield "service destination lacks an exact namespace and name"
    if rule.get("toGroups") or any(
        not entry.get("cidr") for entry in rule.get("toCIDRSet", [])
    ):
        yield "destination group requires expansion and review"


def audit(policies):
    if not policies:
        raise ValueError("Provide at least one Cilium policy to audit")
    for item in policies:
        if item.get("kind") not in KINDS:
            raise ValueError("Expected CiliumNetworkPolicy or CiliumClusterwideNetworkPolicy")
        metadata = item["metadata"]
        name = "/".join(filter(None, (metadata.get("namespace"), metadata["name"])))
        specs = [item["spec"]] if item.get("spec") else []
        specs.extend(item.get("specs", []))
        for index, spec in enumerate(specs):
            for ordinal, rule in enumerate(spec.get("egress", [])):
                for finding in findings(rule):
                    yield f"{name} spec {index + 1} egress rule {ordinal + 1}: {finding}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", nargs="+", type=Path, help="Kubernetes JSON object or list")
    args = parser.parse_args()
    try:
        policies = []
        for path in args.policy:
            snapshot = json.loads(path.read_text())
            policies.extend(snapshot.get("items", [snapshot]))
        problems = list(audit(policies))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"Cilium audit failed: {error}") from None
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"No broad Cilium egress destinations found in {len(policies)} policies")


if __name__ == "__main__":
    main()
