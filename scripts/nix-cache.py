#!/usr/bin/env python3
"""Publish signed, self-contained Nix check outputs as a GitHub binary cache."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "scripts/config/nix-cache.json"


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def flatten(cache):
    """Release assets have no directories; URL is outside the signed fingerprint."""
    for info in cache.glob("*.narinfo"):
        lines = info.read_text().splitlines()
        if not any(line.startswith("Sig: ") for line in lines):
            raise ValueError(f"Unsigned cache entry: {info.name}")
        for index, line in enumerate(lines):
            if line.startswith("URL: "):
                relative = Path(line[5:])
                if relative.parent != Path("nar") or relative.name != str(relative).split("/")[-1]:
                    raise ValueError("Unexpected NAR URL")
                if (cache / relative).exists():
                    shutil.move(cache / relative, cache / relative.name)
                elif not (cache / relative.name).is_file():
                    raise ValueError("Missing NAR")
                lines[index] = "URL: " + relative.name
        info.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init-key", "init-cache", "publish"))
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--linux", action="store_true", help="Build on the declared homelab Linux executor")
    args = parser.parse_args()
    key = args.key_file.expanduser().resolve()
    if key.is_relative_to(ROOT):
        parser.error("Keep the signing key outside the public checkout")
    if args.action == "init-key":
        if key.exists() or key.with_suffix(".pub").exists():
            parser.error("Refusing to replace an existing signing key")
        key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.umask(0o077)
        subprocess.run(["nix-store", "--generate-binary-cache-key", "homelab-ci-1",
                        str(key), str(key.with_suffix(".pub"))], check=True)
        print(key.with_suffix(".pub").read_text().strip())
        return
    if not key.is_file() or key.stat().st_mode & 0o077:
        parser.error("Signing key must exist with mode 0600 or stricter")
    policy = json.loads(POLICY.read_text())
    public = run("nix", "key", "convert-secret-to-public", input=key.read_text())
    if public != policy["publicKey"]:
        parser.error("Signing key does not match the committed cache policy")
    # Always build the expected checks; never sign an arbitrary caller-supplied path.
    with tempfile.TemporaryDirectory(prefix="homelab-nix-cache-") as temporary:
        cache = Path(temporary)
        destination = cache.as_uri() + "?" + urlencode({"secret-key": str(key)})
        if args.action == "init-cache":
            subprocess.run(["nix", "store", "info", "--store", destination], check=True)
        elif args.linux:
            spec = importlib.util.spec_from_file_location("builder", ROOT / "scripts/nix-builder.py")
            builder = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(builder)
            paths = builder.export(cache, policy)
            subprocess.run(["nix", "store", "sign", "--store", cache.as_uri(),
                            "--key-file", str(key), *paths], check=True)
        else:
            paths = run("bash", "scripts/ci/nix-checks.sh", cwd=ROOT).splitlines()
            subprocess.run(["nix", "copy", "--to", destination, *paths], check=True)
        flatten(cache)
        repo, tag = policy["repository"], policy["tag"]
        release = subprocess.run(["gh", "release", "view", tag, "--repo", repo,
                                  "--json", "assets"], text=True, capture_output=True)
        if release.returncode:
            # Only absence creates a release; auth/network failures are fatal.
            if "release not found" not in release.stderr.lower():
                raise RuntimeError(release.stderr)
            sha = run("git", "rev-parse", "HEAD", cwd=ROOT)
            subprocess.run(["gh", "release", "create", tag, "--repo", repo,
                            "--target", sha, "--prerelease", "--latest=false",
                            "--title", "Signed Nix check cache",
                            "--notes", "Signed offline check outputs. See docs/nix-cache.md."], check=True)
            existing = set()
        else:
            existing = {asset["name"] for asset in json.loads(release.stdout)["assets"]}
        # Upload NARs before metadata. Readers can rebuild during publication.
        assets = sorted(cache.glob("*.nar.xz")) + sorted(cache.glob("*.narinfo")) + [cache / "nix-cache-info"]
        for asset in assets:
            if asset.name in existing:
                prior = cache / "prior"
                prior.mkdir(exist_ok=True)
                subprocess.run(["gh", "release", "download", tag, "--repo", repo,
                                "--pattern", asset.name, "--dir", str(prior)], check=True)
                if (prior / asset.name).read_bytes() != asset.read_bytes():
                    raise RuntimeError(f"Cache asset differs; refusing replacement: {asset.name}")
            else:
                subprocess.run(["gh", "release", "upload", tag, str(asset), "--repo", repo], check=True)


if __name__ == "__main__":
    main()
