#!/usr/bin/env python3
"""Inventory committed source paths, never live resources or file contents.

Uses Git tree object IDs to reconcile the complete declared source population.
This is a source inventory, not an HCL parser or deployed workload inventory.
"""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOTS = ("clusters/", "IaC/", ".talos/", ".github/workflows/", "builds/", "policy/")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def collect(repo, revision):
    # Resolve first so user input can never become an option to ls-tree/show.
    sha = git(repo, "rev-parse", "--verify", "--end-of-options",
              revision + "^{commit}").decode().strip()
    entries = git(repo, "ls-tree", "-r", "-z", sha).split(b"\0")
    groups = {}
    for entry in filter(None, entries):
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if not path.startswith(ROOTS):
            continue
        parts = path.split("/")
        if path.startswith("clusters/") and len(parts) >= 5:
            group = "/".join(parts[:4])
        else:
            group = next(root.rstrip("/") for root in ROOTS if path.startswith(root))
        groups.setdefault(group, []).append(entry)
    if not groups or "IaC" not in groups:
        raise ValueError("source population missing")
    stack = git(repo, "show", sha + ":IaC/terragrunt.stack.hcl").decode()
    # Only literal, line-oriented registration paths are extracted. No claims
    # about effective HCL values, Helm expansion, or active resources are made.
    registered = sorted(re.findall(
        r'^\s*path\s*=\s*"live/argocd-apps/([a-z0-9-]+)"\s*$', stack, re.M))
    if not registered or len(registered) != len(set(registered)):
        raise ValueError("missing or duplicate literal app registrations")
    return {
        "schema_version": 1,
        "source_revision": sha,
        "population": "all committed Git tree entries under declared source roots",
        "roots": list(ROOTS),
        "total_entries": sum(map(len, groups.values())),
        "components": [{"path": key, "entries": len(rows),
                        "tree_entries_sha256": hashlib.sha256(
                            b"\0".join(sorted(rows)) + b"\0").hexdigest()}
                       for key, rows in sorted(groups.items())],
        "literal_argocd_registrations": registered,
        "limitations": ["No live collection", "No manifest rendering",
                        "Registration does not establish activation or health",
                        "Hashes cover paths, modes and Git object IDs; no source values emitted"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--revision", required=True)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    result = collect(args.repo, args.revision)
    if args.check:
        expected = json.loads(args.check.read_text())
        # Compare source population across revisions, ignoring only commit ID.
        expected.pop("source_revision", None)
        actual = {k: v for k, v in result.items() if k != "source_revision"}
        if expected != actual:
            raise SystemExit("FAIL: source inventory changed; reconcile scope and issue a new packet")
        print("PASS: complete source population matches approved-for-review baseline")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
