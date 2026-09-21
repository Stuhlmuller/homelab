#!/usr/bin/env python3
"""Create a verified NOFX build context and its complete corresponding source."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


def source_member(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Keep source downloads deterministic and omit local user metadata."""
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ""
    return info


def prepare(destination: Path) -> None:
    recipe = Path(__file__).resolve().parent
    contract = json.loads((recipe / "source.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("build context must be empty")
    with tempfile.TemporaryDirectory(prefix="nofx-source-") as temporary:
        archive = Path(temporary) / "upstream.tar.gz"
        with urllib.request.urlopen(contract["archive_url"], timeout=120) as response:
            with archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != contract["archive_sha256"]:
            raise ValueError("upstream archive SHA-256 mismatch")
        expected_root = "nofx-" + contract["revision"]
        with tarfile.open(archive) as upstream:
            for member in upstream.getmembers():
                if Path(member.name).parts[0] != expected_root:
                    raise ValueError("unexpected upstream archive root")
            # Reject device files, escaping symlinks and paths before extraction.
            upstream.extractall(destination, filter="data")
        (destination / expected_root).rename(destination / "upstream")

    patches = sorted((recipe / "patches").glob("*.patch"))
    if not patches:
        raise ValueError("maintained source requires committed patches")
    for patch in patches:
        subprocess.run(
            ["git", "apply", "--check", str(patch)],
            cwd=destination / "upstream", check=True,
        )
        subprocess.run(
            ["git", "apply", str(patch)], cwd=destination / "upstream", check=True,
        )

    shutil.copytree(recipe, destination / "homelab-build", ignore=shutil.ignore_patterns("__pycache__"))
    revision_file = recipe / "revision.txt"
    revision = revision_file.read_text().strip() if revision_file.exists() else subprocess.check_output(
        ["git", "-C", str(recipe), "rev-parse", "HEAD"], text=True,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("invalid homelab build revision")
    (destination / "homelab-build" / "revision.txt").write_text(revision + "\n")
    for name in ("Dockerfile.backend", "Dockerfile.frontend"):
        shutil.copyfile(recipe / name, destination / name)
    # The served archive includes the full patched upstream, license, lock files,
    # patches, source pin and build scripts. Never include a live database/config.
    with (destination / "nofx-source.tar.gz").open("wb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as bundle:
                bundle.add(destination / "upstream", arcname="nofx", filter=source_member)
                bundle.add(destination / "homelab-build", arcname="homelab-build", filter=source_member)
    print(f"Prepared NOFX {contract['revision']} with {len(patches)} patches")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare-source.py EMPTY_BUILD_CONTEXT")
    prepare(Path(sys.argv[1]).resolve())
