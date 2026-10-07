#!/usr/bin/env python3
"""List declared images plus supplied Helm renders and live Pod inventory.

Run in nix develop. Supply every pinned chart's `helm template` output, including
hooks, with repeated --render FILE. --pods accepts `kubectl get pods -A -o json`.
Use this before refreshing the catalog/chart snapshot; it never changes a cluster.
Operator defaults absent from both renders and existing Pods still need review.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys


spec = importlib.util.spec_from_file_location(
    "coverage", Path(__file__).with_name("ci") / "harbor-images-check.py")
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


def runtime_references(value):
    """Read controller image arguments, env values, and embedded Pod templates."""
    found = set()
    if isinstance(value, dict):
        if str(value.get("name", "")).endswith("IMAGE") and isinstance(value.get("value"), str):
            found.add(value["value"])
        for child in value.values():
            found.update(runtime_references(child))
    elif isinstance(value, list):
        for child in value:
            found.update(runtime_references(child))
    elif isinstance(value, str):
        found.update(re.findall(r"--[\w-]*(?:image|reloader)=([^\s]+)", value))
        # Only consume the value on the image line.  A multiline Helm block
        # may contain a later `tag:` line; allowing newlines here fabricated
        # docker.io/library/tag:latest entries.
        found.update(re.findall(r"(?m)^\s*image:[ \t]*[\"']?([^\s\"']+)", value))
    return {image for image in found if image != "auto"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="append", default=[], metavar="FILE")
    parser.add_argument("--pods", type=Path, help="JSON from kubectl get pods -A -o json")
    args = parser.parse_args()
    paths = sorted((coverage.ROOT / "clusters").rglob("*.yaml"))
    paths += sorted((coverage.ROOT / ".talos/patches").glob("*.yaml"))
    paths += [Path(path) for path in args.render]
    documents = coverage.yaml_documents(paths)
    if args.pods:
        documents.extend(pod["spec"] for pod in json.loads(args.pods.read_text())["items"])
    images, digests = coverage.declared_images(documents)
    images.update(runtime_references(documents))
    normalized = sorted({coverage.normalize(image) for image in images})
    unresolved = digests - {image.rsplit("@", 1)[-1] for image in normalized if "@" in image}
    if unresolved:
        print(f"{len(unresolved)} digest-only chart pins still need their chart renders", file=sys.stderr)
    print(json.dumps(normalized, indent=2))


if __name__ == "__main__":
    main()
