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
    if source != root / "IaC/terragrunt-catalog/modules/argocd-application-kubernetes":
        raise ValueError("Unsupported Application module")
    terraform = data["terraform"]
    if any(terraform.get(key) for key in ("extra_arguments", "after_hook", "error_hook", "include_in_copy", "exclude_from_copy")):
        raise ValueError("Unsupported external execution inputs")
    guard = root / "scripts/ci/terragrunt-current-main.sh"
    expected_hook = {"verify_current_main_before_apply": {
        "commands": ["apply"], "execute": ["bash", f"{root}/IaC/../scripts/ci/terragrunt-current-main.sh"],
        "if": None, "name": "verify_current_main_before_apply", "run_on_error": None,
        "suppress_stdout": None, "working_dir": None}}
    if terraform.get("before_hook") != expected_hook:
        raise ValueError("Unsupported hook")
    text = "\n".join(p.read_text() for p in source.rglob("*.tf"))
    indirect = r'\b(?:module|provisioner)\s+"|\bdata\s+"external"|\b(?:file\w*|templatefile)\s*\('
    if (list(source.rglob("*.tf.json")) or re.search(indirect, text)
            or any(re.search(indirect + r"|\bvariable\b", block["contents"]) for block in data["generate"].values())):
        raise ValueError("Unsupported indirect module inputs")
    manifest = data["inputs"]["manifest"]
    if manifest["apiVersion"] != "argoproj.io/v1alpha1" or manifest["kind"] != "Application":
        raise ValueError("Missing Application contract")
    modules = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in source.rglob("*") if p.is_file()}
    if not modules:
        raise ValueError("Missing module implementation")
    variables = set(re.findall(r'variable\s+"([^"]+)"', text))
    # Only declared module inputs affect OpenTofu. Root convenience inputs may
    # disappear without changing the resource contract; module bytes must match.
    data["inputs"] = {key: value for key, value in data["inputs"].items() if key in variables}
    data.pop("locals", None)
    data.pop("catalog", None)
    data["dependencies"]["paths"] = [str(Path(p).resolve().relative_to(root))
                                       for p in data["dependencies"]["paths"]]
    normalized = json.loads(json.dumps(data).replace(str(root), "<root>"))
    return {"module": modules, "rendered": normalized, "apply_guard": hashlib.sha256(guard.read_bytes()).hexdigest()}


def equivalent(app, paths, base_ref, root=ROOT):
    """Compare the existing app's rendered contract for eligible IaC edits."""
    relevant = [p for p in paths if not p.endswith(".md") and (
        p.startswith(f"clusters/homelab/apps/{app}/") or p.startswith("IaC/") and f"/{app}/" in p)]
    app_stack_only = relevant == [f"IaC/homelab/us-west-2/apps/{app}/stack.hcl"]
    shared_root = not relevant and "IaC/root.hcl" in paths
    if not (app_stack_only or shared_root):
        return False
    try:
        base = run(root, "git", "merge-base", base_ref, "HEAD").strip()
        with tempfile.TemporaryDirectory(prefix="app-equivalence-") as temporary:
            snapshots = []
            for name, revision in (("base", base), ("head", "HEAD")):
                destination = Path(temporary) / name
                destination.mkdir()
                archive = destination / "source.tar"
                run(root, "git", "archive", "--format=tar", "-o", str(archive), revision, "IaC", "scripts/ci/terragrunt-current-main.sh")
                run(destination, "tar", "-xf", str(archive))
                run(destination, "git", "init", "-q")
                snapshots.append(contract(destination, app))
            return snapshots[0] == snapshots[1]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return False
