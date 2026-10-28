#!/usr/bin/env python3
"""Recreate and test the pinned Cordium and Octelium policy source patches."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    result.check_returncode()
    return result.stdout.strip()


def prepare(name: str, spec: dict, target: Path, local: Path | None) -> None:
    patch = HERE / spec["patch"]
    actual_hash = hashlib.sha256(patch.read_bytes()).hexdigest()
    if actual_hash != spec["patchSha256"]:
        raise ValueError(f"{name}: patch SHA-256 mismatch")
    source = str(local) if local else spec["url"]
    clone_args = ["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--branch", spec["tag"]]
    if not local:
        clone_args.extend(("--depth", "1"))
    run(*clone_args, source, str(target))
    if run("git", "rev-parse", "HEAD", cwd=target) != spec["revision"]:
        raise ValueError(f"{name}: source revision mismatch")
    for license_path in spec["licenses"]:
        if not (target / license_path).is_file():
            raise ValueError(f"{name}: missing upstream license {license_path}")
    run("git", "apply", "--check", str(patch), cwd=target)
    run("git", "apply", str(patch), cwd=target)
    run("git", "diff", "--check", cwd=target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cordium-repo", type=Path, help="existing pinned clone for offline verification")
    parser.add_argument("--octelium-repo", type=Path, help="existing pinned clone for offline verification")
    parser.add_argument("--output-dir", type=Path, help="retain verified patched sources for a build")
    render_mode = parser.add_mutually_exclusive_group()
    render_mode.add_argument("--check-render", action="store_true",
                             help="compare full generated policies with the candidate fixture")
    render_mode.add_argument("--write-render", action="store_true",
                             help="refresh the candidate fixture for source review")
    args = parser.parse_args()
    source = json.loads((HERE / "source.json").read_text())
    go_env = dict(os.environ, GOTOOLCHAIN=source["goToolchain"])
    if args.output_dir and (args.output_dir.exists() or not args.output_dir.parent.is_dir()):
        raise ValueError("output directory must be absent and its parent must exist")
    with tempfile.TemporaryDirectory(prefix="policy-generators-") as temp:
        root = Path(temp)
        for name in ("cordium", "octelium"):
            prepare(name, source[name], root / name, getattr(args, f"{name}_repo"))
        run("go", "test", "./genesis", "-run", "^TestWorkspacePolicyHasOnlyNamedEgress$", "-count=1",
            cwd=root / "cordium/cluster/genesis", env=go_env)
        run("go", "test", "./genesis/components", "-run", "^TestServiceUpstreamPolicyDeniesEgress$", "-count=1",
            cwd=root / "octelium/cluster/genesis", env=go_env)
        run("go", "test", "./commands/install", "./commands/upgrade", "-run",
            "^Test(PinGenesisImage|InstallRejectsMissingImageBeforeWrites|UpgradeGenesisUsesPinnedImage)$",
            "-count=1", cwd=root / "octelium/client/octops", env=go_env)
        if args.check_render or args.write_render:
            command = [sys.executable, "-I", str(HERE / "render-policies.py"),
                       "--source-dir", str(root)]
            if args.write_render:
                command.append("--write")
            run(*command, env=go_env)
        if args.output_dir:
            for name in ("cordium", "octelium"):
                run("git", "diff", "--check", cwd=root / name)
            os.rename(root, args.output_dir)
    print("Pinned policy sources and targeted tests passed")


if __name__ == "__main__":
    main()
