#!/usr/bin/env python3
"""Render the two pinned Genesis policies and prove the exact source-only delta."""

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE = HERE / "candidate-networkpolicies.json"
MARKER = "HOMELAB_POLICY_RENDER:"
POLICIES = (
    ("cordium", "ws-main", "cluster/genesis", "./genesis", "genesis",
     "cordium-render_test.go", "TestHomelabRenderWorkspacePolicy",
     "clusters/homelab/apps/cordium-bootstrap/generated-networkpolicies.json"),
    ("octelium", "svc-upstream", "cluster/genesis", "./genesis/components",
     "genesis/components", "octelium-render_test.go",
     "TestHomelabRenderServiceUpstreamPolicy",
     "clusters/homelab/apps/octelium/generated-networkpolicies.json"),
)


def run(args: list[str], *, cwd: Path | None = None,
        env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                            text=True, timeout=600, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {(result.stderr or result.stdout)[-2000:]}")
    return result.stdout.strip()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def render(repo: Path, module: str, package: str, test_dir: str,
           probe: str, test_name: str, go_env: dict[str, str]) -> dict:
    target = repo / module / test_dir / "homelab_render_test.go"
    if target.exists():
        raise ValueError(f"unexpected existing render probe: {target}")
    shutil.copyfile(HERE / "probes" / probe, target)
    try:
        output = run(["go", "test", package, "-run", f"^{test_name}$",
                      "-count=1", "-v"], cwd=repo / module, env=go_env)
    finally:
        target.unlink()
    marked = [line.removeprefix(MARKER) for line in output.splitlines()
              if line.startswith(MARKER)]
    if len(marked) != 1:
        raise ValueError(f"expected one {test_name} full-policy render")
    policy = json.loads(marked[0])
    if not isinstance(policy, dict) or not isinstance(policy.get("spec"), dict):
        raise ValueError(f"{test_name}: invalid NetworkPolicy render")
    return policy


def current_fixture(path: str, name: str, namespace: str) -> dict:
    listing = json.loads((ROOT / path).read_text())
    matches = [item for item in listing["items"]
               if item.get("metadata", {}).get("name") == name and
               item.get("metadata", {}).get("namespace") == namespace]
    if len(matches) != 1:
        raise ValueError(f"expected one current {namespace}/{name} fixture")
    return matches[0]


def prove_delta(original: dict, patched: dict, fixture: dict,
                name: str, namespace: str) -> None:
    identity = {"name": name, "namespace": namespace}
    if original.get("metadata") != identity or patched.get("metadata") != identity:
        raise ValueError(f"{namespace}/{name}: generated identity changed")
    if original.get("spec") != fixture.get("spec") or fixture.get("metadata") != identity:
        raise ValueError(f"{namespace}/{name}: pinned upstream differs from current fixture")
    egress = original["spec"].get("egress", [])
    if not isinstance(egress, list) or len(egress) != (4 if name == "ws-main" else 1):
        raise ValueError(f"{namespace}/{name}: unexpected upstream egress shape")
    broad = egress[0]
    if broad.get("ports") or {peer.get("ipBlock", {}).get("cidr")
                              for peer in broad.get("to", [])} != {"0.0.0.0/0", "::/0"}:
        raise ValueError(f"{namespace}/{name}: expected exact broad first rule")
    expected = deepcopy(original)
    if egress[1:]:
        expected["spec"]["egress"] = egress[1:]
    else:
        expected["spec"].pop("egress")
    if patched != expected:
        raise ValueError(f"{namespace}/{name}: fields besides broad egress changed")


def generate(source_dir: Path) -> dict:
    source = json.loads((HERE / "source.json").read_text())
    go_env = dict(os.environ, GOTOOLCHAIN=source["goToolchain"])
    entries = []
    with tempfile.TemporaryDirectory(prefix="policy-render-baseline-") as temp:
        for (owner, name, module, package, test_dir, probe, test_name,
             fixture_path) in POLICIES:
            patched_repo = source_dir / owner
            config = source[owner]
            if run(["git", "rev-parse", "HEAD"], cwd=patched_repo) != config["revision"]:
                raise ValueError(f"{owner}: prepared source revision changed")
            if hashlib.sha256((HERE / config["patch"]).read_bytes()).hexdigest() != config["patchSha256"]:
                raise ValueError(f"{owner}: patch hash changed")
            run(["git", "apply", "--reverse", "--check", str(HERE / config["patch"])],
                cwd=patched_repo)
            baseline_repo = Path(temp) / owner
            run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet",
                 "--branch", config["tag"], str(patched_repo), str(baseline_repo)])
            if run(["git", "rev-parse", "HEAD"], cwd=baseline_repo) != config["revision"]:
                raise ValueError(f"{owner}: baseline source revision changed")
            original = render(baseline_repo, module, package, test_dir,
                              probe, test_name, go_env)
            patched = render(patched_repo, module, package, test_dir,
                             probe, test_name, go_env)
            namespace = "cordium" if owner == "cordium" else "octelium"
            fixture = current_fixture(fixture_path, name, namespace)
            prove_delta(original, patched, fixture, name, namespace)
            entries.append({
                "policy": f"{namespace}/{name}",
                "baselineSpecSha256": fingerprint(original["spec"]),
                "candidateSpecSha256": fingerprint(patched["spec"]),
                "rendered": {"apiVersion": fixture["apiVersion"],
                             "kind": fixture["kind"], **patched},
            })
    return {
        "schemaVersion": 1,
        "status": "candidate-source-render-only; no deployment or traffic proof",
        "sources": {owner: {"revision": source[owner]["revision"],
                             "patchSha256": source[owner]["patchSha256"]}
                    for owner in ("cordium", "octelium")},
        "policies": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path,
                        help="verified patched source directory from verify-source.py")
    parser.add_argument("--write", action="store_true",
                        help="refresh the candidate fixture for review")
    args = parser.parse_args()
    rendered = json.dumps(generate(args.source_dir), indent=2, sort_keys=True) + "\n"
    if args.write:
        FIXTURE.write_text(rendered)
    elif not FIXTURE.is_file() or FIXTURE.read_text() != rendered:
        raise SystemExit("candidate generator fixture differs from pinned source render")
    print("Pinned Genesis full-spec renders match the candidate fixture; only broad egress is removed")


if __name__ == "__main__":
    main()
