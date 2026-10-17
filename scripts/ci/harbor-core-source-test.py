#!/usr/bin/env python3
"""Check the core source trust boundary without network or production inputs."""

import hashlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class RegistryFixtureTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("registry_fixture", ROOT / "builds/harbor-core/registry-test.py")
        self.fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fixture)

    def test_repeated_index_and_every_blob_are_self_consistent(self):
        config, layer, child, index = self.fixture.fixture_payloads()
        descriptors = json.loads(index)["manifests"]
        self.assertEqual(len(descriptors), 8)
        self.assertTrue(all(item == descriptors[0] for item in descriptors))
        self.assertEqual(descriptors[0]["digest"], self.fixture.digest(child))
        manifest = json.loads(child)
        self.assertEqual(manifest["config"]["digest"], self.fixture.digest(config))
        self.assertEqual(manifest["layers"][0]["digest"], self.fixture.digest(layer))
        self.assertEqual(json.loads(config)["rootfs"]["diff_ids"], [self.fixture.digest(gzip.decompress(layer))])

    def test_upload_location_cannot_escape_disposable_endpoint(self):
        with patch.object(self.fixture.urllib.request, "urlopen") as network:
            with self.assertRaises(AssertionError):
                self.fixture.request("PUT", "https://registry.invalid/upload", b"fixture")
        network.assert_not_called()

    def test_valid_hostname_keeps_external_endpoint_on_loopback(self):
        template = ("hostname: reg.mydomain.com\nhttp:\n  port: 80\nhttps:\n  port: 443\n"
                    "harbor_admin_password: Harbor12345\ndata_volume: /data\nlog:\n    location: /var/log/harbor\n")
        config = self.fixture.fixture_config(template, Path("/owned-fixture"), "fixture-password")
        self.assertIn("hostname: harbor-fixture.invalid\nexternal_url: http://127.0.0.1:8080\n", config)
        self.assertNotIn("https:\n", config)
        self.assertIn("data_volume: /owned-fixture/data\n", config)

    def test_services_publish_no_ports_and_wait_for_candidate_health(self):
        generated = {"services": {}, "networks": {"harbor": {"internal": False}}}
        for name, component in (("log", "harbor-log"), ("core", "harbor-core"),
                                ("proxy", "nginx-photon"), ("jobservice", "harbor-jobservice")):
            generated["services"][name] = {"image": "goharbor/" + component + ":v2.15.4",
                "ports": [{"target": 8080, "published": "8080"}], "container_name": name,
                "depends_on": {"log": {"condition": "service_started"}, "core": {"condition": "service_started"}}}
        self.fixture.isolate_services(generated)
        self.assertNotIn("log", generated["services"])
        self.assertTrue(generated["networks"]["harbor"]["internal"])
        self.assertTrue(all("ports" not in service for service in generated["services"].values()))
        self.assertEqual(generated["services"]["core"]["image"], "homelab-harbor-core:build")
        for name in ("proxy", "jobservice"):
            self.assertEqual(generated["services"][name]["depends_on"]["core"]["condition"], "service_healthy")


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        recipe = self.root / "recipe"
        recipe.mkdir()
        shutil.copyfile(ROOT / "builds/harbor-core/prepare-source.py", recipe / "prepare-source.py")
        (recipe / "Dockerfile").write_text("fixture only\n")
        (recipe / "patches").mkdir()
        for name in ("0001.patch", "0002.patch", "0003.patch"):
            (recipe / "patches" / name).write_text("fixture only\n")
        spec = importlib.util.spec_from_file_location("source", recipe / "prepare-source.py")
        self.source = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.source)
        self.contract = recipe / "source.json"
        self.destination = self.root / "context"

    def archive(self, name="harbor-fixture/src/pkg/artifact/manager.go", link=None):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            info = tarfile.TarInfo(name)
            if link:
                info.type, info.linkname = tarfile.SYMTYPE, link
                archive.addfile(info)
            else:
                data = b"original source\n"
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        data = output.getvalue()
        self.contract.write_text(json.dumps({"revision": "fixture", "archive_url": "https://fixture.invalid/source",
                                             "archive_sha256": hashlib.sha256(data).hexdigest()}))
        return data

    def test_verified_source_checks_every_patch_and_keeps_baseline(self):
        data = self.archive()
        with patch.object(self.source.urllib.request, "urlopen", return_value=io.BytesIO(data)), \
                patch.object(self.source.subprocess, "run") as commands:
            self.source.prepare(self.destination)
        self.assertEqual(commands.call_count, 6)
        self.assertTrue(all(call.kwargs["check"] for call in commands.call_args_list))
        self.assertEqual((self.destination / "homelab-build/original-manager.go").read_bytes(), b"original source\n")

    def test_hash_mismatch_stops_before_extraction_or_patches(self):
        self.archive()
        with patch.object(self.source.urllib.request, "urlopen", return_value=io.BytesIO(b"corrupt")), \
                patch.object(self.source.subprocess, "run") as commands:
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                self.source.prepare(self.destination)
        commands.assert_not_called()
        self.assertFalse(any(self.destination.iterdir()))

    def test_wrong_root_and_escaping_symlink_stop_before_patches(self):
        for name, link in (("other/source", None), ("harbor-fixture/escape", "../../outside")):
            with self.subTest(name=name):
                data = self.archive(name, link)
                with patch.object(self.source.urllib.request, "urlopen", return_value=io.BytesIO(data)), \
                        patch.object(self.source.subprocess, "run") as commands:
                    with self.assertRaises((ValueError, tarfile.FilterError)):
                        self.source.prepare(self.destination)
                commands.assert_not_called()
                self.assertFalse((self.root / "outside").exists())

    def test_nonempty_context_refuses_before_download(self):
        self.archive()
        self.destination.mkdir()
        marker = self.destination / "retained"
        marker.write_text("keep")
        with patch.object(self.source.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(ValueError, "must be empty"):
                self.source.prepare(self.destination)
        download.assert_not_called()
        self.assertEqual(marker.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
