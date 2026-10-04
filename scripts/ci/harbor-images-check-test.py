#!/usr/bin/env python3
"""One offline regression check for image aliases, nested values and stale charts."""

import contextlib
import importlib.util
import io
import json
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("check", Path(__file__).with_name("harbor-images-check.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
# Shared stack defaults and sparse sources must not hide chart upgrades from
# the image inventory gate. A chart needs no Helm overrides to deploy.
with tempfile.TemporaryDirectory() as directory:
    original_root = check.ROOT
    check.ROOT = Path(directory)
    stack = check.ROOT / "IaC/terragrunt.stack.hcl"
    stack.parent.mkdir()
    bootstrap = check.ROOT / "IaC/.catalog/units/bootstrap/argocd/terragrunt.hcl"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text('repository = "https://bootstrap.example.invalid"\n'
                         'chart = "argo-cd"\nchart_version = "1.0.0"\n')
    source = '{ repoURL = "https://charts.example.invalid", chart = "example", targetRevision = "2.0.0" }'
    stack.write_text('locals { defaults = { project = "homelab" } }\n'
                     'unit "app" { values = { defaults = local.defaults, spec = { sources = [' + source + '] } } }')
    expected = {"source": "IaC/terragrunt.stack.hcl", "repoURL": "https://charts.example.invalid",
                "chart": "example", "targetRevision": "2.0.0"}
    assert expected in check.chart_sources()
    stack.write_text(stack.read_text().replace('"2.0.0"', '"2.1.0"'))
    assert expected not in check.chart_sources()
    assert {**expected, "targetRevision": "2.1.0"} in check.chart_sources()
    stack.write_text(stack.read_text().replace('"2.1.0"', 'local.hidden_version'))
    try:
        check.chart_sources()
    except SystemExit as error:
        assert "literal repoURL, chart and targetRevision" in str(error)
    else:
        raise AssertionError("A chart omitted from inventory extraction passed")
    check.ROOT = original_root

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
    check.FLEET_CATALOG = check.ROOT / "fleet-images.json"
    check.CHARTS = check.ROOT / "charts.json"
    catalog = {"images": [
        {"source": "docker.io/library/busybox@" + digest},
        {"source": "quay.io/example/operator@" + digest}]}
    check.CATALOG.write_text(json.dumps(catalog))
    check.FLEET_CATALOG.write_text(json.dumps(catalog))
    check.rendered_fleet_images = lambda: images
    check.CHARTS.write_text("[]")
    mirrors = {registry: {"endpoints": [f"https://harbor.stinkyboi.com/v2/mirror/{registry}"],
                          "overridePath": True, "skipFallback": True}
               for registry in ("docker.io", "quay.io")}
    check.yaml_documents = lambda paths: (
        [{"machine": {"registries": {"mirrors": mirrors}}}]
        if paths and paths[0].name == "harbor-mirrors.yaml" else documents)
    check.chart_sources = list
    with contextlib.redirect_stdout(io.StringIO()):
        check.check()
    check.FLEET_CATALOG.write_text(json.dumps({"images": catalog["images"][:1]}))
    try:
        check.check()
    except SystemExit as error:
        assert "Fleet mirror scope missing rendered image: quay.io/example/operator@" in str(error)
    else:
        raise AssertionError("Fleet scope missing a rendered image passed")
    extra = {"source": "docker.io/library/busybox@sha256:" + "b" * 64}
    expanded = {"images": [*catalog["images"], extra]}
    check.CATALOG.write_text(json.dumps(expanded))
    check.FLEET_CATALOG.write_text(json.dumps(expanded))
    try:
        check.check()
    except SystemExit as error:
        assert "Fleet mirror scope has unrendered image: " + extra["source"] in str(error)
    else:
        raise AssertionError("Fleet scope extra catalog digest passed")
    check.CATALOG.write_text(json.dumps(catalog))
    try:
        check.check()
    except SystemExit as error:
        assert "Fleet mirror scope source absent from full catalog: " + extra["source"] in str(error)
    else:
        raise AssertionError("Fleet scope source absent from the full catalog passed")
    check.FLEET_CATALOG.write_text(json.dumps(catalog))
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
