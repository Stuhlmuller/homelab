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
CHARTS = ROOT / "scripts/config/harbor-image-charts.json"


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


def chart_sources():
    stack = ROOT / "IaC/terragrunt.stack.hcl"
    charts = []
    for match in re.finditer(r"\{([^{}]*\bchart\s*=[^{}]*)", stack.read_text()):
        fields = dict(re.findall(r'(repoURL|chart|targetRevision)\s*=\s*"([^\"]+)"', match[1]))
        if set(fields) != {"repoURL", "chart", "targetRevision"}:
            raise SystemExit("Stack chart sources must keep literal repoURL, chart and targetRevision "
                             "before nested options for image inventory extraction")
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


def check():
    catalog = json.loads(CATALOG.read_text())["images"]
    known = {normalize(item["source"]) for item in catalog}
    known_digests = {item.rsplit("@", 1)[-1] for item in known if "@" in item}
    # An unpinned declaration needs its reviewed tag as well as a copied digest.
    known_tags = {normalize(item["source"].split("@", 1)[0]) for item in catalog
                  if ":" in item["source"].split("@", 1)[0].rsplit("/", 1)[-1]}
    paths = sorted((ROOT / "clusters").rglob("*.yaml")) + sorted((ROOT / ".talos/patches").glob("*.yaml"))
    images, digests = declared_images(yaml_documents(paths))
    missing = sorted(normalize(image) for image in images
                     if not image.startswith("harbor.stinkyboi.com/")
                     and normalize(image) not in known | known_tags)
    missing_digests = sorted(digests - known_digests - {
        image.rsplit("@", 1)[-1] for image in images if image.startswith("harbor.stinkyboi.com/")})
    errors = [*("Unmirrored declared image: " + image for image in missing),
              *("Unmirrored declared digest: " + digest for digest in missing_digests)]
    fleet_sources = {item["source"] for item in json.loads(FLEET_CATALOG.read_text())["images"]}
    fleet_known = {normalize(image) for image in fleet_sources}
    fleet_required = {normalize(image) for image in rendered_fleet_images()}
    errors.extend("Fleet mirror scope missing rendered image: " + image
                  for image in sorted(fleet_required - fleet_known))
    errors.extend("Fleet mirror scope has unrendered image: " + image
                  for image in sorted(fleet_known - fleet_required))
    errors.extend("Fleet mirror scope source absent from full catalog: " + image
                  for image in sorted(fleet_sources - {item["source"] for item in catalog}))
    registries = {image.split("/", 1)[0] for image in known}
    expected_mirrors = {registry: {
        "endpoints": [f"https://harbor.stinkyboi.com/v2/mirror/{registry}"],
        "overridePath": True, "skipFallback": True,
    } for registry in registries}
    patch = yaml_documents([ROOT / ".talos/patches/harbor-mirrors.yaml"])[0]
    if patch["machine"]["registries"]["mirrors"] != expected_mirrors:
        errors.append("Talos mirror endpoints must cover exactly the catalog registries with overridePath and skipFallback enabled")
    if chart_sources() != json.loads(CHARTS.read_text()):
        errors.append("Chart sources changed: render the new versions, mirror their images, then refresh harbor-image-charts.json")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Harbor catalog covers {len(images)} declared image references; chart inventory matches; "
          f"Fleet scope covers exactly {len(fleet_required)} rendered images")


if __name__ == "__main__":
    if sys.argv[1:] == ["--chart-sources"]:
        print(json.dumps(chart_sources(), indent=2))
    else:
        check()
