#!/usr/bin/env python3
"""Offline selective-sync proposal validator. Never contacts Argo or Kubernetes."""

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

NAME = "harbor-vulnerability-exporter"
REPO = "https://github.com/Stuhlmuller/homelab.git"


def require(value):
    if not value:
        raise ValueError("Stop proposal rejected; HOLD")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def plan(e):
    require(
        isinstance(e, dict)
        and set(e)
        == {
            "application",
            "before",
            "after",
            "stop_sha",
            "exclusion_receipt",
            "runtime_receipt",
        }
    )
    require(
        isinstance(e["stop_sha"], str) and re.fullmatch("[0-9a-f]{40}", e["stop_sha"])
    )
    # Receipts are references for independent review, not proof or authorization.
    for key in ("exclusion_receipt", "runtime_receipt"):
        require(
            isinstance(e[key], str) and re.fullmatch("[A-Za-z0-9._-]{1,100}", e[key])
        )
    app = e["application"]
    require(
        app["apiVersion"] == "argoproj.io/v1alpha1" and app["kind"] == "Application"
    )
    require(
        app["metadata"]["name"] == "harbor" and app["metadata"]["namespace"] == "argocd"
    )
    require(bool(app["metadata"]["uid"]) and bool(app["metadata"]["resourceVersion"]))
    require(not app.get("operation"))
    require(
        app.get("status", {}).get("operationState", {}).get("phase")
        in (None, "Succeeded", "Failed", "Error")
    )
    spec = app["spec"]
    require(spec["project"] == "homelab" and "source" not in spec)
    require(
        spec["destination"]["server"] == "https://kubernetes.default.svc"
        and spec["destination"]["namespace"] == "harbor"
    )
    require(spec["syncPolicy"]["automated"]["enabled"] is False)
    require(
        spec["syncPolicy"].get("syncOptions")
        == ["CreateNamespace=true", "ServerSideApply=true"]
    )
    require(not spec.get("ignoreDifferences"))
    sources = spec["sources"]
    require(len(sources) == 3)
    require(
        sources[0]
        == {
            "repoURL": "https://helm.goharbor.io",
            "chart": "harbor",
            "path": ".",
            "targetRevision": "1.19.2",
            "helm": {
                "releaseName": "harbor",
                "valueFiles": ["$values/clusters/homelab/apps/harbor/values.yaml"],
            },
        }
    )
    require(
        sources[1]
        == {
            "repoURL": REPO,
            "targetRevision": "main",
            "ref": "values",
            "path": ".",
            "directory": {"include": ".argocd-values-ref-placeholder.yaml"},
        }
    )
    require(
        sources[2]
        == {
            "repoURL": REPO,
            "targetRevision": "main",
            "path": "clusters/homelab/apps/harbor",
        }
    )
    before, after = e["before"], e["after"]
    for obj in (before, after):
        require(obj["apiVersion"] == "apps/v1" and obj["kind"] == "Deployment")
        require(
            obj["metadata"]["name"] == NAME and obj["metadata"]["namespace"] == "harbor"
        )
        require(
            not any(
                k.startswith("argocd.argoproj.io/")
                for k in obj["metadata"].get("annotations", {})
            )
        )
    require(type(before["spec"]["replicas"]) is int and before["spec"]["replicas"] == 1)
    require(type(after["spec"]["replicas"]) is int and after["spec"]["replicas"] == 0)
    expected = copy.deepcopy(before)
    expected["spec"]["replicas"] = 0
    require(
        expected == after
    )  # Reject any image, mount, script, strategy or ownership delta.
    return {
        "execution_enabled": False,
        "runtime_hook_exclusion_proven": False,
        "application_uid": app["metadata"]["uid"],
        "application_resource_version": app["metadata"]["resourceVersion"],
        "before_sha256": digest(before),
        "after_sha256": digest(after),
        "request_proposal": {
            "name": "harbor",
            "appNamespace": "argocd",
            "project": "homelab",
            "revisions": ["1.19.2", e["stop_sha"], e["stop_sha"]],
            "sourcePositions": [1, 2, 3],
            "prune": False,
            "dryRun": False,
            "resources": [
                {
                    "group": "apps",
                    "kind": "Deployment",
                    "namespace": "harbor",
                    "name": NAME,
                }
            ],
            "strategy": {"apply": {"force": False}},
            "retryStrategy": {"limit": 0},
            "syncOptions": {"items": ["ServerSideApply=true"]},
        },
        "receipts_to_review": [e["exclusion_receipt"], e["runtime_receipt"]],
        "remaining_gate": "Independent fresh readback, exclusion and signed approval; no dispatch adapter exists",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        require(
            not args.execute
        )  # Before any input read; cannot be enabled by configuration.
        require(args.evidence is not None)
        print(json.dumps(plan(json.loads(args.evidence.read_text())), sort_keys=True))
        return 0
    except Exception:  # noqa: BLE001 - do not echo untrusted input
        print("Stop proposal rejected or execution disabled; HOLD.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
