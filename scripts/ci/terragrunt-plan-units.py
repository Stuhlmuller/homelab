#!/usr/bin/env python3
"""Select current-checkout PR plan units without moving saved plans to worktrees."""

import argparse
import json
import subprocess
from pathlib import Path, PurePosixPath

DEPLOYMENT = Path("IaC/homelab/us-west-2")


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def allowed_units():
    units = {"bootstrap/argocd", "operator/application-backup-storage"}
    for pattern in ("apps/*/argocd/terragrunt.hcl", "apps/*/azuread/terragrunt.hcl",
                    "apps/fleet/pilot-user/terragrunt.hcl"):
        units.update(str(path.parent.relative_to(DEPLOYMENT)) for path in DEPLOYMENT.glob(pattern))
    return {unit for unit in units if (DEPLOYMENT / unit / "terragrunt.hcl").is_file()}


def select_units(allowed, changed, discovered):
    selected = set()
    for path in changed:
        parts = PurePosixPath(path).parts
        # Generated units are ignored by Git. A sidecar or stack change must
        # select that application's units even when native find returns no units.
        if len(parts) >= 6 and parts[:3] == DEPLOYMENT.parts and parts[3] == "apps":
            prefix = f"apps/{parts[4]}/"
            selected.update(unit for unit in allowed if unit.startswith(prefix))
        elif (path.startswith("IaC/") or path.startswith("scripts/ci/terragrunt-")
              or path in {"flake.nix", "flake.lock", "policy/terraform.rego",
                          ".github/workflows/terragrunt-plan.yml"}):
            # Native Git filters do not track local Terraform module sources.
            # Shared catalog, root, toolchain and policy edits need full coverage.
            return sorted(allowed)
    for component in discovered:
        path = PurePosixPath(component["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unexpected affected component path: {path}")
        # Git worktree discovery reports repository-relative paths, even when
        # --working-dir points at the deployment tree.
        if path.is_relative_to(DEPLOYMENT):
            path = path.relative_to(DEPLOYMENT)
        if component["type"] == "unit" and str(path) in allowed:
            selected.add(str(path))
        elif component["type"] == "stack":
            selected.update(unit for unit in allowed if unit.startswith(f"{path}/"))
    return sorted(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    changed = output("git", "diff", "--name-only", "--no-renames", args.base, args.head).splitlines()
    allowed = allowed_units()
    # Local edits are not part of Git revision filtering; cover them conservatively.
    dirty = output("git", "status", "--porcelain", "--untracked-files=normal")
    if dirty or select_units(allowed, changed, []) == sorted(allowed):
        selected = sorted(allowed)
    else:
        base = output("git", "rev-parse", args.base)
        head = output("git", "rev-parse", args.head)
        # CI prepare_terragrunt_filter_base binds main to the PR merge base.
        main_ref = subprocess.run(["git", "rev-parse", "--verify", "main"],
                                  capture_output=True, text=True, check=False)
        if main_ref.returncode == 0 and main_ref.stdout.strip() == base and head == output("git", "rev-parse", "HEAD"):
            filters = ["--filter-affected"]
        else:
            filters = ["--filter", f"[{base}...{head}]"]
        discovered = json.loads(output("terragrunt", "--working-dir", str(DEPLOYMENT),
                                       "find", "--json", *filters))
        selected = select_units(allowed, changed, discovered)
    for unit in selected:
        print(DEPLOYMENT / unit)


if __name__ == "__main__":
    main()
