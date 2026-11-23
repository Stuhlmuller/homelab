"""Render Argo chart sources and reject non-Harbor effective workload images."""
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile

import hcl2
import yaml

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = "IaC/terragrunt-catalog/units/bootstrap/argocd/terragrunt.hcl"
CHART_INVENTORY = "scripts/config/harbor-image-charts.json"
CHART_PACKAGES = "scripts/config/harbor-helm-charts.json"
UPSTREAM_EXCEPTIONS = "scripts/config/harbor-rendered-upstream.json"


class ManifestLoader(yaml.SafeLoader):
    """Preserve a bare equals sign used by rendered Prometheus relabeling."""


ManifestLoader.add_constructor("tag:yaml.org,2002:value", ManifestLoader.construct_scalar)


def application_sources(spec):
    if "sources" in spec and "source" in spec:
        raise ValueError("Application declares both source and sources")
    return spec.get("sources", [spec.get("source", {})])


def chart_source(location, source):
    """Identify an Argo Helm source without losing the chart path or repository."""
    if "chart" not in source and "helm" not in source:
        return None
    repository, revision = source["repoURL"], source["targetRevision"]
    if not all(isinstance(field, str) and field and "${" not in field
               for field in (repository, revision)):
        raise ValueError(f"{location}: Helm source must pin a literal repository and revision")
    if "chart" in source:
        chart = source["chart"]
    elif repository.startswith("oci://"):
        if source.get("path") != ".":
            raise ValueError(f"{location}: OCI Helm chart must use the root path")
        repository, chart = repository.removeprefix("oci://").rsplit("/", 1)
    else:
        chart_path = source.get("path", "")
        if not chart_path or Path(chart_path).is_absolute() or ".." in Path(chart_path).parts:
            raise ValueError(f"{location}: Git Helm chart requires a repository-relative path")
        chart = "git:" + chart_path
    return {"source": str(location), "repoURL": repository, "chart": chart,
            "targetRevision": revision}


def sources(root=ROOT):
    for path in sorted((root / "IaC/homelab/us-west-2/apps").glob("*/stack.hcl")):
        for inputs in hcl2.loads(path.read_text()).get("inputs", []):
            spec = inputs.get("spec", {})
            namespace = spec.get("destination", {}).get("namespace", path.parent.name)
            for source in application_sources(spec):
                if entry := chart_source(path.relative_to(root), source):
                    yield entry, namespace, path.parent.name, source
    for path in sorted((root / "clusters").rglob("*.yaml")):
        for document in yaml.safe_load_all(path.read_text()):
            if not isinstance(document, dict) or document.get("kind") != "Application":
                continue
            spec = document["spec"]
            for source in application_sources(spec):
                if entry := chart_source(path.relative_to(root), source):
                    yield entry, spec["destination"]["namespace"], document["metadata"]["name"], source


def verify_coverage(discovered, inventory):
    """Check package coverage and reject duplicate renders of one release."""
    # The separate bootstrap image check covers the Terragrunt Helm release.
    reviewed = [tuple(sorted(entry.items())) for entry in inventory if entry["source"] != BOOTSTRAP]
    actual = [
        (tuple(sorted(entry.items())), namespace, source.get("helm", {}).get("releaseName", application))
        for entry, namespace, application, source in discovered
    ]
    if len(actual) != len(set(actual)) or len(reviewed) != len(set(reviewed)):
        raise ValueError("duplicate Argo Helm chart source")
    packages, expected = {package for package, _, _ in actual}, set(reviewed)
    if packages != expected:
        missing = [dict(entry) for entry in sorted(expected - packages)]
        unexpected = [dict(entry) for entry in sorted(packages - expected)]
        raise ValueError(f"Argo Helm source coverage differs: missing={missing}, unexpected={unexpected}")


def package_for(entry, packages, destination):
    chart, repository, revision = (entry[key] for key in ("chart", "repoURL", "targetRevision"))
    if chart.startswith("git:"):
        matches = [row for row in packages if (row["repository"], row.get("path"), row.get("revision"))
                   == (repository, chart.removeprefix("git:"), revision)]
    else:
        matches = [row for row in packages if (row["chart"], row["version"]) == (chart, revision)
                   and repository in (row["repository"], destination)]
    if len(matches) != 1:
        raise ValueError(f"{entry['source']}: no unique verified package for {repository}/{chart}@{revision}")
    return matches[0]


def render(source, package, namespace, application, workdir, env, root=ROOT):
    helm = source.get("helm", {})
    release = helm.get("releaseName", application)
    command = ["helm", "template", release, str(package), "--namespace", namespace]
    for value in helm.get("valueFiles", []):
        if not value.startswith("$values/"):
            raise ValueError(f"unsupported Helm value file source: {value}")
        relative = Path(value.removeprefix("$values/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Helm value file escapes the repository: {value}")
        command.extend(["-f", str(root / relative)])
    values = helm.get("values")
    if values is not None:
        command.extend(["-f", "-"])
    if "valuesObject" in helm:
        value_file = workdir / "values.yaml"
        value_file.write_text(yaml.safe_dump(helm["valuesObject"]))
        command.extend(["-f", str(value_file)])
    if not helm.get("skipCrds"):
        command.append("--include-crds")
    if helm.get("skipSchemaValidation"):
        command.append("--skip-schema-validation")
    if helm.get("skipTests"):
        command.append("--skip-tests")
    for parameter in helm.get("parameters", []):
        flag = "--set-string" if parameter.get("forceString") else "--set"
        command.extend([flag, parameter["name"] + "=" + parameter["value"]])
    result = subprocess.run(command, input=values, text=True, capture_output=True, env=env, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{release} render failed: {result.stderr[-1000:]}")
    return list(yaml.load_all(result.stdout, Loader=ManifestLoader))


def image_slots(value, path=()):
    """Identify workload, generated and embedded image references by their slot."""
    if isinstance(value, dict):
        name, version = value.get("image_name"), value.get("image_version")
        if isinstance(name, str) and isinstance(version, str):
            yield path + ("image_name+image_version",), f"{name}:{version}"
        if value.get("name") == "PROXY_IMAGE" and isinstance(value.get("value"), str):
            yield path + ("value",), value["value"]
        if value.get("kind") == "ConfigMap":
            data = value.get("data") or {}
            for name in ("IMAGE", "GO_IMAGE", "SKILLS_INIT_IMAGE"):
                keys = [f"{name}_{suffix}" for suffix in ("REGISTRY", "REPOSITORY", "TAG")]
                if all(isinstance(data.get(key), str) and data[key] for key in keys):
                    registry, repository, tag = (data[key] for key in keys)
                    yield path + ("data", name), f"{registry}/{repository}:{tag}"
            if isinstance(template := data.get("helperPod.yaml"), str):
                yield from image_slots(yaml.safe_load(template), path + ("data", "helperPod.yaml"))
        for key, child in value.items():
            position = path + (str(key),)
            if key == "image" and isinstance(child, str):
                yield position, child
            elif key == "args" and isinstance(child, list):
                for index, argument in enumerate(child):
                    if isinstance(argument, str) and argument.startswith("--prometheus-config-reloader="):
                        yield position + (str(index),), argument.split("=", 1)[1]
            else:
                yield from image_slots(child, position)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            name = child.get("name") if isinstance(child, dict) else None
            yield from image_slots(child, path + (name or str(index),))


def images(value):
    for _, image in image_slots(value):
        yield image


def kustomize_documents(root=ROOT):
    for path in sorted((root / "clusters/homelab").rglob("kustomization.yaml")):
        result = subprocess.run(["kustomize", "build", str(path.parent)], text=True,
                                capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"{path.relative_to(root)} render failed: {result.stderr[-1000:]}")
        for doc in yaml.load_all(result.stdout, Loader=ManifestLoader):
            if isinstance(doc, dict):
                yield path.relative_to(root), doc


def kustomize_images(root=ROOT):
    for location, doc in kustomize_documents(root):
        for image in images(doc):
            yield location, image


def image_record(location, release, namespace, document, slot, image):
    metadata = document.get("metadata", {})
    return (str(location), release, metadata.get("namespace", namespace), document["kind"],
            metadata.get("name") or metadata.get("generateName"), tuple(slot), image)


def image_policy_errors(records, reviewed_upstream):
    """Check exact workload and slot identity before allowing an upstream image."""
    if len(reviewed_upstream) != len(set(reviewed_upstream)):
        raise ValueError("duplicate upstream image exception")
    allowed = set(reviewed_upstream)
    errors = []
    for record in records:
        if pinned(record[-1]):
            continue
        if record not in allowed:
            errors.append(f"Unreviewed image: {record}")
        else:
            allowed.remove(record)
    errors.extend(f"Unused upstream exception: {record}" for record in sorted(allowed, key=str))
    return errors


def pinned(image):
    return re.fullmatch(r"harbor\.stinkyboi\.com/[^@\s]+@sha256:[0-9a-f]{64}", image) is not None


def check():
    inventory = json.loads((ROOT / CHART_INVENTORY).read_text())
    manifest = json.loads((ROOT / CHART_PACKAGES).read_text())
    reviewed = json.loads((ROOT / UPSTREAM_EXCEPTIONS).read_text())
    exceptions = [tuple(row[:5]) + (tuple(row[5]), row[6]) for row in reviewed]
    charts = list(sources())
    verify_coverage(charts, inventory)
    publisher_spec = importlib.util.spec_from_file_location(
        "harbor_chart_packages", ROOT / "scripts/ci/harbor-chart-publish.py")
    publisher = importlib.util.module_from_spec(publisher_spec)
    publisher_spec.loader.exec_module(publisher)
    packages = publisher.validate(manifest, inventory)
    records = []
    with tempfile.TemporaryDirectory(prefix="harbor-chart-render-") as directory:
        workdir = Path(directory)
        registry = workdir / "registry.json"
        registry.write_text('{"auths":{}}\n')
        env = {**os.environ, "HELM_REGISTRY_CONFIG": str(registry),
               "HELM_CACHE_HOME": str(workdir / "cache"), "HELM_CONFIG_HOME": str(workdir / "config")}
        verified = {}
        for count, (entry, namespace, application, source) in enumerate(charts, start=1):
            source_dir = workdir / str(count)
            source_dir.mkdir()
            row = package_for(entry, packages, manifest["destination"])
            package_key = row["chart"], row["version"]
            if package_key not in verified:
                verified[package_key] = publisher.upstream_package(row, source_dir, registry)
            release = source.get("helm", {}).get("releaseName", application)
            documents = render(source, verified[package_key], namespace, application, source_dir, env)
            records.extend(
                image_record(entry["source"], release, namespace, doc, slot, image)
                for doc in documents if isinstance(doc, dict)
                for slot, image in image_slots(doc)
            )
    records.extend(
        image_record(location, "", "", doc, slot, image)
        for location, doc in kustomize_documents()
        for slot, image in image_slots(doc)
    )
    failures = image_policy_errors(records, exceptions)
    if failures:
        raise AssertionError("Harbor rendered image policy failed:\n" + "\n".join(failures))
    print(f"Harbor image policy passed for {len(charts)} Argo Helm renders and {len(records)} image slots")


if __name__ == "__main__":
    check()
