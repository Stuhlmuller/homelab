#!/usr/bin/env python3
"""Small offline checks for the reviewed chart publication contract."""

import importlib.util
import io
import json
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


script = Path(__file__).with_name("harbor-chart-publish.py")
spec = importlib.util.spec_from_file_location("harbor_chart_publish", script)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
manifest = json.loads(publisher.MANIFEST.read_text())
sources = json.loads(publisher.SOURCES.read_text())
assert len(publisher.validate(manifest, sources)) == 28
istio = json.loads(publisher.ISTIO_UPGRADE_MANIFEST.read_text())
assert [row["chart"] for row in publisher.validate_istio_upgrade(istio)] == [
    "base", "cni", "gateway", "istiod", "ztunnel"]
assert publisher.missing_harbor_artifact(
    "unknown: repository mirror/helm/example not found", "example")
assert not publisher.missing_harbor_artifact(
    "unknown: repository mirror/helm/other not found", "example")
assert not publisher.missing_harbor_artifact("unauthorized: authentication required", "example")

with tempfile.TemporaryDirectory() as temporary:
    package = Path(temporary) / "test.tgz"
    metadata = b"apiVersion: v2\nname: test\nversion: 1.2.3\n"
    with tarfile.open(package, "w:gz") as archive:
        info = tarfile.TarInfo("test/Chart.yaml")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
    assert publisher.package_identity(package) == ("test", "1.2.3")

duplicate = {**manifest, "charts": manifest["charts"] + [manifest["charts"][0]]}
try:
    publisher.validate(duplicate, sources)
except ValueError:
    pass
else:
    raise AssertionError("duplicate chart package was accepted")

for changed in (
        {**istio, "destination": "harbor.stinkyboi.com/homelab/helm"},
        {**istio, "charts": istio["charts"][:-1]},
        {**istio, "charts": istio["charts"] + [istio["charts"][0]]},
        {**istio, "charts": [{**istio["charts"][0], "repository": "https://unreviewed.example/charts"}]
         + istio["charts"][1:]},
        {**istio, "charts": [{**istio["charts"][0], "version": "1.28.11"}]
         + istio["charts"][1:]},
        {**istio, "charts": [{**istio["charts"][0], "sha256": "unknown"}]
         + istio["charts"][1:]},
):
    try:
        publisher.validate_istio_upgrade(changed)
    except ValueError:
        pass
    else:
        raise AssertionError("unreviewed Istio upgrade inventory was accepted")

manifest_bytes = json.dumps({
    "schemaVersion": 2,
    "config": {"mediaType": "application/vnd.cncf.helm.config.v1+json"},
    "layers": [{"mediaType": "application/vnd.cncf.helm.chart.content.v1.tar+gzip",
                "digest": "sha256:" + "a" * 64}],
}).encode()
with mock.patch.object(publisher.subprocess, "run", return_value=SimpleNamespace(stdout=manifest_bytes)):
    assert publisher.verified_manifest_digest("harbor.stinkyboi.com/mirror/helm/base:1.28.10",
                                              "a" * 64, Path("reader.json")) == (
        "sha256:" + publisher.hashlib.sha256(manifest_bytes).hexdigest())
    try:
        publisher.verified_manifest_digest("harbor.stinkyboi.com/mirror/helm/base:1.28.10",
                                           "b" * 64, Path("reader.json"))
    except ValueError:
        pass
    else:
        raise AssertionError("manifest with mismatched chart layer was accepted")

project = (publisher.ROOT / "clusters/homelab/argocd/self-management/appproject.yaml").read_text()
oci_urls = {line.strip().removeprefix("- ") for line in project.splitlines()
            if line.strip().startswith("- oci://harbor.stinkyboi.com")}
assert oci_urls == {f"oci://{publisher.DESTINATION}/{chart}" for chart in publisher.ISTIO_UPGRADE_CHARTS}
secret = (publisher.ROOT / "clusters/homelab/argocd/self-management/harbor-istio-oci-external-secret.yaml").read_text()
for expected in (
        "name: aws-ssm", "argocd.argoproj.io/secret-type: repo-creds",
        f"url: oci://{publisher.DESTINATION}", "type: oci", "project: homelab",
        "username: robot$mirror+pull", 'password: "{{ .password }}"',
        "key: /homelab/harbor/mirror-robot-pull-password"):
    assert expected in secret
resources = (publisher.ROOT / "clusters/homelab/argocd/self-management/kustomization.yaml").read_text()
assert "  - harbor-istio-oci-external-secret.yaml" in resources

workflow = (publisher.ROOT / ".github/workflows/harbor-helm-charts.yml").read_text()
assert workflow.index("name: Verify Current Main Before Credentials") < workflow.index("name: Configure AWS Credentials")
assert "git ls-remote https://github.com/Stuhlmuller/homelab.git refs/heads/main" in workflow
assert "--check-istio-1.28.10" in workflow
assert "Upload Istio Chart Digest Receipt" in workflow
assert "if-no-files-found: error" in workflow

print("Harbor chart publication contract passed")
