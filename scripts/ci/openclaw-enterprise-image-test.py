#!/usr/bin/env python3
"""Check that Enterprise images and CLI build only from the pinned stock source."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
REVISION = "33bb74590a749f37934da4502fca6035cd234a55"


class ImageBuildTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oce-image-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "builds/openclaw-enterprise").mkdir(parents=True)
        (self.root / "scripts/config").mkdir(parents=True)
        (self.root / "bin").mkdir()
        shutil.copyfile(ROOT / "builds/openclaw-enterprise/build.sh",
                        self.root / "builds/openclaw-enterprise/build.sh")
        shutil.copyfile(ROOT / "builds/openclaw-enterprise/occ.Dockerfile",
                        self.root / "builds/openclaw-enterprise/occ.Dockerfile")
        contract = json.loads((ROOT / "builds/openclaw-enterprise/source.json").read_text())
        cli_bytes = b"fixture occ binary"
        contract["cliBinarySha256"] = hashlib.sha256(cli_bytes).hexdigest()
        self.archive = self.root / "source.tar.gz"
        with tarfile.open(self.archive, "w:gz") as archive:
            files = {
                "Dockerfile": b"FROM scratch\n",
                "deploy/runtime/Dockerfile": b"FROM scratch\n",
                "package.json": b'{"version":"0.1.0"}\n',
            }
            for name, data in files.items():
                item = tarfile.TarInfo(f"openclaw-enterprise-{REVISION}/{name}")
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
        contract["archiveSha256"] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        (self.root / "builds/openclaw-enterprise/source.json").write_text(json.dumps(contract))
        (self.root / "scripts/config/openclaw-enterprise.json").write_text(json.dumps({
            "source": {"revision": REVISION, "cli": {"buildRevision": REVISION,
                                                   "sourcePath": "cmd/occ",
                                                   "imageRepository": "harbor.stinkyboi.com/homelab/homelab-oce-cli"},
                       "images": {"controller": {"repository": "harbor.stinkyboi.com/homelab/homelab-oce-controller"},
                                  "runtime": {"repository": "harbor.stinkyboi.com/homelab/homelab-oce-runtime"}}}
        }))
        curl = self.root / "bin/curl"
        curl.write_text('#!/bin/bash\nwhile [[ "$1" != --output ]]; do shift; done\ncp "$FIXTURE_ARCHIVE" "$2"\n')
        curl.chmod(0o700)
        docker = self.root / "bin/docker"
        docker.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >>"$DOCKER_CALLS"\n'
                          'if [[ "$1 $2" == "image inspect" ]]; then printf "%s\\n" "$FIXTURE_REVISION"; fi\n'
                          'if [[ "$1" == "run" ]]; then printf "occ 0.1.0\\n"; fi\n')
        docker.chmod(0o700)
        go = self.root / "bin/go"
        go.write_text('#!/bin/bash\n'
                      '[[ "$GOTOOLCHAIN" == go1.27.1 && "$CGO_ENABLED" == 0 && "$GOOS" == linux && "$GOARCH" == amd64 && "$GOAMD64" == v1 ]] || exit 96\n'
                      'while [[ "$1" != -o ]]; do shift; done\n'
                      'printf "fixture occ binary" >"$2"\n')
        go.chmod(0o700)
        self.calls = self.root / "docker-calls"

    def run_build(self):
        return subprocess.run(
            ["bash", str(self.root / "builds/openclaw-enterprise/build.sh")],
            cwd=self.root,
            env={**os.environ, "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
                 "FIXTURE_ARCHIVE": str(self.archive), "FIXTURE_REVISION": REVISION,
                 "DOCKER_CALLS": str(self.calls), "TMPDIR": str(self.root)},
            capture_output=True, text=True, timeout=20, check=False,
        )

    def test_matching_source_builds_paired_images_and_cli(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text().splitlines()
        builds = [call for call in calls if call.startswith("buildx build ")]
        self.assertEqual(len(builds), 3)
        self.assertTrue(all(f"OCC_BUILD_REVISION={REVISION}" in call for call in builds[:2]))
        self.assertIn("--target runtime", builds[0])
        self.assertIn("--file deploy/runtime/Dockerfile", builds[1])
        self.assertIn("occ.Dockerfile", builds[2])
        self.assertIn("homelab-oce-cli:build", builds[2])
        self.assertIn("run --rm --network none homelab-oce-cli:build --version", calls)

    def test_changed_cli_binary_fails_before_cli_image_build(self):
        contract = self.root / "builds/openclaw-enterprise/source.json"
        value = json.loads(contract.read_text())
        value["cliBinarySha256"] = "0" * 64
        contract.write_text(json.dumps(value))
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        builds = [call for call in self.calls.read_text().splitlines()
                  if call.startswith("buildx build ")]
        self.assertEqual(len(builds), 2)

    def test_changed_source_fails_before_docker(self):
        self.archive.write_bytes(b"changed")
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_mismatched_cli_revision_fails_before_download(self):
        config = self.root / "scripts/config/openclaw-enterprise.json"
        value = json.loads(config.read_text())
        value["source"]["cli"]["buildRevision"] = "0" * 40
        config.write_text(json.dumps(value))
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_wrong_destination_fails_before_download(self):
        config = self.root / "scripts/config/openclaw-enterprise.json"
        value = json.loads(config.read_text())
        value["source"]["images"]["runtime"]["repository"] = "ghcr.io/other/runtime"
        config.write_text(json.dumps(value))
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
