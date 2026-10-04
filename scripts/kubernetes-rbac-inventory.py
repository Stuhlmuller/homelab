#!/usr/bin/env python3
"""Inventory literal repository RBAC. Not an effective authorization evaluator.

Reads only tracked cluster YAML. Never contacts Kubernetes or outputs Secrets.
Chart/operator/default RBAC, group membership, aggregation and delegated
privilege paths require separate review; an empty match is not a denial.
"""

import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def apps_write_hints(rules):
    """Conservative rule hints, retaining resourceNames for reviewer assessment."""
    hints = []
    for rule in rules:
        if not {"apps", "*"}.intersection(rule.get("apiGroups", [])):
            continue
        verbs = sorted({"create", "update", "patch", "*"}.intersection(rule.get("verbs", [])))
        for resource in ("statefulsets", "controllerrevisions"):
            if verbs and {resource, "*"}.intersection(rule.get("resources", [])):
                hints.append({"resource": resource, "verbs": verbs,
                              "resourceNames": rule.get("resourceNames", [])})
    return hints


def inventory(documents):
    roles = {}
    bindings = []
    accounts = []
    for path, doc in documents:
        if not isinstance(doc, dict):
            continue
        kind = doc.get("kind")
        meta = doc.get("metadata", {})
        namespace = meta.get("namespace", "<render-required>")
        name = meta.get("name")
        if kind == "ServiceAccount":
            accounts.append({"source": path, "namespace": namespace, "name": name,
                             "automount": doc.get("automountServiceAccountToken", "inherited")})
        if doc.get("apiVersion") != "rbac.authorization.k8s.io/v1":
            continue
        if kind in ("Role", "ClusterRole"):
            key = (kind, namespace if kind == "Role" else "*", name)
            if key in roles:
                raise ValueError(f"Duplicate role requires rendered disambiguation: {key}")
            roles[key] = {"source": path, "rules": doc.get("rules", []),
                          "aggregation_unresolved": "aggregationRule" in doc}
        elif kind in ("RoleBinding", "ClusterRoleBinding"):
            bindings.append((path, doc))
    grants = []
    for path, binding in bindings:
        ref = binding["roleRef"]
        namespace = binding["metadata"].get("namespace", "<render-required>")
        key = (ref["kind"], namespace if ref["kind"] == "Role" else "*", ref["name"])
        role = roles.get(key)
        grants.append({"source": path, "binding": binding["metadata"]["name"],
                       "scope": "*" if binding["kind"] == "ClusterRoleBinding" else namespace,
                       "subjects": binding.get("subjects", []), "roleRef": ref,
                       "role": role, "unresolved": role is None or role["aggregation_unresolved"],
                       "apps_write_hints": apps_write_hints(role["rules"]) if role else []})
    return {"scope": "literal tracked cluster YAML only; effective live grants UNKNOWN",
            "service_accounts": accounts, "bindings": grants}


def main():
    paths = subprocess.check_output(
        ["git", "ls-files", "clusters/**/*.yaml", "clusters/**/*.yml"], cwd=ROOT, text=True
    ).splitlines()
    documents = []
    for path in paths:
        for doc in yaml.safe_load_all((ROOT / path).read_text()):
            documents.append((path, doc))
    print(json.dumps(inventory(documents), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
