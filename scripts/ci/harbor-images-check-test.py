#!/usr/bin/env python3
"""One offline regression check for image aliases, nested values and stale charts."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile


spec = importlib.util.spec_from_file_location("check", Path(__file__).with_name("harbor-images-check.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
digest = "sha256:" + "a" * 64
assert check.normalize("busybox") == "docker.io/library/busybox:latest"
assert check.normalize("index.docker.io/busybox:1.38@" + digest) == "docker.io/library/busybox@" + digest
assert check.normalize("localhost:5000/example:v1") == "localhost:5000/example:v1"
assert check.normalize("tailscale/tailscale:v1") == "docker.io/tailscale/tailscale:v1"
documents = [{"initContainers": [{"image": "busybox:1.38@" + digest}],
              "operator": {"image": {"registry": "quay.io", "repository": "example/operator",
                                     "tag": "v1", "digest": digest}},
              "acmesolver": {"image": {"digest": digest}},
              "helm": {"values": "helperImage:\n  tag: v1@" + digest},
              "gateway": {"image": "auto"}}]
images, digests = check.declared_images(documents)
assert images == {"busybox:1.38@" + digest, "quay.io/example/operator:v1@" + digest}
assert digests == {digest}
with tempfile.TemporaryDirectory() as directory:
    check.ROOT = Path(directory)
    check.CATALOG = check.ROOT / "images.json"
    check.CHARTS = check.ROOT / "charts.json"
    check.CATALOG.write_text(json.dumps({"images": [
        {"source": "docker.io/library/busybox@" + digest},
        {"source": "quay.io/example/operator@" + digest}]}))
    check.CHARTS.write_text("[]")
    mirrors = {registry: {"endpoints": [f"https://harbor.stinkyboi.com/v2/mirror/{registry}"],
                          "overridePath": True, "skipFallback": True}
               for registry in ("docker.io", "quay.io")}
    check.yaml_documents = lambda paths: (
        [{"machine": {"registries": {"mirrors": mirrors}}}]
        if paths and paths[0].name == "harbor-mirrors.yaml" else documents)
    check.chart_sources = lambda: []
    with contextlib.redirect_stdout(io.StringIO()):
        check.check()
    documents[0]["initContainers"][0]["image"] = "busybox:missing"
    try:
        check.check()
    except SystemExit as error:
        assert "Unmirrored declared image: docker.io/library/busybox:missing" in str(error)
    else:
        raise AssertionError("missing image passed")
    documents.clear()
    check.CATALOG.write_text(json.dumps({"images": [
        {"source": "docker.io/library/busybox@" + digest},
        {"source": "quay.io/example/operator@" + digest},
        {"source": "mcr.microsoft.com/example/tool@" + digest}]}))
    try:
        check.check()
    except SystemExit as error:
        assert "Talos mirror endpoints must cover exactly" in str(error)
    else:
        raise AssertionError("unmirrored registry passed")
    mirrors["mcr.microsoft.com"] = {
        "endpoints": ["https://harbor.stinkyboi.com/v2/mirror/mcr.microsoft.com"],
        "overridePath": True, "skipFallback": True,
    }
    check.chart_sources = lambda: [{"chart": "new-version"}]
    try:
        check.check()
    except SystemExit as error:
        assert "Chart sources changed" in str(error)
    else:
        raise AssertionError("unreviewed chart version passed")
print("Harbor image coverage regression check passed")
