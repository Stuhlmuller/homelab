#!/usr/bin/env python3
"""Render a suspended restore Application from the committed publication contract; never apply."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / "images/postgres-restore-egress/published-image.json"
NAME = "octelium-postgres-restore-drill"
CANDIDATE = "clusters/homelab/apps/octelium-storage/restore-drill-candidate"
LAUNCHER = "/usr/local/bin/restore-no-network"


def verified_pin():
    # Fail before even importing the source checker or asking Git for HEAD.
    if not PIN.is_file() or PIN.is_symlink():
        raise RuntimeError("Committed published image pin is absent; restore reference is blocked")
    spec = importlib.util.spec_from_file_location("restore_source_contract", ROOT / "scripts/ci/restore-talos-synthetic.py")
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    head = source.run("git", "rev-parse", "HEAD").strip()
    pin, _ = source.contract(head)
    return pin


def application(pin):
    """Pure construction after verification; callers cannot override release fields via the CLI."""
    patch = [
        {"op": "test", "path": "/spec/suspend", "value": True},
        {"op": "test", "path": "/spec/jobTemplate/spec/template/spec/containers/0/name", "value": "restore-drill"},
        {"op": "replace", "path": "/spec/suspend", "value": True},
        {"op": "replace", "path": "/spec/jobTemplate/spec/template/spec/containers/0/command", "value": [
            LAUNCHER, "/bin/sh", "/scripts/restore-drill.sh", "/backup/logical-backups", "/work"]},
    ]
    return {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": NAME, "namespace": "argocd", "labels": {
            "app.kubernetes.io/managed-by": "terragrunt", "app.kubernetes.io/part-of": "homelab"}},
        "spec": {
            "project": "homelab",
            "destination": {"name": "", "server": "https://kubernetes.default.svc", "namespace": "octelium-storage"},
            "sources": [{
                "repoURL": "https://github.com/Stuhlmuller/homelab.git", "targetRevision": "main", "path": CANDIDATE,
                "kustomize": {
                    "images": ["postgres=" + pin["image"]],
                    "patches": [{"target": {"group": "batch", "version": "v1", "kind": "CronJob",
                                             "name": NAME, "namespace": "octelium-storage"},
                                 "patch": json.dumps(patch, separators=(",", ":"))}],
                },
            }],
            "syncPolicy": {
                "automated": {"allowEmpty": False, "enabled": True, "prune": True, "selfHeal": True},
                "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true"],
                "retry": {"limit": 5, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "2m"}},
            },
        },
    }


def main():
    if len(sys.argv) != 1:
        raise RuntimeError("Restore reference accepts no arguments or image overrides")
    print(json.dumps(application(verified_pin()), separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Restore reference rejected: {error}", file=sys.stderr)
        raise SystemExit(1) from None
