#!/usr/bin/env python3
"""Publish reviewed Helm packages to Harbor without changing chart contents."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path



ROOT = Path(__file__).resolve().parents[2]
DESTINATION = "harbor.stinkyboi.com/mirror/helm"
MANIFEST = ROOT / "scripts/config/harbor-helm-charts.json"
SOURCES = ROOT / "scripts/config/harbor-image-charts.json"


def validate(manifest, sources):
    if set(manifest) != {"destination", "charts"} or manifest["destination"] != DESTINATION:
        raise ValueError("Harbor chart destination changed")
    charts = manifest["charts"]
    if not isinstance(charts, list) or not charts or len(charts) > 100:
        raise ValueError("Harbor chart inventory size is invalid")
    declared = {(row["chart"], row["targetRevision"], row["repoURL"]) for row in sources}
    seen = set()
    for row in charts:
        if set(row) not in ({"chart", "version", "repository", "sha256"},
                            {"chart", "version", "repository", "revision", "path", "sha256"}):
            raise ValueError("Harbor chart entry has unexpected fields")
        chart, version = row["chart"], row["version"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", chart) or not re.fullmatch(r"v?[0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?", version):
            raise ValueError("Harbor chart name or version is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) or (chart, version) in seen:
            raise ValueError("Harbor chart hash or uniqueness is invalid")
        seen.add((chart, version))
        if "revision" in row:
            if (row["repository"] != "https://github.com/rancher/local-path-provisioner.git"
                    or row["path"] != "deploy/chart/local-path-provisioner"
                    or not re.fullmatch(r"[0-9a-f]{40}", row["revision"])):
                raise ValueError("Git chart source is invalid")
            if ("git:" + row["path"], row["revision"], row["repository"]) not in declared and (chart, version, DESTINATION) not in declared:
                raise ValueError("Git chart is not in the Argo CD inventory")
        elif not (row["repository"].startswith("https://") or re.fullmatch(r"[a-z0-9.-]+(?:/[a-z0-9.-]+)+", row["repository"])):
            raise ValueError("Helm chart source is invalid")
        elif (chart, version, row["repository"]) not in declared and (chart, version, DESTINATION) not in declared:
            raise ValueError("Helm chart is not in the Argo CD inventory")
    for chart, version, repository in declared:
        if chart.startswith("git:"):
            if not any(row.get("path") == chart[4:] and row.get("revision") == version for row in charts):
                raise ValueError("Argo CD Git chart lacks a Harbor package")
        elif (chart, version) not in seen:
            raise ValueError("Argo CD chart lacks a Harbor package")
    return charts


def package_identity(package):
    with tarfile.open(package) as archive:
        names = [name for name in archive.getnames() if name.count("/") == 1 and name.endswith("/Chart.yaml")]
        if len(names) != 1:
            raise ValueError("Helm package has no unique Chart.yaml")
        metadata = archive.extractfile(names[0]).read().decode()
    fields = {}
    for key in ("name", "version"):
        values = re.findall(rf"^{key}: ['\"]?([^'\"\r\n]+)['\"]?$", metadata, re.M)
        if len(values) != 1:
            raise ValueError(f"Helm package has no unique {key}")
        fields[key] = values[0]
    return fields["name"], fields["version"]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def upstream_package(row, directory, anonymous_config):
    source = directory / "source"
    source.mkdir()
    if "revision" in row:
        checkout = directory / "checkout"
        run("git", "init", "-q", str(checkout))
        run("git", "-C", str(checkout), "fetch", "--depth=1", row["repository"], row["revision"])
        run("git", "-C", str(checkout), "checkout", "-q", "FETCH_HEAD")
        run("helm", "package", str(checkout / row["path"]), "--destination", str(source))
    elif row["repository"].startswith("https://"):
        run("helm", "pull", row["chart"], "--repo", row["repository"],
            "--version", row["version"], "--destination", str(source),
            "--repository-cache", str(directory / "cache"))
    else:
        run("helm", "pull", f"oci://{row['repository']}/{row['chart']}",
            "--version", row["version"], "--destination", str(source),
            "--registry-config", str(anonymous_config))
    packages = list(source.glob("*.tgz"))
    if len(packages) != 1:
        raise ValueError("Upstream produced an unexpected package count")
    package = packages[0]
    if package_identity(package) != (row["chart"], row["version"]):
        raise ValueError("Upstream chart identity changed")
    if hashlib.sha256(package.read_bytes()).hexdigest() != row["sha256"]:
        raise ValueError(f"Upstream chart bytes changed: {row['chart']} {row['version']}")
    return package


def publish(row, package, directory, reader_auth, reader_helm, publisher_helm):
    reference = f"{DESTINATION}/{row['chart']}:{row['version']}"
    probe = subprocess.run(["skopeo", "inspect", "--raw", "--authfile", str(reader_auth),
                            f"docker://{reference}"], capture_output=True, text=True)
    if probe.returncode:
        if not re.search(r"manifest unknown|name unknown", probe.stderr, re.I):
            raise RuntimeError(f"Harbor lookup failed for {row['chart']} {row['version']}")
        run("helm", "push", str(package), f"oci://{DESTINATION}",
            "--registry-config", str(publisher_helm))
    receipt = directory / "receipt"
    receipt.mkdir()
    run("helm", "pull", f"oci://{DESTINATION}/{row['chart']}",
        "--version", row["version"], "--destination", str(receipt),
        "--registry-config", str(reader_helm))
    packages = list(receipt.glob("*.tgz"))
    if len(packages) != 1 or hashlib.sha256(packages[0].read_bytes()).hexdigest() != row["sha256"]:
        raise ValueError(f"Harbor pull bytes differ: {row['chart']} {row['version']}")
    print(f"verified {row['chart']} {row['version']}", flush=True)


def main():
    if len(sys.argv) not in (2, 5) or sys.argv[1] not in ("--check", "--publish"):
        raise SystemExit("usage: harbor-chart-publish.py --check | --publish READER_AUTH READER_HELM PUBLISHER_HELM")
    if sys.argv[1] == "--publish" and len(sys.argv) != 5:
        raise SystemExit("--publish needs three credential file paths")
    charts = validate(json.loads(MANIFEST.read_text()), json.loads(SOURCES.read_text()))
    if sys.argv[1] == "--check":
        print(f"{len(charts)} reviewed Harbor Helm packages cover the Argo CD chart inventory")
        return
    with tempfile.TemporaryDirectory(prefix="harbor-charts-") as temporary:
        directory = Path(temporary)
        anonymous_config = directory / "anonymous-registry.json"
        anonymous_config.write_text('{"auths":{}}')
        docker_config = directory / "docker-config"
        docker_config.mkdir()
        (docker_config / "config.json").write_text('{"auths":{}}')
        os.environ["DOCKER_CONFIG"] = str(docker_config)
        for row in charts:
            chart_directory = directory / row["chart"]
            chart_directory.mkdir()
            package = upstream_package(row, chart_directory, anonymous_config)
            publish(row, package, chart_directory, *map(Path, sys.argv[2:]))


if __name__ == "__main__":
    main()
