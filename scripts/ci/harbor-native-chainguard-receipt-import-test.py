#!/usr/bin/env python3
"""Fixtures for protected native receipt artifact import."""

import copy
import base64
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


IMPORT = module("native_receipt_import", ROOT / "scripts/ci/harbor-native-chainguard-receipt-import.py")
NATIVE = IMPORT.NATIVE_RECEIPT
SHA = "a" * 40
RUN_ID = 123
ARTIFACT_ID = 456
AMD64 = "sha256:" + "a" * 64
ARM64 = "sha256:" + "b" * 64


def index():
    return json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": AMD64,
             "size": 1, "platform": {"os": "linux", "architecture": "amd64"}},
            {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": ARM64,
             "size": 1, "platform": {"os": "linux", "architecture": "arm64"}},
        ],
    }, separators=(",", ":")).encode()


def archive(value, names=(IMPORT.RECEIPT_FILE,)):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in names:
            bundle.writestr(name, json.dumps(value, sort_keys=True))
    return output.getvalue()


class FakeGitHub:
    def __init__(self, run, artifacts, payload, contents=None, files=None):
        self.run = run
        self.artifacts = artifacts
        self.payload = payload
        self.contents = contents or {}
        self.files = files
        self.calls = []

    def json(self, path):
        self.calls.append(path)
        if path.endswith(f"/runs/{RUN_ID}"):
            return copy.deepcopy(self.run)
        if path.endswith(f"/runs/{RUN_ID}/artifacts?per_page=100"):
            return copy.deepcopy(self.artifacts)
        if "/contents/" in path:
            revision = path.rsplit("?ref=", 1)[1]
            value = self.contents[revision]
            raw = json.dumps(value, sort_keys=True).encode()
            return {"type": "file", "path": IMPORT.STATE_PATH, "encoding": "base64", "size": len(raw),
                    "content": base64.b64encode(raw).decode()}
        raise AssertionError(path)

    def download(self, path):
        self.calls.append(path)
        if path.endswith(f"/artifacts/{ARTIFACT_ID}/zip"):
            return self.payload
        raise AssertionError(path)

    def content(self, _repository, _path, revision):
        return copy.deepcopy(self.contents[revision])

    def compare(self, _repository, _base_sha, _head_sha):
        return set(self.files)


class NoNetwork:
    def json(self, _path):
        raise AssertionError("unchanged receipt made a network request")

    def download(self, _path):
        raise AssertionError("unchanged receipt made a network request")


class ReceiptImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.raw = index()
        self.config = {
            "schema_version": 1,
            "images": [{
                "image_id": "chainguard-python", "source": "cgr.dev/chainguard/python:latest",
                "destination": "harbor.stinkyboi.com/homelab/chainguard/python:latest",
                "access_class": "public", "required_platforms": ["linux/amd64", "linux/arm64"],
                "release_recipe": "python-release-v1",
            }],
        }
        replication = {
            "schema_version": 1, "paused": False, "schedule": "0 0 * * * *", "source_registry": "cgr.dev",
            "rules": [{"repository": "chainguard/python", "source_tag": "latest",
                       "destination": "homelab/chainguard/python", "override": True,
                       "delete": False, "flatten": False, "access_class": "public"}],
        }
        catalog = {"images": [{"source": "cgr.dev/chainguard/python:latest@" + NATIVE.bytes_digest(self.raw)}]}
        self.replication_path = root / "replication.json"
        self.catalog_path = root / "catalog.json"
        self.replication_path.write_text(json.dumps(replication))
        self.catalog_path.write_text(json.dumps(catalog))
        self.original_replication, self.original_catalog = IMPORT.REPLICATION, IMPORT.CATALOG
        IMPORT.REPLICATION, IMPORT.CATALOG = self.replication_path, self.catalog_path
        self.plans = IMPORT.native_plans(self.config)
        plan = self.plans["chainguard-python"]
        scan = {
            "schema_version": 1, "kind": "native-chainguard-scan-v1", "image_id": plan["image_id"],
            "config_digest": plan["config_digest"], "destination_digest": plan["source_digest"],
            "platforms": {"linux/amd64": AMD64, "linux/arm64": ARM64},
            "scan_status": {"linux/amd64": "Success", "linux/arm64": "Success"},
        }
        self.receipt = NATIVE.receipt_for(plan, SHA, self.raw, self.raw, self.raw, scan)
        self.envelope = {"schema_version": 1, "kind": "native-chainguard-receipts-v1",
                         "repository_sha": SHA, "receipts": [self.receipt]}
        self.payload = archive(self.envelope)
        self.run = {
            "id": RUN_ID, "event": "workflow_dispatch", "path": IMPORT.WORKFLOW_PATH + "@main",
            "head_branch": "main", "head_sha": SHA, "status": "completed", "conclusion": "success",
            "workflow_id": 77, "repository": {"full_name": IMPORT.REPOSITORY, "id": 88},
        }
        self.artifacts = {"artifacts": [{
            "id": ARTIFACT_ID, "name": IMPORT.ARTIFACT_PREFIX + SHA, "expired": False,
            "size_in_bytes": len(self.payload), "digest": IMPORT.digest(self.payload),
            "workflow_run": {"id": RUN_ID, "head_branch": "main", "head_sha": SHA, "repository_id": 88},
        }]}

    def tearDown(self):
        IMPORT.REPLICATION, IMPORT.CATALOG = self.original_replication, self.original_catalog
        self.directory.cleanup()

    def api(self, contents=None, files=None):
        return FakeGitHub(self.run, self.artifacts, self.payload, contents, files)

    def test_exact_successful_artifact_imports_and_later_unchanged_state_needs_no_network(self):
        receipts, provenance = IMPORT.verify_artifact(self.api(), IMPORT.REPOSITORY, RUN_ID, SHA, self.plans)
        state = IMPORT.imported_state({"schema_version": 1, "receipts": {}, "applications": {}, "rejected_digests": {}},
                                      receipts, provenance)
        entry = state["receipts"]["chainguard-python"]
        self.assertTrue(IMPORT.verify_imported_receipt(self.plans["chainguard-python"], entry)[0])
        self.assertEqual(
            IMPORT.verify_state_change(self.config, {"receipts": {}}, state, self.api()),
            ["chainguard-python"],
        )
        self.assertEqual(IMPORT.verify_state_change(self.config, state, state, NoNetwork()), [])

    def test_wrong_run_artifact_or_archive_is_rejected(self):
        cases = []
        bad_run = copy.deepcopy(self.run)
        bad_run["event"] = "push"
        cases.append((bad_run, self.artifacts, self.payload))
        bad_run = copy.deepcopy(self.run)
        bad_run["path"] = IMPORT.WORKFLOW_PATH + "@other"
        cases.append((bad_run, self.artifacts, self.payload))
        bad_artifact = copy.deepcopy(self.artifacts)
        bad_artifact["artifacts"][0]["digest"] = "sha256:" + "0" * 64
        cases.append((self.run, bad_artifact, self.payload))
        cases.append((self.run, self.artifacts, archive(self.envelope, (IMPORT.RECEIPT_FILE, "extra.json"))))
        for run, artifacts, payload in cases:
            with self.subTest(run=run is not self.run, artifacts=artifacts is not self.artifacts):
                with self.assertRaises(IMPORT.ImportError):
                    IMPORT.verify_artifact(FakeGitHub(run, artifacts, payload), IMPORT.REPOSITORY, RUN_ID, SHA, self.plans)

    def test_changed_state_must_exactly_match_the_live_protected_artifact(self):
        receipts, provenance = IMPORT.verify_artifact(self.api(), IMPORT.REPOSITORY, RUN_ID, SHA, self.plans)
        state = IMPORT.imported_state({"schema_version": 1, "receipts": {}}, receipts, provenance)
        state["receipts"]["chainguard-python"]["receipt"]["consumer_access"] = False
        with self.assertRaises(IMPORT.ImportError):
            IMPORT.verify_state_change(self.config, {"receipts": {}}, state, self.api())

    def test_pull_request_verifier_reads_state_as_data_and_rejects_bundled_changes(self):
        receipts, provenance = IMPORT.verify_artifact(self.api(), IMPORT.REPOSITORY, RUN_ID, SHA, self.plans)
        base = {"schema_version": 1, "receipts": {}, "applications": {}, "rejected_digests": {}}
        state = IMPORT.imported_state(base, receipts, provenance)
        base_sha, head_sha = "b" * 40, "c" * 40
        self.assertEqual(
            IMPORT.verify_pull_request(
                self.config, self.api({base_sha: base, head_sha: state}, {IMPORT.STATE_PATH}),
                base_sha, head_sha,
            ),
            ["chainguard-python"],
        )
        with self.assertRaises(IMPORT.ImportError):
            IMPORT.verify_pull_request(
                self.config, self.api({base_sha: base, head_sha: state}, {IMPORT.STATE_PATH, "docs/extra.md"}),
                base_sha, head_sha,
            )

    def test_native_receipt_cannot_be_deleted_or_preseeded(self):
        receipts, provenance = IMPORT.verify_artifact(self.api(), IMPORT.REPOSITORY, RUN_ID, SHA, self.plans)
        imported = IMPORT.imported_state({"schema_version": 1, "receipts": {}}, receipts, provenance)
        removed = {"schema_version": 1, "receipts": {}}
        with self.assertRaises(IMPORT.ImportError):
            IMPORT.verify_state_change(self.config, imported, removed, NoNetwork())
        base_sha, head_sha = "b" * 40, "c" * 40
        with self.assertRaises(IMPORT.ImportError):
            IMPORT.verify_pull_request(
                self.config, self.api({base_sha: imported, head_sha: removed}, {IMPORT.STATE_PATH}),
                base_sha, head_sha,
            )
        preseeded = {"schema_version": 1, "receipts": {"chainguard-preseed": {}}}
        with self.assertRaises(IMPORT.ImportError):
            IMPORT.verify_pull_request(
                self.config, self.api({base_sha: {"schema_version": 1, "receipts": {}}, head_sha: preseeded},
                                      {IMPORT.STATE_PATH}),
                base_sha, head_sha,
            )

    def test_contents_api_decodes_only_bounded_base64_json(self):
        state = {"schema_version": 1, "receipts": {}}
        raw = json.dumps(state).encode()
        client = IMPORT.GitHubActionsClient()
        client.json = lambda _path: {
            "type": "file", "path": IMPORT.STATE_PATH, "encoding": "base64", "size": len(raw),
            "content": base64.b64encode(raw).decode(),
        }
        self.assertEqual(client.content(IMPORT.REPOSITORY, IMPORT.STATE_PATH, SHA), state)
        client.json = lambda _path: {
            "type": "file", "path": IMPORT.STATE_PATH, "encoding": "base64", "size": 1,
            "content": "not?base64",
        }
        with self.assertRaises(IMPORT.ImportError):
            client.content(IMPORT.REPOSITORY, IMPORT.STATE_PATH, SHA)
        client.json = lambda _path: {
            "merge_base_commit": {"sha": SHA}, "files": [{"filename": IMPORT.STATE_PATH}],
        }
        self.assertEqual(client.compare(IMPORT.REPOSITORY, SHA, "b" * 40), {IMPORT.STATE_PATH})
        client.json = lambda _path: {"merge_base_commit": {"sha": "c" * 40}, "files": []}
        with self.assertRaises(IMPORT.ImportError):
            client.compare(IMPORT.REPOSITORY, SHA, "b" * 40)


if __name__ == "__main__":
    unittest.main()
