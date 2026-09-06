#!/usr/bin/env python3
"""Prove two independent local tested-image exports agree; no registry or credentials."""
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("publish", ROOT / "scripts/ci/restore-image-publish.py")
PUBLISH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISH)


def main():
    boundary = PUBLISH.load_boundary()
    expected = None
    # Force a second build in a separate temporary context; image tags are removed between runs.
    for _ in range(2):
        with boundary.verified_image() as image, tempfile.TemporaryDirectory(prefix="restore-export-") as directory:
            layout = Path(directory) / "oci"
            PUBLISH.run("skopeo", "copy", f"docker-daemon:{image.tag}", f"oci:{layout}:candidate")
            candidate = PUBLISH.verified_manifest(layout, image)
            if expected is not None and candidate != expected:
                raise RuntimeError("Independent tested image exports differ")
            expected = candidate
    print(f"Independent tested OCI exports matched: {expected[0]}")


if __name__ == "__main__":
    main()
