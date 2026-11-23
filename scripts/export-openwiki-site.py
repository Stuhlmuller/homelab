#!/usr/bin/env python3
"""Refresh the Argo CD OpenWiki viewer from the tracked wiki pages."""

import gzip
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "clusters/homelab/apps/openwiki/site"
ASSETS = ("index.html", "client.js", "client-lib.js", "styles.css")


def main():
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "openwiki"], cwd=ROOT
    ).decode().split("\0")

    with tempfile.TemporaryDirectory(prefix="openwiki-export-") as work:
        staging = Path(work)
        for name in tracked:
            source = ROOT / name
            if source.suffix != ".md" or not source.is_file() or source.is_symlink():
                continue
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        output = staging / "site"
        subprocess.run(
            ["openwiki", "visualize", "openwiki", "--export", str(output)],
            cwd=staging,
            check=True,
        )
        subprocess.run(
            ["git", "apply", "--no-index", "--unidiff-zero", "-p0",
             str(ROOT / "scripts/openwiki-viewer-navigation.patch")],
            cwd=output,
            check=True,
        )
        graph = json.loads((output / "graph.json").read_bytes())
        assert any(node["id"] == "quickstart" for node in graph["nodes"]), "Missing wiki quickstart"
        # Build timestamps would change the generated ConfigMap on identical inputs.
        del graph["generatedAt"]
        graph_data = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).encode()
        compressed = gzip.compress(graph_data, mtime=0)
        asset_size = sum((output / asset).stat().st_size for asset in ASSETS)
        if len(compressed) + asset_size > 1024 * 1024:
            raise ValueError("The OpenWiki site exceeds the Kubernetes ConfigMap size limit")

        for asset in ASSETS:
            (SITE / asset).write_bytes((output / asset).read_bytes().rstrip(b"\n") + b"\n")
        (SITE / "graph.json.gz").write_bytes(compressed)


if __name__ == "__main__":
    main()
