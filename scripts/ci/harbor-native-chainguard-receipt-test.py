#!/usr/bin/env python3
"""Offline fixtures for native Chainguard receipt invariants."""

import base64
import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock


ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


VERIFY = module("native_receipt", ROOT / "scripts/ci/harbor-native-chainguard-receipt.py")


AMD64 = "sha256:" + "a" * 64
ARM64 = "sha256:" + "b" * 64


def index(children=None):
    children = children or {"linux/amd64": AMD64, "linux/arm64": ARM64}
    manifests = []
    for platform, digest in sorted(children.items()):
        os_name, architecture = platform.split("/", 1)
        manifests.append({"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": digest,
                          "size": 1, "platform": {"os": os_name, "architecture": architecture}})
    return json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
                       "manifests": manifests}, separators=(",", ":")).encode()


def configuration(raw):
    digest = VERIFY.bytes_digest(raw)
    config = {"schema_version": 1, "images": [{
        "image_id": "chainguard-python", "source": "cgr.dev/chainguard/python:latest",
        "destination": "harbor.stinkyboi.com/homelab/chainguard-python:latest", "access_class": "public",
        "required_platforms": ["linux/amd64", "linux/arm64"], "release_recipe": "python-release-v1",
    }]}
    replication = {"schema_version": 1, "paused": False, "schedule": "0 0 * * * *", "source_registry": "cgr.dev",
                   "rules": [{"repository": "chainguard/python", "source_tag": "latest",
                              "destination": "homelab/chainguard-python", "override": True,
                              "delete": False, "flatten": False, "access_class": "public"}]}
    catalog = {"images": [{"source": f"cgr.dev/chainguard/python:latest@{digest}"}]}
    return config, replication, catalog


def scan_receipt(plan):
    return {"schema_version": 1, "kind": "native-chainguard-scan-v1", "image_id": plan["image_id"],
            "config_digest": plan["config_digest"],
            "destination_digest": plan["source_digest"], "platforms": {"linux/amd64": AMD64, "linux/arm64": ARM64},
            "scan_status": {"linux/amd64": "Success", "linux/arm64": "Success"}}


class VerificationTests(TestCase):
    def setUp(self):
        self.raw = index()
        self.config, self.replication, self.catalog = configuration(self.raw)
        self.plan = VERIFY.selected_plan(self.config, self.replication, self.catalog, "chainguard-python")

    def test_matching_index_scan_and_authenticated_pull_emit_a_bound_receipt(self):
        receipt = VERIFY.receipt_for(self.plan, "c" * 40, self.raw, self.raw, self.raw, scan_receipt(self.plan))
        self.assertTrue(VERIFY.verify_native_receipt(self.plan, receipt)[0])
        self.assertEqual(receipt["platforms"], {"linux/amd64": AMD64, "linux/arm64": ARM64})

    def test_unmanaged_replication_rule_or_catalog_digest_is_rejected(self):
        broken = copy.deepcopy(self.replication)
        broken["rules"][0]["destination"] = "homelab/other"
        with self.assertRaises(VERIFY.ReceiptError):
            VERIFY.build_plan(self.config, broken, self.catalog)
        broken_catalog = copy.deepcopy(self.catalog)
        broken_catalog["images"][0]["source"] = broken_catalog["images"][0]["source"].replace("a", "c", 1)
        with self.assertRaises(VERIFY.ReceiptError):
            VERIFY.build_plan(self.config, self.replication, broken_catalog)

    def test_contract_digest_ignores_consumer_status_but_binds_import_contract(self):
        with_status = copy.deepcopy(self.config)
        with_status["consumers"] = [{"migration_status": "candidate"}]
        changed_status = copy.deepcopy(with_status)
        changed_status["consumers"][0]["migration_status"] = "migrated"
        first = VERIFY.selected_plan(with_status, self.replication, self.catalog, "chainguard-python")
        second = VERIFY.selected_plan(changed_status, self.replication, self.catalog, "chainguard-python")
        self.assertEqual(first["config_digest"], second["config_digest"])
        changed_catalog = copy.deepcopy(self.catalog)
        changed_catalog["images"][0]["source"] = "cgr.dev/chainguard/python:latest@sha256:" + "c" * 64
        changed = VERIFY.selected_plan(self.config, self.replication, changed_catalog, "chainguard-python")
        self.assertNotEqual(self.plan["config_digest"], changed["config_digest"])

    def test_missing_platform_and_mismatched_private_index_fail(self):
        with self.assertRaises(VERIFY.ReceiptError):
            VERIFY.receipt_for(self.plan, "c" * 40, index({"linux/amd64": AMD64}),
                                index({"linux/amd64": AMD64}), index({"linux/amd64": AMD64}), scan_receipt(self.plan))
        with self.assertRaises(VERIFY.ReceiptError):
            VERIFY.receipt_for(self.plan, "c" * 40, self.raw, self.raw + b" ", self.raw, scan_receipt(self.plan))

    def test_failed_scan_and_forged_receipt_fail(self):
        failed = scan_receipt(self.plan)
        failed["scan_status"]["linux/arm64"] = "Running"
        with self.assertRaises(VERIFY.ReceiptError):
            VERIFY.receipt_for(self.plan, "c" * 40, self.raw, self.raw, self.raw, failed)
        forged = VERIFY.receipt_for(self.plan, "c" * 40, self.raw, self.raw, self.raw, scan_receipt(self.plan))
        forged["destination_ref"] = "harbor.stinkyboi.com/homelab/other:latest"
        self.assertFalse(VERIFY.verify_native_receipt(self.plan, forged)[0])


def artifact(digest, platform, counts=None, status="Success"):
    os_name, architecture = platform.split("/", 1)
    return {"type": "IMAGE", "digest": digest, "media_type": "application/vnd.oci.image.config.v1+json",
            "extra_attrs": {"os": os_name, "architecture": architecture},
            "scan_overview": {VERIFY.SCAN_REPORT_TYPE: {"scan_status": status,
                              "summary": {"summary": counts if counts is not None else {"Critical": 0, "High": 0}}}}}


class ScanReceiptTests(TestCase):
    def setUp(self):
        self.config, self.replication, self.catalog = configuration(index())
        self.plan = VERIFY.selected_plan(self.config, self.replication, self.catalog, "chainguard-python")
        self.artifacts = {AMD64: artifact(AMD64, "linux/amd64"), ARM64: artifact(ARM64, "linux/arm64")}

    def client(self, artifacts):
        class FakeClient:
            def __init__(self, password):
                self.password = password

            def artifact(self, repository, digest):
                self.repository = repository
                return artifacts[digest]
        return FakeClient

    def test_only_cve_free_completed_children_produce_a_bounded_receipt(self):
        receipt = VERIFY.scan_receipt(self.plan, VERIFY.bytes_digest(index()),
                                      {"linux/amd64": AMD64, "linux/arm64": ARM64}, "not-a-real-secret",
                                      self.client(self.artifacts))
        self.assertEqual(receipt["scan_status"], {"linux/amd64": "Success", "linux/arm64": "Success"})

    def test_failed_or_vulnerable_child_scan_is_rejected(self):
        for change in ({"status": "Running"}, {"counts": {"High": 1}}):
            with self.subTest(change=change):
                artifacts = copy.deepcopy(self.artifacts)
                if "status" in change:
                    artifacts[ARM64] = artifact(ARM64, "linux/arm64", status=change["status"])
                else:
                    artifacts[ARM64] = artifact(ARM64, "linux/arm64", counts=change["counts"])
                with self.assertRaises(VERIFY.ReceiptError):
                    VERIFY.scan_receipt(self.plan, VERIFY.bytes_digest(index()),
                                        {"linux/amd64": AMD64, "linux/arm64": ARM64}, "not-a-real-secret",
                                        self.client(artifacts))

    def test_stale_configuration_or_malformed_scan_summary_is_rejected(self):
        with self.assertRaises(VERIFY.ReceiptError):
            VERIFY.scan_receipt(self.plan, "sha256:" + "f" * 64,
                                {"linux/amd64": AMD64, "linux/arm64": ARM64}, "not-a-real-secret",
                                self.client(self.artifacts))
        artifacts = copy.deepcopy(self.artifacts)
        artifacts[ARM64]["scan_overview"][VERIFY.SCAN_REPORT_TYPE]["summary"] = {}
        with self.assertRaises(VERIFY.ReceiptError):
            VERIFY.scan_receipt(self.plan, VERIFY.bytes_digest(index()),
                                {"linux/amd64": AMD64, "linux/arm64": ARM64}, "not-a-real-secret",
                                self.client(artifacts))

    def test_empty_completed_scan_summary_is_cve_free(self):
        artifacts = copy.deepcopy(self.artifacts)
        artifacts[ARM64] = artifact(ARM64, "linux/arm64", counts={})
        receipt = VERIFY.scan_receipt(self.plan, VERIFY.bytes_digest(index()),
                                      {"linux/amd64": AMD64, "linux/arm64": ARM64}, "not-a-real-secret",
                                      self.client(artifacts))
        self.assertEqual(receipt["scan_status"]["linux/arm64"], "Success")

    def test_scan_cli_accepts_contract_digests(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config = directory / "config.json"
            replication = directory / "replication.json"
            catalog = directory / "catalog.json"
            raw_index = directory / "index.json"
            password = directory / "password"
            output = directory / "scan.json"
            config.write_text(json.dumps(self.config))
            replication.write_text(json.dumps(self.replication))
            catalog.write_text(json.dumps(self.catalog))
            raw_index.write_bytes(index())
            password.write_text("not-a-real-secret")

            def scan(plan, destination_digest, platforms, scan_password):
                self.assertEqual(plan, self.plan)
                self.assertEqual(destination_digest, self.plan["source_digest"])
                self.assertEqual(platforms, {"linux/amd64": AMD64, "linux/arm64": ARM64})
                self.assertEqual(scan_password, "not-a-real-secret")
                return scan_receipt(self.plan)

            with mock.patch.object(VERIFY, "scan_receipt", side_effect=scan), \
                 mock.patch.object(sys, "argv", [
                     "harbor-native-chainguard-receipt.py", "scan",
                     "--config", str(config), "--replication", str(replication), "--catalog", str(catalog),
                     "--image-id", "chainguard-python", "--config-digest", self.plan["config_digest"],
                     "--destination-digest", self.plan["source_digest"], "--index", str(raw_index),
                     "--scan-password-file", str(password), "--output", str(output),
                 ]):
                VERIFY.main()
            self.assertEqual(json.loads(output.read_text()), scan_receipt(self.plan))

    def test_scan_client_uses_the_exact_artifact_read_endpoint(self):
        class Response:
            status = 200

            def read(self, _limit):
                return json.dumps(self.artifact).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Opener:
            def open(self, request, timeout):
                self.request, self.timeout = request, timeout
                response = Response()
                response.artifact = self.artifact
                return response

        opener = Opener()
        opener.artifact = self.artifacts[AMD64]
        client = VERIFY.HarborScanClient("not-a-real-secret")
        client.opener = opener
        self.assertEqual(client.artifact("chainguard-python", AMD64), self.artifacts[AMD64])
        self.assertEqual(
            opener.request.full_url,
            f"https://harbor.stinkyboi.com/api/v2.0/projects/homelab/repositories/chainguard-python/artifacts/{AMD64}?with_scan_overview=true",
        )
        self.assertEqual(opener.timeout, 15)
        authorization = opener.request.get_header("Authorization")
        self.assertTrue(authorization.startswith("Basic "))
        self.assertEqual(base64.b64decode(authorization.removeprefix("Basic ")),
                         b"robot$homelab+scan:not-a-real-secret")

    def test_runner_uses_separate_artifact_read_credential_without_a_cluster_job(self):
        script = (ROOT / "scripts/ci/harbor-native-chainguard-receipt.sh").read_text()
        self.assertIn("/homelab/harbor/robot-pull-password", script)
        self.assertIn("/homelab/harbor/robot-scan-password", script)
        self.assertIn("--password-stdin", script)
        self.assertIn("rm -f -- \"$scratch/harbor-pull-password\"", script)
        self.assertIn("rm -f -- \"$scratch/harbor-scan-password\"", script)
        self.assertIn("--scan-password-file \"$scratch/harbor-scan-password\"", script)
        self.assertNotIn("GITHUB_OUTPUT", script)
        self.assertNotIn("cat \"$scratch/harbor-pull-password\"", script)
        self.assertNotIn("admin-password", script)
        self.assertNotIn("get configmap", script)
        self.assertNotIn("kubectl --namespace harbor create", script)
        self.assertNotIn("chainguard-receipt-job", script)
        self.assertLess(script.index("/homelab/harbor/robot-scan-password"),
                        script.index("--scan-password-file"))


if __name__ == "__main__":
    main()
