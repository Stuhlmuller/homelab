#!/usr/bin/env python3
"""Small offline checks for the reviewed chart publication contract."""

import importlib.util
import io
import json
import tarfile
import tempfile
from pathlib import Path


script = Path(__file__).with_name("harbor-chart-publish.py")
spec = importlib.util.spec_from_file_location("harbor_chart_publish", script)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
manifest = json.loads(publisher.MANIFEST.read_text())
sources = json.loads(publisher.SOURCES.read_text())
assert len(publisher.validate(manifest, sources)) == 28

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

print("Harbor chart publication contract passed")
