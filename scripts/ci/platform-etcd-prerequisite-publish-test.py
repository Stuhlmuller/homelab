#!/usr/bin/env python3
"""Offline fail-closed fixtures for exact-key etcd prerequisite publication."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "platform-etcd-prerequisite-publish.py"
spec = importlib.util.spec_from_file_location("platform_etcd_prerequisite_publish", SCRIPT)
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)

SOURCE = "a" * 40
SNAPSHOT = "b" * 64
PUBLICATION = "c" * 32


class Store:
    target = {"region": "us-east-1", "account_id": "716182248480"}

    def __init__(self, body):
        self.body = body
        self.operations = []
        self.versions = []
        self.deleted = False
        self.truncated = False
        self.foreign = False
        self.after_put_duplicate = False
        self.after_put_deleted = False
        self.after_put_truncated = False
        self.after_put_foreign = False

    def check(self):
        self.operations.append("check")

    def call(self, service, operation, arguments=()):
        self.operations.append(operation)
        if operation == "list-object-versions":
            key = arguments[arguments.index("--prefix") + 1]
            listed = list(self.versions)
            after_put = "put-object" in self.operations
            if self.foreign or (after_put and self.after_put_foreign):
                listed.append({"Key": key + "-foreign", "VersionId": "bad", "IsLatest": False})
            if self.after_put_duplicate and after_put:
                listed.append({"Key": key, "VersionId": "old", "IsLatest": False})
            return {"IsTruncated": self.truncated or (after_put and self.after_put_truncated),
                    "DeleteMarkers": [{"Key": key}] if self.deleted or (after_put and self.after_put_deleted) else [],
                    "Versions": listed}
        if operation == "put-object":
            self.body_key = arguments[arguments.index("--key") + 1]
            self.checksum = arguments[arguments.index("--checksum-sha256") + 1]
            assert arguments[arguments.index("--if-none-match") + 1] == "*"
            assert arguments[arguments.index("--server-side-encryption") + 1] == "aws:kms"
            self.versions = [{"Key": self.body_key, "VersionId": "v1", "IsLatest": True}]
            return {"VersionId": "v1", "ChecksumSHA256": self.checksum}
        if operation == "head-object":
            return {"VersionId": "v1", "ChecksumSHA256": self.checksum,
                    "ContentLength": len(self.body), "ServerSideEncryption": "aws:kms",
                    "BucketKeyEnabled": True}
        raise AssertionError(f"unexpected operation {service} {operation}")

    def download(self, key, version, directory):
        self.operations.append("download")
        assert key == self.body_key and version == "v1"
        return self.body


class PublicationTests(unittest.TestCase):
    def value(self):
        return {
            "sourceSha": SOURCE, "verified": True,
            "capturedAt": "2026-10-27T00:00:00Z", "offNode": True,
            "offlineRestoreVerified": True, "snapshotSha256": SNAPSHOT,
            "objectVersionId": "object-v1", "manifestVersionId": "manifest-v1",
            "objectPrefix": f"etcd/{SNAPSHOT}/{PUBLICATION}/",
            "offlineRestore": "etcdutl-offline-database-restore",
            "controlPlaneRecoveryTested": False,
        }

    def run_publication(self, changed=None, store_change=None, main=SOURCE,
                        freshness_error=None):
        value = self.value()
        if changed:
            value.update(changed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / producer.candidate.RECEIPT
            path.write_text(json.dumps(value))
            path.chmod(0o600)
            store = Store(path.read_bytes())
            if store_change:
                store_change(store)
            def fresh(_timestamp):
                if freshness_error:
                    raise ValueError("private recovery evidence is stale")
            with patch.object(producer, "reviewed_publisher"), \
                    patch.object(producer.candidate, "stage", return_value=path), \
                    patch.object(producer.platform, "current_main_sha", return_value=main), \
                    patch.object(producer.platform, "fresh_recovery_time", side_effect=fresh):
                try:
                    outcome = producer.publish(SOURCE, SNAPSHOT, PUBLICATION,
                                               Path("/unused/archive"), Path(directory), store)
                    return outcome, store.operations, store.body_key
                except ValueError as error:
                    return str(error), store.operations, getattr(store, "body_key", None)

    def test_exact_unique_receipt_is_read_back_from_one_version(self):
        result, operations, key = self.run_publication()
        self.assertEqual(result, "v1")
        self.assertEqual(key, producer.platform.prerequisite_key(
            SOURCE, "off-node-etcd-backup", PUBLICATION))
        self.assertEqual(operations, ["check", "list-object-versions", "put-object",
                                      "list-object-versions", "head-object", "download"])

    def test_candidate_timestamp_is_snapshot_time_and_cannot_be_renewed(self):
        result, operations, _ = self.run_publication(freshness_error=True)
        self.assertIn("stale", result)
        self.assertEqual(operations, [])

    def test_tampered_candidate_cannot_publish(self):
        for changed in ({"sourceSha": "d" * 40}, {"offlineRestoreVerified": False},
                        {"controlPlaneRecoveryTested": True},
                        {"objectPrefix": "etcd/other/"},
                        {"objectVersionId": "null"}):
            with self.subTest(changed=changed):
                result, operations, _ = self.run_publication(changed=changed)
                self.assertIn("differs", result)
                self.assertEqual(operations, [])

    def test_main_advance_or_existing_key_prevents_put(self):
        for change, main in ((None, "d" * 40),
                             (lambda store: setattr(store, "versions", [{
                                 "Key": producer.platform.prerequisite_key(
                                     SOURCE, "off-node-etcd-backup", PUBLICATION),
                                 "VersionId": "v0", "IsLatest": True}]), SOURCE),
                             (lambda store: setattr(store, "deleted", True), SOURCE),
                             (lambda store: setattr(store, "truncated", True), SOURCE),
                             (lambda store: setattr(store, "foreign", True), SOURCE)):
            with self.subTest(main=main, change=change):
                result, operations, _ = self.run_publication(store_change=change, main=main)
                self.assertIsInstance(result, str)
                self.assertNotIn("put-object", operations)

    def test_canceled_or_partial_post_put_history_cannot_claim_completion(self):
        for flag in ("after_put_duplicate", "after_put_deleted",
                     "after_put_truncated", "after_put_foreign"):
            with self.subTest(flag=flag):
                result, operations, _ = self.run_publication(
                    store_change=lambda store: setattr(store, flag, True))
                self.assertIsInstance(result, str)
                self.assertIn("put-object", operations)
                self.assertNotIn("head-object", operations)

    def test_publisher_requires_owner_first_attempt(self):
        with patch.object(producer.candidate, "reviewed_context"), \
                patch.object(producer.subprocess, "run") as run, \
                patch.object(producer.os, "environ", {"GITHUB_ACTOR_ID": "other",
                                                     "GITHUB_RUN_ATTEMPT": "1"}):
            run.return_value.stdout = SCRIPT.read_bytes()
            with self.assertRaisesRegex(ValueError, "reviewed owner"):
                producer.reviewed_publisher(SOURCE)


if __name__ == "__main__":
    unittest.main()
