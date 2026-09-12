#!/usr/bin/env python3
"""Prove two independent local tested-image exports agree; no registry or credentials."""
import importlib.util
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("publish", ROOT / "scripts/ci/restore-image-publish.py")
PUBLISH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISH)


def main():
    boundary = PUBLISH.load_boundary()
    expected = None
    # The harness disables Docker layer cache; the pinned base image may stay cached.
    for iteration in range(2):
        if iteration:
            # Cross a whole-second creation timestamp boundary between independent builds.
            time.sleep(2)
        with boundary.verified_image() as image, tempfile.TemporaryDirectory(prefix="restore-export-") as directory:
            layout = Path(directory) / "image"
            PUBLISH.run("skopeo", "copy", "--format", "v2s2", "--dest-compress",
                        f"docker-daemon:{image.image_id}", f"dir:{layout}")
            candidate = PUBLISH.verified_manifest(layout, image)
            print(f"Tested source {image.source_sha}: config {image.image_id}, manifest {candidate[0]}", flush=True)
            if expected is not None and candidate != expected:
                raise RuntimeError("Independent tested image exports differ")
            expected = candidate
    print(f"Independent tested schema2 exports matched: {expected[0]}")


if __name__ == "__main__":
    main()
