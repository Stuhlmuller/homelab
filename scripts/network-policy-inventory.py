#!/usr/bin/env python3
"""Inventory effective NetworkPolicy egress from read-only Kubernetes snapshots.

Pass separate JSON snapshots from ``kubectl get pods -A -o json`` and
``kubectl get networkpolicies -A -o json``, plus every rendered policy source,
including controller-generated policy output. The script never invokes kubectl
or changes cluster state.
"""

import argparse
import hashlib
import ipaddress
import json
from pathlib import Path


PORT_PROTOCOLS = ("TCP", "UDP", "SCTP")
RISKY_CAPABILITIES = {"ALL", "NET_ADMIN", "NET_RAW", "SYS_ADMIN"}


def canonical(value):
    """Return a stable representation for NetworkPolicy's unordered collections."""
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        values = [canonical(item) for item in value]
        return sorted(
            values,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    return value


def load_items(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read JSON snapshot: {path}") from error
    if isinstance(value, dict):
        value = value.get("items", [value])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Snapshot must be a Kubernetes List or object: {path}")
    return value


def metadata(item):
    value = item.get("metadata")
    if not isinstance(value, dict):
        raise ValueError("Kubernetes object has no metadata")
    namespace, name = value.get("namespace"), value.get("name")
    if not isinstance(namespace, str) or not namespace or not isinstance(name, str) or not name:
        raise ValueError("NetworkPolicy must have namespace and name")
    return namespace, name


def policy_types(spec):
    declared = spec.get("policyTypes")
    if declared is None:
        return {"Ingress", "Egress"} if "egress" in spec else {"Ingress"}
    if (not isinstance(declared, list) or
            not all(item in {"Ingress", "Egress"} for item in declared)):
        raise ValueError("NetworkPolicy policyTypes is invalid")
    return set(declared)


def selector_parts(selector):
    if not isinstance(selector, dict):
        raise ValueError("NetworkPolicy selector is invalid")
    exact = selector.get("matchLabels", {})
    expressions = selector.get("matchExpressions", [])
    if not isinstance(exact, dict) or not isinstance(expressions, list):
        raise ValueError("NetworkPolicy selector is invalid")
    return exact, expressions


def validated_selector(selector):
    exact, expressions = selector_parts(selector)
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in exact.items()):
        raise ValueError("NetworkPolicy selector is invalid")
    for expression in expressions:
        if not isinstance(expression, dict):
            raise ValueError("NetworkPolicy selector expression is invalid")
        key, operator = expression.get("key"), expression.get("operator")
        values = expression.get("values", [])
        if not isinstance(key, str) or operator not in {"In", "NotIn", "Exists", "DoesNotExist"}:
            raise ValueError("NetworkPolicy selector expression is invalid")
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("NetworkPolicy selector expression values are invalid")
        if (operator in {"In", "NotIn"} and not values) or (
                operator in {"Exists", "DoesNotExist"} and values):
            raise ValueError("NetworkPolicy selector expression values are invalid")
    return exact, expressions


def selector_matches(selector, labels):
    if not isinstance(labels, dict):
        raise ValueError("Pod labels are invalid")
    exact, expressions = validated_selector(selector)
    if any(labels.get(key) != value for key, value in exact.items()):
        return False
    for expression in expressions:
        key, operator = expression["key"], expression["operator"]
        values = expression.get("values", [])
        present, value = key in labels, labels.get(key)
        if ((operator == "In" and (not present or value not in values)) or
                (operator == "NotIn" and (not present or value in values)) or
                (operator == "Exists" and not present) or
                (operator == "DoesNotExist" and present)):
            return False
    return True


def empty_selector(selector):
    exact, expressions = validated_selector(selector)
    return not exact and not expressions


def negative_selector(selector):
    return any(
        expression["operator"] in {"NotIn", "DoesNotExist"}
        for expression in validated_selector(selector)[1]
    )


def normalized_selector(selector):
    if not isinstance(selector, dict):
        return selector
    return {
        key: value for key, value in selector.items()
        if not ((key == "matchLabels" and value == {}) or
                (key == "matchExpressions" and value == []))
    }


def normalized_peer(peer):
    if not isinstance(peer, dict):
        return peer
    normalized = dict(peer)
    for field in ("podSelector", "namespaceSelector"):
        if field in normalized:
            normalized[field] = normalized_selector(normalized[field])
    block = normalized.get("ipBlock")
    if isinstance(block, dict) and block.get("except") == []:
        normalized["ipBlock"] = {key: value for key, value in block.items() if key != "except"}
    return normalized


def normalized_egress(egress):
    """Apply Kubernetes defaults that affect NetworkPolicy equality."""
    normalized = []
    for rule in egress:
        if not isinstance(rule, dict):
            normalized.append(rule)
            continue
        normalized_rule = dict(rule)
        ports = normalized_rule.get("ports")
        if ports == []:
            normalized_rule.pop("ports")
        elif isinstance(ports, list):
            normalized_rule["ports"] = [
                {**port, "protocol": "TCP"}
                if isinstance(port, dict) and port.get("protocol") is None else port
                for port in ports
            ]
        destinations = normalized_rule.get("to")
        if destinations == []:
            normalized_rule.pop("to")
        elif isinstance(destinations, list):
            normalized_rule["to"] = [normalized_peer(peer) for peer in destinations]
        normalized.append(normalized_rule)
    return canonical(normalized)


def normalized_policy(item):
    if item.get("kind") != "NetworkPolicy":
        raise ValueError("Policy snapshot contains a non-NetworkPolicy object")
    namespace, name = metadata(item)
    spec = item.get("spec")
    if not isinstance(spec, dict) or not isinstance(spec.get("podSelector"), dict):
        raise ValueError("NetworkPolicy spec is invalid")
    types = policy_types(spec)
    egress = spec.get("egress", [])
    if "Egress" in types and not isinstance(egress, list):
        raise ValueError("NetworkPolicy egress must be a list")
    return {
        "namespace": namespace,
        "name": name,
        "podSelector": canonical(normalized_selector(spec["podSelector"])),
        "policyTypes": sorted(types),
        "egress": normalized_egress(egress if "Egress" in types else []),
    }


def policy_fingerprint(policy):
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def policies(items, strict=False):
    result = {}
    for item in items:
        if item.get("kind") != "NetworkPolicy":
            if strict:
                raise ValueError("NetworkPolicy snapshot contains a non-NetworkPolicy object")
            continue
        policy = normalized_policy(item)
        key = (policy["namespace"], policy["name"])
        if key in result and result[key] != policy:
            raise ValueError(f"Conflicting NetworkPolicy snapshots for {key[0]}/{key[1]}")
        result[key] = policy
    return result


def allowed_ip_intervals(block):
    cidr, exceptions = block.get("cidr"), block.get("except", [])
    if not isinstance(cidr, str) or not isinstance(exceptions, list):
        raise ValueError("NetworkPolicy IP block is invalid")
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError as error:
        raise ValueError("NetworkPolicy IP block CIDR is invalid") from error
    intervals = [(int(network.network_address), int(network.broadcast_address))]
    for value in exceptions:
        if not isinstance(value, str):
            raise ValueError("NetworkPolicy IP block exception is invalid")
        try:
            excluded = ipaddress.ip_network(value, strict=False)
        except ValueError as error:
            raise ValueError("NetworkPolicy IP block exception is invalid") from error
        if excluded.version != network.version or not excluded.subnet_of(network):
            raise ValueError("NetworkPolicy IP block exception is outside its CIDR")
        start, end = int(excluded.network_address), int(excluded.broadcast_address)
        remaining = []
        for interval_start, interval_end in intervals:
            if end < interval_start or start > interval_end:
                remaining.append((interval_start, interval_end))
                continue
            if start > interval_start:
                remaining.append((interval_start, start - 1))
            if end < interval_end:
                remaining.append((end + 1, interval_end))
        intervals = remaining
    return network.version, intervals


def covers_range(intervals, minimum, maximum):
    cursor = minimum
    for start, end in sorted(intervals):
        if start > cursor:
            return False
        cursor = max(cursor, end + 1)
        if cursor > maximum:
            return True
    return False


def covers_address_space(intervals, version):
    return covers_range(intervals, 0, (1 << (32 if version == 4 else 128)) - 1)


def allowed_port_intervals(ports):
    intervals = {protocol: [] for protocol in PORT_PROTOCOLS}
    if not ports:
        for values in intervals.values():
            values.append((1, 65535))
        return intervals
    for port in ports:
        if not isinstance(port, dict):
            raise ValueError("NetworkPolicy egress port is invalid")
        protocol = port.get("protocol", "TCP")
        if protocol not in PORT_PROTOCOLS:
            raise ValueError("NetworkPolicy egress port protocol is invalid")
        if "port" not in port:
            if "endPort" in port:
                raise ValueError("NetworkPolicy egress endPort requires port")
            intervals[protocol].append((1, 65535))
            continue
        value = port["port"]
        if type(value) is int:
            if not 1 <= value <= 65535:
                raise ValueError("NetworkPolicy egress port is invalid")
            end = port.get("endPort", value)
            if type(end) is not int or not value <= end <= 65535:
                raise ValueError("NetworkPolicy egress endPort is invalid")
            intervals[protocol].append((value, end))
        elif isinstance(value, str) and value:
            if "endPort" in port:
                raise ValueError("NetworkPolicy egress endPort requires numeric port")
        else:
            raise ValueError("NetworkPolicy egress port is invalid")
    return intervals


def broad_rule(rule):
    if not isinstance(rule, dict):
        raise ValueError("NetworkPolicy egress rule is invalid")
    findings = []
    destinations = rule.get("to", [])
    ports = rule.get("ports", [])
    if not isinstance(destinations, list) or not isinstance(ports, list):
        raise ValueError("NetworkPolicy egress rule is invalid")
    intervals = {4: [], 6: []}
    has_ip_range = False
    if not destinations:
        findings.append("all-destinations")
    for destination in destinations:
        if not isinstance(destination, dict):
            raise ValueError("NetworkPolicy egress destination is invalid")
        pod_selector = destination.get("podSelector")
        namespace_selector = destination.get("namespaceSelector")
        block = destination.get("ipBlock")
        if pod_selector is not None and not isinstance(pod_selector, dict):
            raise ValueError("NetworkPolicy pod selector is invalid")
        if namespace_selector is not None and not isinstance(namespace_selector, dict):
            raise ValueError("NetworkPolicy namespace selector is invalid")
        if block is not None and not isinstance(block, dict):
            raise ValueError("NetworkPolicy IP block is invalid")
        if block is not None and (pod_selector is not None or namespace_selector is not None):
            raise ValueError("NetworkPolicy peer cannot combine IP block and selectors")
        pod_all = pod_selector is not None and empty_selector(pod_selector)
        namespace_all = namespace_selector is not None and empty_selector(namespace_selector)
        if pod_selector is not None and negative_selector(pod_selector):
            findings.append("negative-pod-selector")
        if namespace_selector is not None and negative_selector(namespace_selector):
            findings.append("negative-namespace-selector")
        if pod_selector is None and namespace_selector is None and block is None:
            findings.append("all-destinations")
        if block is None and (pod_selector is None or pod_all):
            findings.append("all-pods")
        if namespace_all:
            findings.append("all-namespaces")
        if block is None and namespace_all and (pod_selector is None or pod_all):
            findings.append("all-destinations")
        if block is not None:
            version, allowed = allowed_ip_intervals(block)
            intervals[version].extend(allowed)
            has_ip_range = has_ip_range or any(start != end for start, end in allowed)
    if any(covers_address_space(values, version) for version, values in intervals.items()):
        findings.append("all-ip-range")
    elif has_ip_range:
        findings.append("ip-range")
    port_intervals = allowed_port_intervals(ports)
    if any(covers_range(values, 1, 65535) for values in port_intervals.values()):
        findings.append("all-ports")
    elif any(start != end for values in port_intervals.values() for start, end in values):
        findings.append("port-range")
    return sorted(set(findings))


def effective_wildcards(rules):
    addresses = {4: [], 6: []}
    ports = {protocol: [] for protocol in PORT_PROTOCOLS}
    for rule in rules:
        broad_rule(rule)
        for destination in rule.get("to", []):
            block = destination.get("ipBlock")
            if block is not None:
                version, intervals = allowed_ip_intervals(block)
                addresses[version].extend(intervals)
        for protocol, intervals in allowed_port_intervals(rule.get("ports", [])).items():
            ports[protocol].extend(intervals)
    findings = []
    if any(covers_address_space(values, version) for version, values in addresses.items()):
        findings.append("all-ip-range")
    if any(covers_range(values, 1, 65535) for values in ports.values()):
        findings.append("all-ports")
    return findings


def peer_target_selectors(namespace, rule):
    """Return resolvable peer selectors grouped by their target namespace."""
    selectors = {}
    findings = []
    for destination in rule.get("to", []):
        if destination.get("ipBlock") is not None:
            continue
        selector = destination.get("podSelector")
        namespace_selector = destination.get("namespaceSelector")
        if selector is None or empty_selector(selector):
            continue
        target_namespace = namespace
        if namespace_selector is not None:
            exact, expressions = validated_selector(namespace_selector)
            if len(exact) == 1 and not expressions and "kubernetes.io/metadata.name" in exact:
                target_namespace = exact["kubernetes.io/metadata.name"]
            else:
                findings.append("unresolved-namespace-selector")
                continue
        selectors.setdefault(target_namespace, []).append(selector)
    return selectors, sorted(set(findings))


def effective_destination_wildcards(records, pods, source):
    """Return broad effective reachability across selector and IPBlock peers."""
    selectors = {}
    intervals = {4: [], 6: []}
    for record in records:
        for egress in record["egress"]:
            rule = egress["rule"]
            target_selectors, _ = peer_target_selectors(record["namespace"], rule)
            for namespace, values in target_selectors.items():
                selectors.setdefault(namespace, []).extend(values)
            for destination in rule.get("to", []):
                block = destination.get("ipBlock")
                if block is not None:
                    version, allowed = allowed_ip_intervals(block)
                    intervals[version].extend(allowed)

    def matches_peer(pod):
        return any(
            pod["namespace"] == namespace and any(
                selector_matches(selector, pod["labels"]) for selector in values
            )
            for namespace, values in selectors.items()
        )

    def matches_destination(pod):
        return matches_peer(pod) or any(
            start <= address <= end for version, address in pod["ips"]
            for start, end in intervals[version]
        )

    targets = [
        pod for pod in pods
        if (pod["namespace"], pod["name"]) != (source["namespace"], source["name"])
    ]
    if any(intervals.values()) and any(not pod["ips"] and not matches_peer(pod) for pod in targets):
        return ["unresolved-pod-ip"]
    findings = []
    for namespace in {pod["namespace"] for pod in targets}:
        namespace_targets = [pod for pod in targets if pod["namespace"] == namespace]
        if len(namespace_targets) > 1 and all(matches_destination(pod) for pod in namespace_targets):
            findings.append("all-current-pods")
    if len(targets) > 1 and all(matches_destination(pod) for pod in targets):
        findings.append("all-current-pods")
    return sorted(set(findings))


def review_entries(path):
    if path is None:
        return {}
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read policy review: {path}") from error
    entries = value.get("policies") if isinstance(value, dict) else value
    if not isinstance(entries, list):
        raise ValueError("Policy review must contain a policies list")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Policy review entry is invalid")
        namespace, name, digest = entry.get("namespace"), entry.get("name"), entry.get("sha256")
        if (not isinstance(namespace, str) or not isinstance(name, str) or
                not isinstance(digest, str) or len(digest) != 64 or
                any(character not in "0123456789abcdef" for character in digest)):
            raise ValueError("Policy review entry requires namespace, name and sha256")
        key = (namespace, name)
        if key in result and result[key] != digest:
            raise ValueError("Policy review has conflicting fingerprints")
        result[key] = digest
    return result


def active_pods(items, namespaces):
    result = []
    for item in items:
        if item.get("kind") != "Pod":
            raise ValueError("Pod snapshot contains a non-Pod object")
        metadata_value = item.get("metadata", {})
        spec = item.get("spec", {})
        status = item.get("status", {})
        if not isinstance(status, dict):
            raise ValueError("Pod status is invalid")
        namespace, name = metadata_value.get("namespace"), metadata_value.get("name")
        if not isinstance(namespace, str) or not isinstance(name, str):
            raise ValueError("Pod snapshot is missing namespace or name")
        if namespaces and namespace not in namespaces:
            continue
        if status.get("phase") in {"Succeeded", "Failed"}:
            continue
        labels = metadata_value.get("labels", {})
        if not isinstance(labels, dict) or not all(isinstance(key, str) and isinstance(value, str)
                                                   for key, value in labels.items()):
            raise ValueError("Pod labels are invalid")
        if not isinstance(spec, dict):
            raise ValueError("Pod spec is invalid")
        ip_values = status.get("podIPs", [])
        if ip_values is None:
            ip_values = []
        legacy_ip = status.get("podIP")
        if legacy_ip is not None:
            if not isinstance(legacy_ip, str):
                raise ValueError("Pod IPs are invalid")
            ip_values = [*ip_values, {"ip": legacy_ip}]
        if (not isinstance(ip_values, list) or not all(
                isinstance(value, dict) and isinstance(value.get("ip"), str)
                for value in ip_values)):
            raise ValueError("Pod IPs are invalid")
        ips = set()
        for value in ip_values:
            try:
                address = ipaddress.ip_address(value["ip"])
            except ValueError as error:
                raise ValueError("Pod IPs are invalid") from error
            ips.add((address.version, int(address)))
        containers = []
        for field, kind in (("containers", "container"), ("initContainers", "init-container"),
                            ("ephemeralContainers", "ephemeral-container")):
            values = spec.get(field, [])
            if not isinstance(values, list):
                raise ValueError("Pod containers are invalid")
            for container in values:
                if not isinstance(container, dict):
                    raise ValueError("Pod container is invalid")
                security = container.get("securityContext", {})
                if not isinstance(security, dict):
                    raise ValueError("Pod security context is invalid")
                capabilities = security.get("capabilities", {})
                if not isinstance(capabilities, dict):
                    raise ValueError("Pod capabilities are invalid")
                added, dropped = capabilities.get("add", []), capabilities.get("drop", [])
                if (not isinstance(added, list) or not isinstance(dropped, list) or
                        not all(isinstance(value, str) for value in added + dropped)):
                    raise ValueError("Pod capabilities are invalid")
                normalized_added = {value.upper().removeprefix("CAP_") for value in added}
                normalized_dropped = {value.upper().removeprefix("CAP_") for value in dropped}
                containers.append({
                    "kind": kind,
                    "name": container.get("name", "<unnamed>"),
                    "privileged": security.get("privileged") is True,
                    "capabilities": sorted(RISKY_CAPABILITIES & normalized_added),
                    "dropsAllCapabilities": "ALL" in normalized_dropped,
                })
        result.append({
            "namespace": namespace,
            "name": name,
            "labels": dict(sorted(labels.items())),
            "serviceAccount": spec.get("serviceAccountName", "default"),
            "hostNetwork": spec.get("hostNetwork") is True,
            "ips": sorted(ips),
            "containers": containers,
        })
    return sorted(result, key=lambda pod: (pod["namespace"], pod["name"]))


def audit(pod_items, policy_items, render_items, review_path=None, namespaces=()):
    """Return an effective-egress inventory without contacting Kubernetes."""
    pod_items = list(pod_items)
    if not pod_items:
        raise ValueError("Pod snapshot is empty")
    live = policies(policy_items, strict=True)
    rendered = policies(item for items in render_items for item in items)
    reviewed = review_entries(review_path)
    namespaces = set(namespaces)
    all_pods = active_pods(pod_items, ())

    def scoped(key):
        return not namespaces or key[0] in namespaces

    live_keys, rendered_keys = set(live), set(rendered)
    live_only = sorted(key for key in live_keys - rendered_keys if scoped(key))
    source_only = sorted(key for key in rendered_keys - live_keys if scoped(key))
    drifted = sorted(
        key for key in live_keys & rendered_keys if live[key] != rendered[key] and scoped(key)
    )
    policy_records = []
    for key, policy in sorted(live.items()):
        if not scoped(key):
            continue
        owned = "owned"
        if key in live_only:
            owned = "live-only"
        elif key in drifted:
            owned = "drifted"
        fingerprint = policy_fingerprint(policy)
        rules = []
        for rule in policy["egress"]:
            base_findings = broad_rule(rule)
            _, peer_findings = peer_target_selectors(key[0], rule)
            rules.append({
                "rule": rule,
                "wildcards": sorted(set(base_findings) | set(peer_findings)),
            })
        egress_mode = "not-applicable"
        if "Egress" in policy["policyTypes"]:
            egress_mode = "deny-all" if not rules else "allow-rules"
        policy_records.append({
            "namespace": key[0],
            "name": key[1],
            "state": owned,
            "fingerprint": fingerprint,
            "policyTypes": policy["policyTypes"],
            "egressMode": egress_mode,
            "egress": rules,
            "reviewed": reviewed.get(key) == fingerprint,
        })
    inventory = []
    findings = []
    policy_index = {(record["namespace"], record["name"]): record for record in policy_records}
    for key in live_only:
        if "Egress" in live[key]["policyTypes"]:
            findings.append({"kind": "unowned-egress-policy", "policy": "/".join(key)})
    for key in drifted:
        if "Egress" in live[key]["policyTypes"]:
            findings.append({"kind": "drifted-egress-policy", "policy": "/".join(key)})
    for key in source_only:
        if "Egress" in rendered[key]["policyTypes"]:
            findings.append({"kind": "source-only-egress-policy", "policy": "/".join(key)})
    for record in policy_records:
        policy = live[(record["namespace"], record["name"])]
        if "Egress" not in policy["policyTypes"]:
            continue
        if not record["reviewed"]:
            findings.append({"kind": "unreviewed-egress-policy",
                             "policy": record["namespace"] + "/" + record["name"]})
        for index, rule in enumerate(record["egress"]):
            if rule["wildcards"]:
                findings.append({
                    "kind": "wildcard-egress",
                    "policy": record["namespace"] + "/" + record["name"],
                    "rule": index,
                    "wildcards": rule["wildcards"],
                })
    pods = [pod for pod in all_pods if not namespaces or pod["namespace"] in namespaces]
    missing_namespaces = namespaces - {pod["namespace"] for pod in pods}
    if missing_namespaces:
        raise ValueError("Candidate namespace has no active Pod")
    if not pods:
        raise ValueError("Pod snapshot has no active Pods")
    for pod in pods:
        selected = []
        for key, policy in live.items():
            if (key[0] == pod["namespace"] and "Egress" in policy["policyTypes"] and
                    selector_matches(policy["podSelector"], pod["labels"])):
                selected.append(policy_index[key])
        selected.sort(key=lambda item: (item["namespace"], item["name"]))
        union = []
        for record in selected:
            union.extend(record["egress"])
        union = sorted(
            {
                json.dumps(rule, sort_keys=True, separators=(",", ":")): rule
                for rule in union
            }.values(),
            key=lambda rule: json.dumps(rule, sort_keys=True, separators=(",", ":")),
        )
        rule_wildcards = {
            wildcard for policy_record in selected for rule in policy_record["egress"]
            for wildcard in rule["wildcards"]
        }
        aggregate_wildcards = sorted(
            (set(effective_wildcards([rule["rule"] for policy_record in selected
                                      for rule in policy_record["egress"]])) |
             set(effective_destination_wildcards(selected, all_pods, pod))) - rule_wildcards
        )
        exceptions = []
        if pod["hostNetwork"]:
            exceptions.append("host-network")
        for container in pod["containers"]:
            if container["privileged"]:
                exceptions.append("privileged-" + container["kind"] + ":" + str(container["name"]))
            elif container["kind"] == "init-container":
                exceptions.append("init-container:" + str(container["name"]))
            if not container["privileged"] and not container["dropsAllCapabilities"]:
                exceptions.append("capabilities-not-drop-all:" + container["kind"] + ":" + str(container["name"]))
            for capability in container["capabilities"]:
                exceptions.append(
                    "capability-" + capability + ":" + container["kind"] + ":" + str(container["name"])
                )
        record = {
            "namespace": pod["namespace"],
            "name": pod["name"],
            "labels": pod["labels"],
            "serviceAccount": pod["serviceAccount"],
            "matchingEgressPolicies": [item["namespace"] + "/" + item["name"] for item in selected],
            "egressMode": (
                "unrestricted" if not selected else "deny-all" if not union else "allow-rules"
            ),
            "effectiveEgress": union,
            "effectiveWildcards": aggregate_wildcards,
            "exceptions": sorted(exceptions),
        }
        inventory.append(record)
        identity = pod["namespace"] + "/" + pod["name"]
        if not selected:
            findings.append({"kind": "unisolated-pod", "pod": identity})
        if record["effectiveWildcards"]:
            findings.append({"kind": "wildcard-effective-egress", "pod": identity,
                             "wildcards": record["effectiveWildcards"]})
        for exception in record["exceptions"]:
            findings.append({"kind": "pod-requires-separate-review", "pod": identity,
                             "exception": exception})
    return {
        "pods": inventory,
        "policies": policy_records,
        "liveOnlyPolicies": ["/".join(key) for key in live_only],
        "sourceOnlyPolicies": ["/".join(key) for key in source_only],
        "driftedPolicies": ["/".join(key) for key in drifted],
        "findings": sorted(findings, key=lambda item: json.dumps(item, sort_keys=True)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pods", required=True, type=Path, help="kubectl get pods -A -o json snapshot"
    )
    parser.add_argument("--policies", required=True, type=Path,
                        help="kubectl get networkpolicies -A -o json snapshot")
    parser.add_argument("--render", required=True, action="append", type=Path,
                        help="rendered NetworkPolicy JSON; repeat for every source and generator")
    parser.add_argument("--review", type=Path,
                        help="JSON policy fingerprints approved against rendered policy")
    parser.add_argument("--namespace", action="append", default=[],
                        help="limit the candidate audit to this namespace; repeat as needed")
    parser.add_argument("--fail-on-findings", action="store_true",
                        help="return non-zero for wildcard, drift, unreviewed or bypass findings")
    args = parser.parse_args()
    try:
        result = audit(load_items(args.pods), load_items(args.policies),
                       [load_items(path) for path in args.render], args.review, args.namespace)
    except ValueError as error:
        raise SystemExit(f"NetworkPolicy inventory failed: {error}") from None
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.fail_on_findings and result["findings"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
