#!/usr/bin/env python3
"""Check declared image coverage and chart inventory freshness (offline).

Chart defaults and operator-generated images require the separate rendered/live
inventory. A chart version change deliberately requires refreshing that inventory.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "scripts/config/harbor-images.json"
FLEET_CATALOG = ROOT / "scripts/config/harbor-fleet-images.json"
MASTODON_CATALOG = ROOT / "scripts/config/harbor-mastodon-images.json"
BAZARR_CATALOG = ROOT / "scripts/config/harbor-bazarr-images.json"
CHAINGUARD_CATALOG = ROOT / "scripts/config/harbor-chainguard-images.json"
HARBOR_RUNTIME_CATALOG = ROOT / "scripts/config/harbor-runtime-images.json"
CHARTS = ROOT / "scripts/config/harbor-image-charts.json"
AUTOMATION = ROOT / "clusters/homelab/apps/harbor/image-automation.json"
AUTOMATION_STATE = ROOT / "scripts/config/image-automation-state.json"
RENOVATE = ROOT / "renovate.json"
HARBOR_COMPONENTS = frozenset({
    "docker.io/goharbor/harbor-core",
    "docker.io/goharbor/harbor-exporter",
    "docker.io/goharbor/harbor-jobservice",
    "docker.io/goharbor/harbor-portal",
    "docker.io/goharbor/harbor-registryctl",
    "docker.io/goharbor/nginx-photon",
    "docker.io/goharbor/registry-photon",
    "docker.io/goharbor/trivy-adapter-photon",
    "docker.io/goharbor/valkey-photon",
})
HARBOR_RUNTIME_VERSION = "v2.15.4"


def normalize(image):
    """Docker aliases compare equally; digest pins take precedence over tags."""
    image, separator, digest = image.partition("@")
    last = image.rsplit("/", 1)[-1]
    tag = last.split(":", 1)[1] if ":" in last else "latest"
    repository = image.rsplit(":", 1)[0] if ":" in last else image
    first = repository.split("/", 1)[0]
    if "/" not in repository or ("." not in first and ":" not in first and first != "localhost"):
        repository = "docker.io/" + repository
    repository = re.sub(r"^(index\.docker\.io|registry-1\.docker\.io)/", "docker.io/", repository)
    if repository.startswith("docker.io/") and repository.count("/") == 1:
        repository = repository.replace("docker.io/", "docker.io/library/", 1)
    return repository + ("@" + digest if separator else ":" + tag)


def catalog_reference(image):
    """Compare a Harbor mirror ref with its reviewed upstream provenance."""
    return normalize(image.removeprefix("harbor.stinkyboi.com/mirror/"))


def mirror_reference(image):
    """Keep the literal Harbor repository and digest; tags do not change either."""
    repository, _, digest = image.partition("@")
    if ":" in repository.rsplit("/", 1)[-1]:
        repository = repository.rsplit(":", 1)[0]
    return repository + "@" + digest


def declared_images(value):
    """Walk manifests and chart image maps, including embedded Helm values."""
    images, digests = set(), set()
    if isinstance(value, dict):
        image = value.get("image")
        if isinstance(image, str) and image and image != "auto" and not any(c.isspace() for c in image):
            images.add(image)
        repository = value.get("repository")
        if isinstance(repository, str) and (value.get("tag") or value.get("digest")):
            image = repository
            if value.get("registry"):
                image = str(value["registry"]) + "/" + image
            if value.get("tag"):
                image += ":" + str(value["tag"])
            if value.get("digest"):
                image = image.split("@", 1)[0] + "@" + str(value["digest"])
            images.add(image)
        for child in value.values():
            found, pinned = declared_images(child)
            images.update(found)
            digests.update(pinned)
    elif isinstance(value, list):
        for child in value:
            found, pinned = declared_images(child)
            images.update(found)
            digests.update(pinned)
    elif isinstance(value, str):
        # Also covers digest-only chart defaults and embedded Helm values blocks.
        digests.update(re.findall(r"sha256:[0-9a-f]{64}(?![0-9a-f])", value))
    return images, digests


def yaml_documents(paths):
    return json.loads(subprocess.check_output(
        ["yq", "ea", "-o=json", "-I=0",
         '[., (.. | select(tag == "!!map" and has("helm")) | .helm.values | select(tag == "!!str") | from_yaml)]',
         *map(str, paths)], text=True))


def rendered_fleet_images():
    manifests = subprocess.check_output(
        ["kubectl", "kustomize", str(ROOT / "clusters/homelab/apps/fleet")], text=True)
    documents = json.loads(subprocess.check_output(
        ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=manifests, text=True))
    return declared_images(documents)[0]


def declared_bazarr_images():
    # app-template has no built-in container image. Its complete image set is
    # declared in values; the pinned Helm render is also checked before rollout.
    app = ROOT / "clusters/homelab/apps/bazarr"
    manifests = subprocess.check_output(["kubectl", "kustomize", str(app)], text=True)
    documents = json.loads(subprocess.check_output(
        ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=manifests, text=True))
    return declared_images(documents + yaml_documents([app / "values.yaml"]))[0]


def declared_mastodon_images():
    app = ROOT / "clusters/homelab/apps/mastodon"
    if app.exists():
        manifests = subprocess.check_output(["kubectl", "kustomize", str(app)], text=True)
        documents = json.loads(subprocess.check_output(
            ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=manifests, text=True))
        return declared_images(documents)[0]
    # Publication precedes its consuming workload; compare the fixed four tags
    # to the full reviewed catalog until the runtime overlay lands.
    prefixes = (
        "ghcr.io/mastodon/mastodon:v4.7.3@",
        "ghcr.io/mastodon/mastodon-streaming:v4.7.3@",
        "docker.io/library/postgres:18-bookworm@",
        "docker.io/library/redis:7.4.11-alpine@",
    )
    sources = {item["source"] for item in json.loads(CATALOG.read_text())["images"]
               if item["source"].startswith(prefixes)}
    if len(sources) != 4:
        raise RuntimeError("Mastodon publication prerequisite lacks its four reviewed runtime images")
    return sources


def chart_sources():
    charts = []
    stacks = [ROOT / "IaC/terragrunt.stack.hcl", *sorted((ROOT / "IaC/stacks").glob("*/stack.hcl"))]
    for stack in stacks:
        for match in re.finditer(r"\{([^{}]*\bchart\s*=[^{}]*)", stack.read_text()):
            fields = dict(re.findall(r'(repoURL|chart|targetRevision)\s*=\s*"([^\"]+)"', match[1]))
            if set(fields) != {"repoURL", "chart", "targetRevision"}:
                raise SystemExit(f"{stack.relative_to(ROOT)}: Stack chart sources must keep literal "
                                 "repoURL, chart and targetRevision before nested options for image inventory extraction")
            charts.append({"source": str(stack.relative_to(ROOT)), **fields})
    bootstrap = ROOT / "IaC/.catalog/units/bootstrap/argocd/terragrunt.hcl"
    fields = dict(re.findall(r'(repository|chart|chart_version)\s*=\s*"([^\"]+)"', bootstrap.read_text()))
    charts.append({"source": str(bootstrap.relative_to(ROOT)), "repoURL": fields["repository"],
                   "chart": fields["chart"], "targetRevision": fields["chart_version"]})
    for path in sorted((ROOT / "clusters").rglob("*-application.yaml")):
        for document in yaml_documents([path]):
            if not document or document.get("kind") != "Application":
                continue
            spec = document["spec"]
            for source in spec.get("sources", [spec.get("source", {})]):
                if "chart" not in source and "helm" not in source:
                    continue
                charts.append({"source": str(path.relative_to(ROOT)), "repoURL": source["repoURL"],
                               "chart": source.get("chart", "git:" + source.get("path", "")),
                               "targetRevision": source["targetRevision"]})
    return [json.loads(item) for item in sorted({json.dumps(item, sort_keys=True) for item in charts})]


def receipt_errors():
    """Enrolled Harbor consumers require an immutable verified publication receipt."""
    if not AUTOMATION.exists() or not AUTOMATION_STATE.exists():
        return []
    config = json.loads(AUTOMATION.read_text())
    state = json.loads(AUTOMATION_STATE.read_text())
    images = {item["image_id"]: item for item in config.get("images", [])}
    receipts = state.get("receipts", {})
    errors = []
    for consumer in config.get("consumers", []):
        if consumer.get("automation_status") != "enrolled":
            continue
        image = images.get(consumer.get("image_id"))
        receipt = receipts.get(consumer.get("image_id"))
        if not image or not isinstance(receipt, dict):
            errors.append(f"Enrolled image lacks publication receipt: {consumer.get('image_id')}")
            continue
        if receipt.get("destination_ref") != image["destination"] or receipt.get("consumer_access") is not True:
            errors.append(f"Enrolled image receipt lacks intended Harbor access: {consumer['image_id']}")
    return errors


def ownership_errors():
    """Image Updater targets must not also be eligible for Renovate updates."""
    if not AUTOMATION.exists() or not RENOVATE.exists():
        return []
    config = json.loads(AUTOMATION.read_text())
    renovate = json.loads(RENOVATE.read_text())
    destinations = {
        image["destination"].split("@", 1)[0].rsplit(":", 1)[0]
        for image in config.get("images", [])
        if any(consumer.get("image_id") == image.get("image_id")
               and consumer.get("automation_status") == "enrolled"
               for consumer in config.get("consumers", []))
    }
    disabled = {
        package
        for rule in renovate.get("packageRules", [])
        if rule.get("enabled") is False
        for package in rule.get("matchPackageNames", [])
    }
    return [f"Enrolled Harbor target remains Renovate-owned: {destination}"
            for destination in sorted(destinations - disabled)]


def harbor_component_errors(values, catalog):
    """Keep the coupled Harbor runtime and its mirror catalog on one version."""
    declared = {}

    def collect(value):
        if isinstance(value, dict):
            repository = value.get("repository")
            if repository in HARBOR_COMPONENTS:
                declared.setdefault(repository, []).append(value.get("tag"))
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(values)
    cataloged = {repository: [] for repository in HARBOR_COMPONENTS}
    for item in catalog:
        source = item.get("source")
        if not isinstance(source, str):
            continue
        reference = source.split("@", 1)[0]
        if ":" not in reference.rsplit("/", 1)[-1]:
            continue
        repository, _ = reference.rsplit(":", 1)
        if repository in HARBOR_COMPONENTS:
            cataloged[repository].append(source)

    errors = []
    tag_pattern = re.compile(rf"{re.escape(HARBOR_RUNTIME_VERSION)}@sha256:[0-9a-f]{{64}}$")
    for repository in sorted(HARBOR_COMPONENTS):
        tags = declared.get(repository, [])
        if len(tags) != 1:
            errors.append(f"Harbor values must declare exactly one image for {repository}")
            continue
        tag = tags[0]
        if not isinstance(tag, str) or not tag_pattern.fullmatch(tag):
            errors.append(f"Harbor component {repository} must use {HARBOR_RUNTIME_VERSION}@sha256:<digest>")
            continue
        expected = f"{repository}:{tag}"
        if expected not in cataloged[repository]:
            errors.append(f"Harbor catalog must contain the same {HARBOR_RUNTIME_VERSION} source as values for {repository}")
    return errors


def check_harbor_components():
    values = yaml_documents([ROOT / "clusters/homelab/apps/harbor/values.yaml"])
    errors = harbor_component_errors(values[0], json.loads(CATALOG.read_text())["images"])
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Harbor coupled runtime: {len(HARBOR_COMPONENTS)} components pinned to {HARBOR_RUNTIME_VERSION}")


def check():
    catalog = json.loads(CATALOG.read_text())["images"]
    known = {normalize(item["source"]) for item in catalog}
    known_mirrors = {mirror_reference("harbor.stinkyboi.com/mirror/" + item["source"])
                     for item in catalog}
    known_digests = {item.rsplit("@", 1)[-1] for item in known if "@" in item}
    # An unpinned declaration needs its reviewed tag as well as a copied digest.
    known_tags = {normalize(item["source"].split("@", 1)[0]) for item in catalog
                  if ":" in item["source"].split("@", 1)[0].rsplit("/", 1)[-1]}
    paths = sorted((ROOT / "clusters").rglob("*.yaml")) + sorted((ROOT / ".talos/patches").glob("*.yaml"))
    images, digests = declared_images(yaml_documents(paths))
    # Direct Harbor mirror references must retain the reviewed digest. Upstream
    # provenance refs may use a reviewed tag because Talos resolves them through
    # the strict Harbor mirror path.
    missing = sorted(normalize(image) for image in images
                     if not image.startswith("harbor.stinkyboi.com/homelab/")
                     and (mirror_reference(image) not in known_mirrors
                          if image.startswith("harbor.stinkyboi.com/mirror/")
                          else catalog_reference(image) not in known | known_tags))
    missing_digests = sorted(digests - known_digests - {
        image.rsplit("@", 1)[-1] for image in images if image.startswith("harbor.stinkyboi.com/homelab/")})
    errors = [*("Unmirrored declared image: " + image for image in missing),
              *("Unmirrored declared digest: " + digest for digest in missing_digests)]
    errors.extend(receipt_errors())
    errors.extend(ownership_errors())
    scope_counts = {}
    harbor_runtime = {item["source"] for item in catalog
                      if item["source"].startswith("docker.io/goharbor/")
                      and ":v2.15.4@" in item["source"]}
    if len(harbor_runtime) != 9:
        errors.append("Harbor 2.15.4 runtime publication requires nine component digests")
    for name, path, required_images in (
        ("Fleet", FLEET_CATALOG, rendered_fleet_images()),
        ("Bazarr", BAZARR_CATALOG, declared_bazarr_images()),
        ("Mastodon", MASTODON_CATALOG, declared_mastodon_images()),
        ("Chainguard", CHAINGUARD_CATALOG,
         {item["source"] for item in catalog if item["source"].startswith("cgr.dev/chainguard/")}),
        ("Harbor", HARBOR_RUNTIME_CATALOG, harbor_runtime),
    ):
        sources = {item["source"] for item in json.loads(path.read_text())["images"]}
        known_scope = {normalize(image) for image in sources}
        required = {catalog_reference(image) for image in required_images}
        errors.extend(f"{name} mirror scope missing required image: " + image
                      for image in sorted(required - known_scope))
        errors.extend(f"{name} mirror scope has unused image: " + image
                      for image in sorted(known_scope - required))
        errors.extend(f"{name} mirror scope source absent from full catalog: " + image
                      for image in sorted(sources - {item["source"] for item in catalog}))
        scope_counts[name] = len(required)
    registries = {image.split("/", 1)[0] for image in known}
    expected_mirrors = {registry: {
        "endpoints": [f"https://harbor.stinkyboi.com/v2/mirror/{registry}"],
        "overridePath": True, "skipFallback": True,
    } for registry in registries}
    patch = yaml_documents([ROOT / ".talos/patches/harbor-mirrors.yaml"])[0]
    registry_config = patch["machine"]["registries"]
    if "config" in registry_config:
        errors.append("Talos Harbor mirror patch must not contain registry authentication")
    if registry_config["mirrors"] != expected_mirrors:
        errors.append("Talos mirror endpoints must cover exactly the catalog registries with overridePath and skipFallback enabled")
    if chart_sources() != json.loads(CHARTS.read_text()):
        errors.append("Chart sources changed: render the new versions, mirror their images, then refresh harbor-image-charts.json")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Harbor catalog covers {len(images)} declared image references; chart inventory matches; "
          f"fixed app scopes match required images: {scope_counts}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--chart-sources"]:
        print(json.dumps(chart_sources(), indent=2))
    elif sys.argv[1:] == ["--harbor-components"]:
        check_harbor_components()
    else:
        check()
