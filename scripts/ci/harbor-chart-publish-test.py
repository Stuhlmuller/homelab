#!/usr/bin/env python3
"""Small offline checks for the reviewed chart publication contract."""

import gzip
import importlib.util
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path


script = Path(__file__).with_name("harbor-chart-publish.py")
spec = importlib.util.spec_from_file_location("harbor_chart_publish", script)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
manifest = json.loads(publisher.MANIFEST.read_text())
sources = json.loads(publisher.SOURCES.read_text())
assert publisher.validate(manifest, sources) == manifest["charts"]
missing = {**manifest, "charts": manifest["charts"][1:]}
try:
    publisher.validate(missing, sources)
except ValueError as error:
    assert "Argo CD chart lacks a Harbor package" in str(error)
else:
    raise AssertionError("missing chart package was accepted")

assert publisher.missing_harbor_artifact(
    "unknown: repository mirror/helm/example not found", "example")
assert not publisher.missing_harbor_artifact(
    "unknown: repository mirror/helm/other not found", "example")
assert not publisher.missing_harbor_artifact("unauthorized: authentication required", "example")

def fixture_package(path, timestamp, payload):
    files = {"test/Chart.yaml": b"apiVersion: v2\nname: test\nversion: 1.2.3\n",
             "test/templates/deployment.yaml": payload}
    with path.open("wb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", filename=path.name, mtime=timestamp) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for name, contents in files.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(contents)
                    info.mtime = timestamp
                    archive.addfile(info, io.BytesIO(contents))
    return files


with tempfile.TemporaryDirectory() as temporary:
    first, second, changed = (Path(temporary) / f"{name}.tgz" for name in ("first", "second", "changed"))
    template = b"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}\n"
    expected = fixture_package(first, 100, template)
    fixture_package(second, 200, template)
    fixture_package(changed, 200, template.replace(b".Release.Name", b".Chart.Name"))
    assert first.read_bytes() != second.read_bytes()
    rendered = subprocess.check_output(["helm", "template", "chart-test", str(first)])
    assert publisher.package_identity(first) == ("test", "1.2.3")
    for package in (first, second, changed):
        publisher.normalize_git_package(package)
    assert first.read_bytes() == second.read_bytes()
    assert rendered == subprocess.check_output(["helm", "template", "chart-test", str(second)])
    assert first.read_bytes() != changed.read_bytes()
    assert publisher.package_identity(first) == ("test", "1.2.3")
    with tarfile.open(first) as archive:
        assert [member.name for member in archive] == list(expected)
        assert all(member.mtime == 0 for member in archive.getmembers())
        assert {member.name: archive.extractfile(member).read() for member in archive.getmembers()} == expected

duplicate = {**manifest, "charts": manifest["charts"] + [manifest["charts"][0]]}
try:
    publisher.validate(duplicate, sources)
except ValueError:
    pass
else:
    raise AssertionError("duplicate chart package was accepted")

print("Harbor chart publication contract passed")
