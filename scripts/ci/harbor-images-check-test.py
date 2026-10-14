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

# App inputs retain their own provenance, even when apps share a chart/version.
with tempfile.TemporaryDirectory() as directory:
    original_root = check.ROOT
    check.ROOT = Path(directory)
    stack = check.ROOT / "IaC/terragrunt.stack.hcl"
    stack.parent.mkdir()
    stack.write_text('unit "app" { values = read_terragrunt_config("stacks/app/stack.hcl").inputs }')
    bootstrap = check.ROOT / "IaC/.catalog/units/bootstrap/argocd/terragrunt.hcl"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text('repository = "https://bootstrap.example.invalid"\n'
                         'chart = "argo-cd"\nchart_version = "1.0.0"\n')
    source = '{ repoURL = "https://charts.example.invalid", chart = "example", targetRevision = "2.0.0" }'
    for app in ("beta", "alpha"):
        path = check.ROOT / f"IaC/stacks/{app}/stack.hcl"
        path.parent.mkdir(parents=True)
        path.write_text('inputs = { defaults = local.defaults, spec = { sources = [' + source + '] } }')
    expected = [{"source": f"IaC/stacks/{app}/stack.hcl", "repoURL": "https://charts.example.invalid",
                 "chart": "example", "targetRevision": "2.0.0"} for app in ("alpha", "beta")]
    for ignored in ("IaC/live/argocd-apps/alpha/stack.hcl",
                    "IaC/stacks/alpha/.terragrunt-cache/generated/stack.hcl"):
        path = check.ROOT / ignored
        path.parent.mkdir(parents=True)
        path.write_text('inputs = { spec = { sources = [' + source + '] } }')
    assert [item for item in check.chart_sources() if item["chart"] == "example"] == expected
    alpha = check.ROOT / "IaC/stacks/alpha/stack.hcl"
    alpha.write_text(alpha.read_text().replace('"2.0.0"', '"2.1.0"'))
    assert expected[0] not in check.chart_sources()
    assert {**expected[0], "targetRevision": "2.1.0"} in check.chart_sources()
    assert expected[1] in check.chart_sources()
    valid = alpha.read_text()
    for field, value in (("repoURL", "https://charts.example.invalid"), ("chart", "example"),
                         ("targetRevision", "2.1.0")):
        alpha.write_text(valid.replace(f'"{value}"', f"local.hidden_{field}"))
        try:
            check.chart_sources()
        except SystemExit as error:
            assert "IaC/stacks/alpha/stack.hcl" in str(error)
            assert "literal repoURL, chart and targetRevision" in str(error)
        else:
            raise AssertionError(f"A nonliteral split-stack {field} passed")
    check.ROOT = original_root

digest = "sha256:" + "a" * 64
assert check.normalize("busybox") == "docker.io/library/busybox:latest"
assert check.normalize("index.docker.io/busybox:1.38@" + digest) == "docker.io/library/busybox@" + digest
assert check.normalize("localhost:5000/example:v1") == "localhost:5000/example:v1"
assert check.normalize("tailscale/tailscale:v1") == "docker.io/tailscale/tailscale:v1"
inventory_spec = importlib.util.spec_from_file_location("inventory", Path(__file__).parents[1] / "harbor-image-inventory.py")
inventory = importlib.util.module_from_spec(inventory_spec)
inventory_spec.loader.exec_module(inventory)
assert inventory.runtime_references([{"helm": {"values": "image:\n  repository: docker.io/example\n  tag: latest"}}]) == set()
assert inventory.runtime_references([{"helm": {"values": "image: docker.io/example:latest\ntag: ignored"}}]) == {"docker.io/example:latest"}
documents = [{"initContainers": [{"image": "busybox:1.38@" + digest}],
              "operator": {"image": {"registry": "quay.io", "repository": "example/operator",
                                     "tag": "v1", "digest": digest}},
              "acmesolver": {"image": {"digest": digest}},
              "helm": {"values": "helperImage:\n  tag: v1@" + digest},
              "gateway": {"image": "auto"}}]
images, digests = check.declared_images(documents)
assert images == {"busybox:1.38@" + digest, "quay.io/example/operator:v1@" + digest}
assert digests == {digest}

# Coupled Harbor components must stay on one runtime version and match the
# publication catalog; a single Renovate-style component bump is unsafe.
harbor_tag = "v2.15.4@" + digest
harbor_values = {"images": [
    {"repository": repository, "tag": harbor_tag}
    for repository in sorted(check.HARBOR_COMPONENTS)
]}
harbor_catalog = [
    {"source": f"{repository}:{harbor_tag}"}
    for repository in sorted(check.HARBOR_COMPONENTS)
]
assert check.harbor_component_errors(harbor_values, harbor_catalog) == []
mixed_values = {"images": [*harbor_values["images"]]}
mixed_values["images"][0] = {**mixed_values["images"][0], "tag": "v2.15.2@" + digest}
assert any("must use v2.15.4" in error
           for error in check.harbor_component_errors(mixed_values, harbor_catalog))
assert any("Harbor catalog" in error
           for error in check.harbor_component_errors(harbor_values, harbor_catalog[1:]))

# Before its consumer lands, the Mastodon scope still requires all four tags.
with tempfile.TemporaryDirectory() as directory:
    root, catalog_path = check.ROOT, check.CATALOG
    check.ROOT = Path(directory)
    check.CATALOG = check.ROOT / "mastodon-full.json"
    sources = [prefix + digest for prefix in (
        "ghcr.io/mastodon/mastodon:v4.7.3@",
        "ghcr.io/mastodon/mastodon-streaming:v4.7.3@",
        "docker.io/library/postgres:18-bookworm@",
        "docker.io/library/redis:7.4.11-alpine@",
    )]
    check.CATALOG.write_text(json.dumps({"images": [{"source": source} for source in sources]}))
    assert check.declared_mastodon_images() == set(sources)
    check.CATALOG.write_text(json.dumps({"images": [{"source": source} for source in sources[:-1]]}))
    try:
        check.declared_mastodon_images()
        raise AssertionError("Incomplete Mastodon prerequisite passed")
    except RuntimeError:
        pass
    check.ROOT, check.CATALOG = root, catalog_path

with tempfile.TemporaryDirectory() as directory:
    check.ROOT = Path(directory)
    check.CATALOG = check.ROOT / "images.json"
    check.FLEET_CATALOG = check.ROOT / "fleet-images.json"
    check.BAZARR_CATALOG = check.ROOT / "bazarr-images.json"
    check.MASTODON_CATALOG = check.ROOT / "mastodon-images.json"
    check.CHAINGUARD_CATALOG = check.ROOT / "chainguard-images.json"
    check.HARBOR_RUNTIME_CATALOG = check.ROOT / "harbor-runtime-images.json"
    runtime_images = json.loads((original_root / "scripts/config/harbor-runtime-images.json").read_text())["images"]
    check.HARBOR_RUNTIME_CATALOG.write_text(json.dumps({"images": runtime_images}))
    check.CHAINGUARD_CATALOG.write_text(json.dumps({"images": []}))
    check.CHARTS = check.ROOT / "charts.json"
    base_catalog = {"images": [
        {"source": "docker.io/library/busybox:1.38@" + digest},
        {"source": "quay.io/example/operator@" + digest}]}
    catalog = {"images": [*base_catalog["images"], *runtime_images]}
    check.CATALOG.write_text(json.dumps(catalog))
    check.FLEET_CATALOG.write_text(json.dumps(base_catalog))
    check.BAZARR_CATALOG.write_text(json.dumps(base_catalog))
    check.MASTODON_CATALOG.write_text(json.dumps(base_catalog))
    check.declared_mastodon_images = lambda: images
    check.rendered_fleet_images = lambda: images
    check.declared_bazarr_images = lambda: images
    check.CHARTS.write_text("[]")
    mirrors = {registry: {"endpoints": [f"https://harbor.stinkyboi.com/v2/mirror/{registry}"],
                          "overridePath": True, "skipFallback": True}
               for registry in ("docker.io", "quay.io")}
    mirror_patch = {"machine": {"registries": {"mirrors": mirrors}}}
    check.yaml_documents = lambda paths: (
        [mirror_patch] if paths and paths[0].name == "harbor-mirrors.yaml" else documents)
    check.chart_sources = list
    with contextlib.redirect_stdout(io.StringIO()):
        check.check()
    original_image = documents[0]["initContainers"][0]["image"]
    documents[0]["initContainers"][0]["image"] = "busybox:1.38"
    with contextlib.redirect_stdout(io.StringIO()):
        check.check()
    documents[0]["initContainers"][0]["image"] = (
        "harbor.stinkyboi.com/mirror/docker.io/library/busybox:1.38@" + digest)
    with contextlib.redirect_stdout(io.StringIO()):
        check.check()
    documents[0]["initContainers"][0]["image"] = (
        "harbor.stinkyboi.com/mirror/docker.io/library/busybox@" + digest)
    with contextlib.redirect_stdout(io.StringIO()):
        check.check()
    documents[0]["initContainers"][0]["image"] = (
        "harbor.stinkyboi.com/mirror/docker.io/busybox:1.38@" + digest)
    try:
        check.check()
    except SystemExit as error:
        assert "Unmirrored declared image: harbor.stinkyboi.com/mirror/" in str(error)
    else:
        raise AssertionError("Unpublished Docker Hub shorthand mirror path passed")
    documents[0]["initContainers"][0]["image"] = (
        "harbor.stinkyboi.com/mirror/docker.io/library/busybox:1.38")
    try:
        check.check()
    except SystemExit as error:
        assert "Unmirrored declared image: harbor.stinkyboi.com/mirror/" in str(error)
    else:
        raise AssertionError("Digestless Harbor mirror tag passed")
    documents[0]["initContainers"][0]["image"] = (
        "harbor.stinkyboi.com/mirror/docker.io/library/unreviewed:1@" + digest)
    try:
        check.check()
    except SystemExit as error:
        assert "Unmirrored declared image: harbor.stinkyboi.com/mirror/" in str(error)
    else:
        raise AssertionError("Internal image with unreviewed source repository passed")
    documents[0]["initContainers"][0]["image"] = (
        "harbor.stinkyboi.com/homelab/private-tool:latest")
    with contextlib.redirect_stdout(io.StringIO()):
        check.check()
    documents[0]["initContainers"][0]["image"] = original_image
    check.MASTODON_CATALOG.write_text(json.dumps({"images": catalog["images"][:1]}))
    try:
        check.check()
        raise AssertionError("Mastodon scope missing a required image passed")
    except SystemExit as error:
        assert "Mastodon mirror scope missing required image: " in str(error)
    check.MASTODON_CATALOG.write_text(json.dumps({"images": [*catalog["images"],
        {"source": "docker.io/library/busybox@sha256:" + "b" * 64}]}))
    try:
        check.check()
        raise AssertionError("Mastodon scope included an unused/unreviewed image")
    except SystemExit as error:
        assert "Mastodon mirror scope has unused image: " in str(error)
        assert "Mastodon mirror scope source absent from full catalog: " in str(error)
    check.MASTODON_CATALOG.write_text(json.dumps(catalog))
    mirror_patch["machine"]["registries"]["config"] = {}
    try:
        check.check()
    except SystemExit as error:
        assert "Talos Harbor mirror patch must not contain registry authentication" in str(error)
    else:
        raise AssertionError("committed Talos registry config passed")
    mirror_patch["machine"]["registries"].pop("config")
    check.FLEET_CATALOG.write_text(json.dumps({"images": catalog["images"][:1]}))
    try:
        check.check()
    except SystemExit as error:
        assert "Fleet mirror scope missing required image: quay.io/example/operator@" in str(error)
    else:
        raise AssertionError("Fleet scope missing a rendered image passed")
    extra = {"source": "docker.io/library/busybox@sha256:" + "b" * 64}
    expanded = {"images": [*catalog["images"], extra]}
    check.CATALOG.write_text(json.dumps(expanded))
    check.FLEET_CATALOG.write_text(json.dumps(expanded))
    try:
        check.check()
    except SystemExit as error:
        assert "Fleet mirror scope has unused image: " + extra["source"] in str(error)
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
    check.BAZARR_CATALOG.write_text(json.dumps({"images": catalog["images"][:1]}))
    try:
        check.check()
    except SystemExit as error:
        assert "Bazarr mirror scope missing required image: quay.io/example/operator@" in str(error)
    else:
        raise AssertionError("Bazarr scope missing a rendered image passed")
    extra = {"source": "docker.io/library/busybox@sha256:" + "b" * 64}
    expanded = {"images": [*catalog["images"], extra]}
    check.CATALOG.write_text(json.dumps(expanded))
    check.BAZARR_CATALOG.write_text(json.dumps(expanded))
    try:
        check.check()
    except SystemExit as error:
        assert "Bazarr mirror scope has unused image: " + extra["source"] in str(error)
    else:
        raise AssertionError("Bazarr scope extra catalog digest passed")
    check.CATALOG.write_text(json.dumps(catalog))
    try:
        check.check()
    except SystemExit as error:
        assert "Bazarr mirror scope source absent from full catalog: " + extra["source"] in str(error)
    else:
        raise AssertionError("Bazarr scope source absent from the full catalog passed")
    check.BAZARR_CATALOG.write_text(json.dumps(catalog))
    unreviewed = {"source": "cgr.dev/chainguard/python:latest@sha256:" + "c" * 64}
    check.CHAINGUARD_CATALOG.write_text(json.dumps({"images": [unreviewed]}))
    try:
        check.check()
    except SystemExit as error:
        assert "Chainguard mirror scope source absent from full catalog" in str(error)
    else:
        raise AssertionError("Unreviewed Chainguard publication scope passed")
    check.CHAINGUARD_CATALOG.write_text(json.dumps({"images": []}))
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

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    original_automation = check.AUTOMATION
    original_state = check.AUTOMATION_STATE
    original_renovate = check.RENOVATE
    check.AUTOMATION = root / "image-automation.json"
    check.AUTOMATION_STATE = root / "image-automation-state.json"
    check.RENOVATE = root / "renovate.json"
    config = {"images": [{"image_id": "pilot", "destination": "harbor.stinkyboi.com/homelab/pilot:latest"}],
              "consumers": [{"image_id": "pilot", "automation_status": "enrolled"}]}
    check.AUTOMATION.write_text(json.dumps(config))
    check.AUTOMATION_STATE.write_text(json.dumps({"receipts": {}}))
    assert check.receipt_errors()
    check.AUTOMATION_STATE.write_text(json.dumps({"receipts": {"pilot": {
        "destination_ref": "harbor.stinkyboi.com/homelab/pilot:latest", "consumer_access": True}}}))
    assert check.receipt_errors() == []
    check.RENOVATE.write_text(json.dumps({"packageRules": [{
        "matchPackageNames": ["harbor.stinkyboi.com/homelab/pilot"],
        "enabled": False}]}))
    assert check.ownership_errors() == []
    check.RENOVATE.write_text(json.dumps({"packageRules": []}))
    assert check.ownership_errors()
    check.AUTOMATION = original_automation
    check.AUTOMATION_STATE = original_state
    check.RENOVATE = original_renovate
print("Harbor image coverage regression check passed")
