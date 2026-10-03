#!/usr/bin/env python3
"""Apply one reviewed candidate phase through Argo CD, only after explicit approval.

The required commit argument is a guard against mistakes, not authorization.
Default is read-only preview. No engine-removal or host-rule cleanup operation.
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "clusters/homelab/platform/network-isolation-candidate"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=["policies", "engine", "rollback"])
    p.add_argument("--approved-commit")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()
    app = next(
        a
        for a in yaml.safe_load_all((CANDIDATE / "applications.yaml").read_text())
        if a["metadata"]["name"] == "network-isolation-" + args.phase
    )
    if not args.execute:
        print(yaml.safe_dump(app, sort_keys=False))
        return
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    remote = subprocess.check_output(
        ["git", "ls-remote", "origin", "refs/heads/main"], cwd=ROOT, text=True
    ).split()[0]
    if args.approved_commit != head or head != remote:
        p.error(
            "Execution requires the explicitly approved commit at clean current remote main"
        )
    if subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip():
        p.error("Working tree must be clean")
    subprocess.run(
        ["kustomize", "build", str(CANDIDATE / args.phase)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    if args.phase == "engine":
        policies = json.loads(
            subprocess.check_output(
                ["argocd", "app", "get", "network-isolation-policies", "-o", "json"],
                text=True,
            )
        )
        status = policies["status"]
        if (
            status["sync"]["status"] != "Synced"
            or status["sync"]["revision"] != head
            or status["health"]["status"] != "Healthy"
        ):
            p.error(
                "Policies must be Healthy and Synced at this exact commit before engine activation"
            )
    with tempfile.TemporaryDirectory(prefix="network-isolation-") as temp:
        path = Path(temp) / "application.yaml"
        path.write_text(yaml.safe_dump(app, sort_keys=False))
        subprocess.run(
            ["argocd", "app", "create", "--file", str(path), "--upsert"], check=True
        )
        subprocess.run(
            [
                "argocd",
                "app",
                "sync",
                app["metadata"]["name"],
                "--timeout",
                "180",
                "--revision",
                head,
            ],
            check=True,
        )
    # No automatic pruning; leaving stale firewall rules is not a rollback.
    print("Phase synced. Collect rollout evidence; this is not operational acceptance.")


if __name__ == "__main__":
    main()
