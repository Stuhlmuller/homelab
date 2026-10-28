#!/usr/bin/env python3
"""Offline failure fixtures for the dormant Enterprise ciphertext publisher."""

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
    "oce_s3_publisher_under_test", ROOT / "scripts/ci/openclaw-enterprise-s3-publish.py")
PUBLISH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISH)
ACCOUNT = PUBLISH.CHAIN.OFFSITE.read_inputs(
    ROOT / "IaC/application-backup-storage.hcl")["account_id"]
BUCKET = f"homelab-application-backups-{ACCOUNT}-us-east-1"
KEY_ALIAS = f"arn:aws:kms:us-east-1:{ACCOUNT}:alias/aws/s3"
KEY_ID = f"arn:aws:kms:us-east-1:{ACCOUNT}:key/11111111-1111-1111-1111-111111111111"
# Generated once with age 1.3.1 and an ephemeral test-only X25519 recipient.
# The private identity was discarded; no production recovery identity is involved.
PAYLOAD = (ROOT / "scripts/ci/fixtures/openclaw-enterprise/"
           "s3-publisher-fixture.tar.age").read_bytes()


def material():
    return {
        "scope": "source-only-material", "publishable": False,
        "sourceSha": "b" * 40, "backupId": "a" * 64,
        "materialSha256": "c" * 64, "markerSha256": "d" * 64,
        "installationId": "ins_123", "namespaceId": "ns_123",
        "agentId": "agt_123", "revisionId": "rev_123",
    }


class FakeAws:
    def __init__(self, ciphertext):
        self.ciphertext = ciphertext
        self.calls = []
        self.parts = []
        self.metadata = None
        self.object = None
        self.abort_count = 0
        self.bad_role = False
        self.bad_encryption = False
        self.bad_versioning = False
        self.fail_upload = False
        self.fail_complete = False
        self.unknown_complete = False
        self.corrupt_get = False
        self.mutate_source = False

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["stdin"] == subprocess.DEVNULL
        service, operation = args[3:5]
        if service == "sts":
            value = {"Account": ACCOUNT,
                     "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/" +
                            ("other" if self.bad_role else
                             "homelab-oce-recovery-publisher") + "/ci-123"}
        else:
            assert args[args.index("--expected-bucket-owner") + 1] == ACCOUNT
            if operation == "get-bucket-versioning":
                value = {"Status": "Suspended" if self.bad_versioning else "Enabled"}
            elif operation == "get-bucket-encryption":
                value = {"ServerSideEncryptionConfiguration": {"Rules": [{
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256" if self.bad_encryption else "aws:kms",
                        "KMSMasterKeyID": KEY_ALIAS},
                    "BucketKeyEnabled": True,
                }]}}
            elif operation == "list-object-versions":
                value = {"IsTruncated": False,
                         "Versions": ([{"Key": args[args.index("--prefix") + 1],
                                        "VersionId": "immutable-version-1"}]
                                      if self.object is not None else [])}
            elif operation == "create-multipart-upload":
                self.metadata = json.loads(args[args.index("--metadata") + 1])
                assert args[args.index("--server-side-encryption") + 1] == "aws:kms"
                assert args[args.index("--ssekms-key-id") + 1] == KEY_ALIAS
                value = {"UploadId": "upload-123"}
            elif operation == "upload-part":
                if self.fail_upload:
                    return subprocess.CompletedProcess(args, 1, b"")
                assert args[args.index("--upload-id") + 1] == "upload-123"
                body = Path(args[args.index("--body") + 1])
                assert body.stat().st_mode & 0o777 == 0o600
                self.parts.append(body.read_bytes())
                if self.mutate_source and len(self.parts) == 1:
                    self.ciphertext.write_bytes(b"X" * len(PAYLOAD))
                value = {"ETag": f'"part-{len(self.parts)}"'}
            elif operation == "complete-multipart-upload":
                assert args[args.index("--if-none-match") + 1] == "*"
                manifest = Path(args[args.index("--multipart-upload") + 1][7:])
                assert len(json.loads(manifest.read_text())["Parts"]) == len(self.parts)
                if self.fail_complete:
                    return subprocess.CompletedProcess(args, 1, b"")
                self.object = b"".join(self.parts)
                if self.unknown_complete:
                    return subprocess.CompletedProcess(args, 1, b"")
                value = {"VersionId": "immutable-version-1"}
            elif operation == "abort-multipart-upload":
                self.abort_count += 1
                value = {}
            elif operation == "head-object":
                assert self.object is not None
                value = self.object_metadata()
            elif operation == "get-object":
                assert self.object is not None
                assert args[args.index("--version-id") + 1] == "immutable-version-1"
                start, end = map(int, args[args.index("--range") + 1][6:].split("-"))
                chunk = self.object[start:end + 1]
                if self.corrupt_get:
                    chunk = b"X" + chunk[1:]
                body = Path(args[-1])
                body.write_bytes(chunk)
                body.chmod(0o600)
                value = self.object_metadata()
                value.update({"ContentRange": f"bytes {start}-{end}/{len(self.object)}",
                              "ContentLength": len(chunk)})
            else:
                raise AssertionError(operation)
        return subprocess.CompletedProcess(args, 0, json.dumps(value).encode())

    def object_metadata(self):
        return {"VersionId": "immutable-version-1",
                "ContentLength": len(self.object),
                "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": KEY_ID,
                "Metadata": self.metadata}


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.ciphertext = root / "ciphertext.tar.age"
        self.ciphertext.write_bytes(PAYLOAD)
        self.ciphertext.chmod(0o600)
        self.scratch = root / "scratch"
        self.scratch.mkdir(mode=0o700)
        self.aws = FakeAws(self.ciphertext)

    def publish(self):
        with mock.patch.object(PUBLISH, "PART_SIZE", 50), \
                mock.patch.object(PUBLISH.PROOF, "PART_SIZE", 4):
            return PUBLISH.publish_ciphertext(
                material(), self.ciphertext, self.scratch, run=self.aws)

    def test_multipart_exact_version_readback_is_unpublishable(self):
        result = self.publish()
        self.assertEqual(self.aws.object, PAYLOAD)
        self.assertEqual(result["scope"], "source-only-s3-publication")
        self.assertIs(result["publishable"], False)
        self.assertEqual(result["versionId"], "immutable-version-1")
        self.assertEqual(result["ciphertextSha256"], hashlib.sha256(PAYLOAD).hexdigest())
        self.assertEqual(len(self.aws.parts), 5)
        self.assertEqual(self.aws.abort_count, 0)
        self.assertTrue(any(call[3:5] == ["s3api", "get-object"]
                            for call in self.aws.calls))

    def test_existing_version_or_wrong_credential_context_blocks_before_write(self):
        for mutation in ("object", "bad_role", "bad_encryption", "bad_versioning"):
            with self.subTest(mutation=mutation):
                self.aws = FakeAws(self.ciphertext)
                setattr(self.aws, mutation, PAYLOAD if mutation == "object" else True)
                with self.assertRaises((PUBLISH.Blocked, PUBLISH.PROOF.Blocked)):
                    self.publish()
                self.assertFalse(any(call[3:5] == ["s3api", "create-multipart-upload"]
                                     for call in self.aws.calls))

    def test_upload_failure_changed_source_and_unknown_completion_fail_closed(self):
        for mutation in ("fail_upload", "mutate_source", "fail_complete",
                         "unknown_complete"):
            with self.subTest(mutation=mutation):
                self.ciphertext.write_bytes(PAYLOAD)
                self.aws = FakeAws(self.ciphertext)
                setattr(self.aws, mutation, True)
                with self.assertRaises(PUBLISH.Blocked):
                    self.publish()
                self.assertEqual(self.aws.abort_count, 1)
                if mutation == "unknown_complete":
                    with self.assertRaises(PUBLISH.Blocked):
                        self.publish()
                    self.assertEqual(sum(call[3:5] == ["s3api", "create-multipart-upload"]
                                         for call in self.aws.calls), 1)

    def test_corrupt_readback_never_returns_publication_receipt(self):
        self.aws.corrupt_get = True
        with self.assertRaises(PUBLISH.PROOF.Blocked):
            self.publish()
        self.assertEqual(self.aws.object, PAYLOAD)
        self.assertEqual(self.aws.abort_count, 0)
        with self.assertRaises(PUBLISH.Blocked):
            self.publish()

    def test_small_parts_fixture_can_reach_upload(self):
        with mock.patch.object(PUBLISH, "PART_SIZE", 1), \
                mock.patch.object(PUBLISH, "MAX_PARTS", 1000):
            result = PUBLISH.publish_ciphertext(
                material(), self.ciphertext, self.scratch, run=self.aws)
        self.assertEqual(result["ciphertextBytes"], len(PAYLOAD))
        self.assertEqual(len(self.aws.parts), len(PAYLOAD))

    def test_unsafe_inputs_and_part_limit_block_without_aws(self):
        for change in ("material", "source_mode", "scratch_mode", "too_many_parts",
                       "plaintext", "renamed", "truncated_age"):
            with self.subTest(change=change):
                self.aws = FakeAws(self.ciphertext)
                candidate = material()
                if change == "material":
                    candidate["publishable"] = True
                if change == "source_mode":
                    self.ciphertext.chmod(0o644)
                if change == "scratch_mode":
                    self.scratch.chmod(0o755)
                if change == "plaintext":
                    self.ciphertext.write_bytes(b"fixture-private-material-" * 12)
                if change == "truncated_age":
                    self.ciphertext.write_bytes(PAYLOAD[:100])
                source = self.ciphertext
                if change == "renamed":
                    source = self.ciphertext.with_suffix("")
                    self.ciphertext.rename(source)
                try:
                    with mock.patch.object(PUBLISH, "PART_SIZE", 1), \
                            mock.patch.object(PUBLISH, "MAX_PARTS", 2):
                        if change != "too_many_parts":
                            with mock.patch.object(PUBLISH, "MAX_PARTS", 1000):
                                with self.assertRaises(PUBLISH.Blocked):
                                    PUBLISH.publish_ciphertext(
                                        candidate, source, self.scratch,
                                        run=self.aws)
                        else:
                            with self.assertRaises(PUBLISH.Blocked):
                                PUBLISH.publish_ciphertext(
                                    candidate, source, self.scratch,
                                    run=self.aws)
                finally:
                    if change == "renamed":
                        source.rename(self.ciphertext)
                    self.ciphertext.write_bytes(PAYLOAD)
                    self.ciphertext.chmod(0o600)
                    self.scratch.chmod(0o700)
                self.assertEqual(self.aws.calls, [])


if __name__ == "__main__":
    unittest.main()
