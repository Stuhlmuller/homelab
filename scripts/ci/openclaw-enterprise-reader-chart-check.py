#!/usr/bin/env python3
"""Run reader policy overlap against the exact stock Enterprise chart commit.

The required validation job needs repository read access, not cloud credentials.
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "builds/openclaw-enterprise/source.json"
READER_TEST = ROOT / "scripts/ci/openclaw-enterprise-reader-policy-test.py"
UPSTREAM_URL = "https://github.com/openclaw/openclaw-enterprise.git"


def git(*arguments):
    return subprocess.run(["git", *map(str, arguments)], check=True,
                          capture_output=True, text=True, timeout=180).stdout.strip()


def pinned_revision(contract):
    revision = json.loads(contract.read_text())["revision"]
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Enterprise source revision must be a full SHA")
    return revision


def fetch_pinned_chart(destination, revision, remote=UPSTREAM_URL):
    """Fetch only the reviewed object; a missing chart or changed HEAD is fatal."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Enterprise source revision must be a full SHA")
    git("init", "--quiet", destination)
    git("-C", destination, "fetch", "--no-tags", "--depth=1", remote, revision)
    git("-C", destination, "checkout", "--quiet", "--detach", "FETCH_HEAD")
    if git("-C", destination, "rev-parse", "HEAD") != revision:
        raise ValueError("Enterprise chart HEAD differs from pinned source")
    if git("-C", destination, "status", "--porcelain"):
        raise ValueError("Enterprise chart checkout is dirty")
    if not (destination / "deploy/helm/openclaw-enterprise/Chart.yaml").is_file():
        raise FileNotFoundError("Pinned Enterprise chart is unavailable")


def check(contract=SOURCE, remote=UPSTREAM_URL, reader_test=READER_TEST):
    revision = pinned_revision(contract)
    with tempfile.TemporaryDirectory(prefix="oce-reader-chart-") as folder:
        upstream = Path(folder) / "upstream"
        fetch_pinned_chart(upstream, revision, remote)
        subprocess.run([sys.executable, "-I", str(reader_test),
                        "--upstream-root", str(upstream)],
                       cwd=ROOT, check=True, timeout=180)


if __name__ == "__main__":
    check()
