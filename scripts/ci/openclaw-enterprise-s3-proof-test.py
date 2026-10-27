#!/usr/bin/env python3
"""Offline adversarial fixtures for exact Enterprise S3 version readback."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "oce_s3_proof_under_test", ROOT / "scripts/ci/openclaw-enterprise-s3-proof.py")
PROOF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROOF)
ACCOUNT = PROOF.CHAIN.OFFSITE.read_inputs(
    ROOT / "IaC/application-backup-storage.hcl")["account_id"]
BUCKET = f"homelab-application-backups-{ACCOUNT}-us-east-1"
KMS_KEY = f"arn:aws:kms:us-east-1:{ACCOUNT}:key/11111111-1111-1111-1111-111111111111"
KMS_ALIAS = f"arn:aws:kms:us-east-1:{ACCOUNT}:alias/aws/s3"
PAYLOAD = b"encrypted-ciphertext-example"


def source_receipt(payload=PAYLOAD):
    backup_id = "a" * 64
    return {
        "scope": "source-only-recovery-chain", "publishable": False,
        "sourceSha": "b" * 40, "backupId": backup_id,
        "materialSha256": "c" * 64, "installationId": "ins_123",
        "namespaceId": "ns_123", "agentId": "agt_123",
        "revisionId": "rev_123", "ciphertextSha256": hashlib.sha256(payload).hexdigest(),
        "ciphertextBytes": len(payload), "bucket": BUCKET,
        "key": f"openclaw-enterprise/new/{backup_id}.tar.age",
        "versionId": "immutable-version-1", "publisherRunId": 100,
        "restoreRunId": 101,
    }


class FakeAws:
    def __init__(self, receipt, payload=PAYLOAD):
        self.receipt = receipt
        self.payload = payload
        self.calls = []
        self.corrupt = False
        self.missing = False
        self.no_kms = False
        self.bad_role = False
        self.missing_body = False
        self.world_readable_body = False

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["stdin"] == subprocess.DEVNULL
        service, operation = args[3:5]
        if service == "sts":
            response = {"Account": ACCOUNT,
                        "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/"
                               + ("other-role" if self.bad_role else
                                  "homelab-oce-recovery-publisher") + "/ci-123"}
        else:
            assert args[args.index("--expected-bucket-owner") + 1] == ACCOUNT
            if self.missing and operation in ("head-object", "get-object"):
                return subprocess.CompletedProcess(args, 1, b"")
            if operation == "get-bucket-versioning":
                response = {"Status": "Enabled"}
            elif operation == "get-bucket-encryption":
                response = {"ServerSideEncryptionConfiguration": {"Rules": [{
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "aws:kms", "KMSMasterKeyID": KMS_ALIAS},
                    "BucketKeyEnabled": True}]}}
            elif operation == "head-object":
                response = self.object_metadata()
            elif operation == "get-object":
                index = args.index("--range")
                range_value = args[index + 1]
                body = Path(args[index + 2])
                start, end = map(int, range_value.removeprefix("bytes=").split("-"))
                block = self.payload[start:end + 1]
                if self.corrupt and start == 0:
                    block = b"X" + block[1:]
                if not self.missing_body:
                    body.write_bytes(block)
                    body.chmod(0o644 if self.world_readable_body else 0o600)
                response = self.object_metadata()
                response.update({"ContentRange": f"bytes {start}-{end}/{len(self.payload)}",
                                 "ContentLength": len(block)})
            else:
                raise AssertionError(operation)
        return subprocess.CompletedProcess(args, 0, json.dumps(response).encode())

    def object_metadata(self):
        receipt = self.receipt
        return {"VersionId": receipt["versionId"],
                "ContentLength": len(self.payload),
                "ServerSideEncryption": "AES256" if self.no_kms else "aws:kms",
                "SSEKMSKeyId": KMS_KEY,
                "Metadata": {"source-sha": receipt["sourceSha"],
                             "backup-id": receipt["backupId"],
                             "material-sha256": receipt["materialSha256"],
                             "ciphertext-sha256": receipt["ciphertextSha256"]}}


class S3ProofTest(unittest.TestCase):
    def test_exact_version_is_read_back_in_bounded_ranges_without_promotion(self):
        receipt = source_receipt()
        fake = FakeAws(receipt)
        with mock.patch.object(PROOF, "PART_SIZE", 5):
            result = PROOF.verify_version(receipt, run=fake)
        self.assertEqual(result["scope"], "s3-version-readback")
        self.assertIs(result["publishable"], False)
        self.assertEqual(result["ciphertextSha256"], receipt["ciphertextSha256"])
        reads = [call for call in fake.calls if call[3:5] == ["s3api", "get-object"]]
        self.assertEqual(len(reads), 6)
        self.assertTrue(all("--version-id" in call for call in reads))
        self.assertTrue(all("--expected-bucket-owner" in call for call in reads))

    def test_missing_version_corrupt_bytes_kms_or_unsafe_body_blocks(self):
        receipt = source_receipt()
        for mutation in ("missing", "corrupt", "no_kms", "bad_role",
                         "missing_body", "world_readable_body"):
            with self.subTest(mutation=mutation):
                fake = FakeAws(receipt)
                setattr(fake, mutation, True)
                with self.assertRaises(PROOF.Blocked):
                    PROOF.verify_version(receipt, run=fake)

    def test_wrong_destination_size_version_or_ciphertext_digest_blocks(self):
        for field, value in (("bucket", "other-bucket"),
                             ("key", "openclaw-enterprise/new/other.tar.age"),
                             ("versionId", "missing-version"),
                             ("ciphertextBytes", len(PAYLOAD) + 1),
                             ("ciphertextSha256", "0" * 64)):
            with self.subTest(field=field):
                receipt = source_receipt()
                receipt[field] = value
                # The remote object stays bound to the original input.
                fake = FakeAws(source_receipt())
                with self.assertRaises(PROOF.Blocked):
                    PROOF.verify_version(receipt, run=fake)

    def test_rejects_promoted_or_unbounded_source_receipt(self):
        receipt = source_receipt()
        for field, value in (("publishable", True),
                             ("scope", "verified-restore"),
                             ("ciphertextBytes", 0),
                             ("versionId", "null"),
                             ("versionId", "-bad")):
            with self.subTest(field=field):
                altered = dict(receipt, **{field: value})
                with self.assertRaises(PROOF.Blocked):
                    PROOF.verify_version(altered, run=FakeAws(altered))

    def test_private_receipt_is_atomic_and_never_overwritten(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            path = Path(directory) / "receipt.json"
            proof = {"scope": "s3-version-readback", "publishable": False}
            PROOF._write_private_receipt(path, proof)
            self.assertEqual(json.loads(path.read_bytes()), proof)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                PROOF._write_private_receipt(path, {"publishable": True})
            self.assertEqual(json.loads(path.read_bytes()), proof)


if __name__ == "__main__":
    unittest.main()
