#!/usr/bin/env python3
"""Offline tests for Langfuse's offsite raw-version copy contract."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).with_name("langfuse-raw-version-backup.py")
SPEC = importlib.util.spec_from_file_location("langfuse_raw_backup", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeS3:
    def __init__(self, change_after_copy=False, corrupt_readback=False):
        self.change_after_copy = change_after_copy
        self.corrupt_readback = corrupt_readback
        self.list_calls = 0
        self.objects = {}
        self.source = b"raw-event"

    def __call__(self, region, operation, *args, file=None):
        def value(option):
            return args[args.index(option) + 1]

        if operation == "get-bucket-versioning":
            return {"Status": "Enabled"}
        if operation == "get-bucket-encryption":
            return {"ServerSideEncryptionConfiguration": {"Rules": [{
                "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"},
                "BucketKeyEnabled": True,
            }]}}
        if operation == "list-object-versions":
            self.list_calls += 1
            versions = [{"Key": "raw/a", "VersionId": "version-1",
                         "Size": len(self.source), "LastModified": "2026-10-27T00:00:00Z",
                         "IsLatest": True}]
            if self.change_after_copy and self.list_calls == 2:
                versions.append({"Key": "raw/new", "VersionId": "version-2",
                                 "Size": 1, "LastModified": "2026-10-27T00:01:00Z",
                                 "IsLatest": True})
            return {"IsTruncated": False, "Versions": versions,
                    "DeleteMarkers": [{"Key": "raw/deleted", "VersionId": "delete-1",
                                       "LastModified": "2026-10-26T00:00:00Z",
                                       "IsLatest": True}]}
        if operation == "get-object" and region == "us-west-2":
            Path(file).write_bytes(self.source)
            return {"VersionId": "version-1", "ContentLength": len(self.source),
                    "ServerSideEncryption": "aws:kms"}
        if operation == "put-object":
            key = value("--key")
            assert value("--if-none-match") == "*"
            assert key not in self.objects
            body = Path(value("--body")).read_bytes()
            version = f"copy-{len(self.objects) + 1}"
            self.objects[key] = (version, body, value("--metadata").removeprefix("sha256="))
            return {"VersionId": version}
        if operation == "get-object" and region == "us-east-1":
            version, body, digest = self.objects[value("--key")]
            assert value("--version-id") == version
            Path(file).write_bytes(body + b"!" if self.corrupt_readback else body)
            return {"VersionId": version, "ContentLength": len(body),
                    "ServerSideEncryption": "aws:kms", "Metadata": {"sha256": digest}}
        raise AssertionError(f"unexpected AWS call: {region} {operation}")


class BackupTest(unittest.TestCase):
    def test_publishes_exact_versions_and_completion_last(self):
        fake = FakeS3()
        with tempfile.TemporaryDirectory() as temp:
            count, size, digest = MODULE.backup(
                fake, "123456789012", "homelab-langfuse-123456789012-us-west-2",
                "homelab-application-backups-123456789012-us-east-1",
                "langfuse/raw-versions/" + "a" * 40 + "/123/1", Path(temp))
        self.assertEqual((count, size), (1, len(fake.source)))
        self.assertEqual(len(fake.objects), 2)
        key = next(key for key in fake.objects if key.endswith("/complete.json"))
        manifest = json.loads(fake.objects[key][1])
        self.assertEqual(manifest["items"][0]["kind"], "object")
        self.assertEqual(manifest["items"][0]["version"], "version-1")
        self.assertEqual(manifest["items"][1]["kind"], "delete")
        self.assertEqual(MODULE.hashlib.sha256(fake.objects[key][1]).hexdigest(), digest)
        self.assertTrue(all("/raw/a" not in key for key in fake.objects))

    def test_changed_source_leaves_no_completion_marker(self):
        fake = FakeS3(change_after_copy=True)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(MODULE.BackupBlocked, "changed during copy"):
                MODULE.backup(
                    fake, "123456789012", "homelab-langfuse-123456789012-us-west-2",
                    "homelab-application-backups-123456789012-us-east-1",
                    "langfuse/raw-versions/" + "a" * 40 + "/123/1", Path(temp))
        self.assertFalse(any(key.endswith("/complete.json") for key in fake.objects))

    def test_corrupt_offsite_readback_leaves_no_completion_marker(self):
        fake = FakeS3(corrupt_readback=True)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(MODULE.BackupBlocked, "readback differs"):
                MODULE.backup(
                    fake, "123456789012", "homelab-langfuse-123456789012-us-west-2",
                    "homelab-application-backups-123456789012-us-east-1",
                    "langfuse/raw-versions/" + "a" * 40 + "/123/1", Path(temp))
        self.assertFalse(any(key.endswith("/complete.json") for key in fake.objects))

    def test_committed_bucket_names_are_exact(self):
        self.assertEqual(MODULE.declared_buckets(), (
            "716182248480", "homelab-langfuse-716182248480-us-west-2",
            "homelab-application-backups-716182248480-us-east-1"))


if __name__ == "__main__":
    unittest.main()
