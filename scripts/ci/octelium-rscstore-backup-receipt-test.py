#!/usr/bin/env python3
"""Verify that the protected backup accepts only its recent, exact preflight receipt."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "receipt", Path(__file__).with_name("octelium-rscstore-backup-receipt.py")
)
receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipt)

NOW = 1_790_000_000
SOURCE_SHA = "a" * 40
RUN_ID = "123456"


class S3ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        uids = {"EXPECTED_PVC_UID": "11111111-1111-1111-1111-111111111111",
                "EXPECTED_PV_UID": "22222222-2222-2222-2222-222222222222"}
        env = patch.dict(os.environ, uids)
        env.start()
        self.addCleanup(env.stop)
        clock = patch.object(receipt.time, "time", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.record = receipt.binding(RUN_ID, "preflight", SOURCE_SHA)
        self.record["retained_at"] = NOW
        self.calls = []
        self.version = "verified-version"

    def call(self, service, operation, args=()):
        self.assertEqual(service, "s3api")
        self.calls.append((operation, args))
        payload = receipt.backup.canonical(self.record)
        digest = {"sha256": hashlib.sha256(payload).hexdigest()}
        response = {"VersionId": self.version, "ContentLength": len(payload),
                    "ChecksumSHA256": receipt.backup.OFFSITE.checksum(digest),
                    "ServerSideEncryption": "aws:kms", "BucketKeyEnabled": True}
        if operation == "get-object":
            self.assertEqual(args[-3:-1], ["--version-id", "verified-version"])
            Path(args[-1]).write_bytes(payload)
            response.update(getattr(self, "readback_override", {}))
        return response

    def test_fetches_exact_s3_version_and_records_authorization(self):
        receipt.verify_preflight(self, self.workspace, RUN_ID, SOURCE_SHA)
        self.assertEqual([op for op, _ in self.calls], ["head-object", "get-object"])
        marker = self.workspace / "authorized-preflight.json"
        self.assertEqual(json.loads(marker.read_text())["version_id"], self.version)
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)

    def test_rejects_different_source_storage_and_old_or_future_receipts(self):
        for field, value in (
            ("source_sha", "b" * 40), ("workflow_run_id", "123455"),
            ("pvc_uid", "33333333-3333-3333-3333-333333333333"),
            ("pv_uid", "33333333-3333-3333-3333-333333333333"),
            ("retained_at", NOW - receipt.MAX_PREFLIGHT_AGE - 1),
            ("retained_at", NOW + 1), ("stage", "backup"),
        ):
            with self.subTest(field=field, value=value):
                previous = self.record[field]
                self.record[field] = value
                with self.assertRaisesRegex(ValueError, "preflight source"):
                    receipt.verify_preflight(self, self.workspace, RUN_ID, SOURCE_SHA)
                self.assertFalse((self.workspace / "authorized-preflight.json").exists())
                (self.workspace / "prior-preflight.json").unlink()
                self.record[field] = previous

    def test_rejects_unversioned_head_before_readback(self):
        self.version = "null"
        with self.assertRaisesRegex(ValueError, "preflight object metadata"):
            receipt.verify_preflight(self, self.workspace, RUN_ID, SOURCE_SHA)
        self.assertEqual([op for op, _ in self.calls], ["head-object"])

    def test_rejects_changed_version_or_missing_encryption(self):
        for changed in ({"VersionId": "other"}, {"BucketKeyEnabled": False}):
            with self.subTest(changed=changed):
                self.readback_override = changed
                with self.assertRaisesRegex(ValueError, "checksum, or encryption"):
                    receipt.verify_preflight(self, self.workspace, RUN_ID, SOURCE_SHA)
                self.assertFalse((self.workspace / "authorized-preflight.json").exists())
                (self.workspace / "prior-preflight.json").unlink()


if __name__ == "__main__":
    unittest.main()
