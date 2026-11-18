#!/usr/bin/env python3
"""Prove an app stack refactor leaves its rendered runtime contract unchanged."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def run(root, *args):
    return subprocess.run(args, cwd=root, check=True, capture_output=True,
                          text=True, timeout=60).stdout


def contract(root, app):
    root = root.resolve()
    stack = root / f"IaC/homelab/us-west-2/apps/{app}"
    run(root / "IaC", "terragrunt", "--log-disable", "stack", "generate")
    unit = stack / "argocd"
    data = json.loads(run(unit, "terragrunt", "--log-disable", "render", "--json", "--write=false"))
    source = Path(data["terraform"]["source"]).resolve()
    if not source.is_relative_to(root / "IaC/terragrunt-catalog/modules"):
        raise ValueError("Only repository-owned root modules can establish equivalence")
    modules = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in source.rglob("*") if p.is_file()}
    if not modules:
        raise ValueError("Missing module implementation")
    variables = set(re.findall(r'variable\s+"([^"]+)"', "\n".join(p.read_text() for p in source.rglob("*.tf"))))
    # Only declared module inputs affect OpenTofu. Root convenience inputs may
    # disappear without changing the resource contract; module bytes must match.
    data["inputs"] = {key: value for key, value in data.get("inputs", {}).items() if key in variables}
    data.pop("locals", None)
    data.pop("catalog", None)
    data["dependencies"]["paths"] = [str(Path(p).resolve().relative_to(root))
                                       for p in data["dependencies"]["paths"]]
    normalized = json.loads(json.dumps(data).replace(str(root), "<root>"))
    return {"module": modules, "rendered": normalized}


def equivalent(app, paths, base_ref, root=ROOT):
    """Fail closed; only an existing app's stack.hcl-only edit is eligible."""
    relevant = [p for p in paths if not p.endswith(".md") and (
        p.startswith(f"clusters/homelab/apps/{app}/") or p.startswith("IaC/") and f"/{app}/" in p)]
    if relevant != [f"IaC/homelab/us-west-2/apps/{app}/stack.hcl"]:
        return False
    try:
        base = run(root, "git", "merge-base", base_ref, "HEAD").strip()
        with tempfile.TemporaryDirectory(prefix="app-equivalence-") as temporary:
            snapshots = []
            for name, revision in (("base", base), ("head", "HEAD")):
                destination = Path(temporary) / name
                destination.mkdir()
                archive = destination / "source.tar"
                run(root, "git", "archive", "--format=tar", "-o", str(archive), revision, "IaC")
                run(destination, "tar", "-xf", str(archive))
                run(destination, "git", "init", "-q")
                snapshots.append(contract(destination, app))
            return snapshots[0] == snapshots[1]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return False
