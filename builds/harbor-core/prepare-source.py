#!/usr/bin/env python3
"""Prepare the pinned Harbor core source and its identical-reference repair."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


def prepare(destination):
    recipe = Path(__file__).resolve().parent
    contract = json.loads((recipe / "source.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("build context must be empty")
    with tempfile.TemporaryDirectory(prefix="harbor-core-source-") as temporary:
        archive = Path(temporary) / "upstream.tar.gz"
        with urllib.request.urlopen(contract["archive_url"], timeout=120) as response:
            with archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != contract["archive_sha256"]:
            raise ValueError("upstream archive SHA-256 mismatch")
        expected_root = "harbor-" + contract["revision"]
        with tarfile.open(archive) as upstream:
            if any(Path(member.name).parts[0] != expected_root for member in upstream.getmembers()):
                raise ValueError("unexpected upstream archive root")
            upstream.extractall(destination, filter="data")
        (destination / expected_root).rename(destination / "upstream")
    shutil.copytree(recipe, destination / "homelab-build", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(destination / "upstream/src/pkg/artifact/manager.go",
                    destination / "homelab-build/original-manager.go")
    patches = sorted((recipe / "patches").glob("*.patch"))
    if len(patches) != 3:
        raise ValueError("expected committed regression, repair and dependency patches")
    for patch in patches:
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=destination / "upstream", check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=destination / "upstream", check=True)
    shutil.copyfile(recipe / "Dockerfile", destination / "Dockerfile")
    print("Prepared pinned Harbor core with duplicate-reference regressions and repair")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare-source.py EMPTY_BUILD_CONTEXT")
    prepare(Path(sys.argv[1]).resolve())
