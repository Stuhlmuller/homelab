#!/usr/bin/env python3
"""Exercise exact-version off-node proof without credentials or cluster access."""

import base64
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "platform_etcd_prerequisite", ROOT / "scripts/platform-etcd-prerequisite.py")
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)


class SourceBucket(producer.S3Reader):
    def __init__(self, snapshot, manifest, prefix):
        self.target = producer.offsite.destination()
        self.prefix = prefix
        self.objects = {prefix + "etcd.snapshot": snapshot,
                        prefix + "manifest.json": manifest}
        self.version = {name: "version-" + str(index)
                        for index, name in enumerate(self.objects, 1)}
        self.extra_version = False
        self.delete_marker = False
        self.corrupt_download = False
        self.corrupt_head = False
        self.calls = []

    def call(self, service, operation, arguments=()):
        self.calls.append((service, operation, tuple(arguments)))
        if operation == "get-caller-identity":
            return {"Account": self.target["account_id"]}
        if operation == "get-bucket-versioning":
            return {"Status": "Enabled"}
        if operation == "get-bucket-encryption":
            return {"ServerSideEncryptionConfiguration": {"Rules": [
                {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]}}
        if operation == "list-object-versions":
            rows = [{"Key": key, "VersionId": version, "IsLatest": True,
                     "Size": len(self.objects[key])}
                    for key, version in self.version.items()]
            if self.extra_version:
                rows.append({"Key": rows[0]["Key"], "VersionId": "old",
                             "IsLatest": False, "Size": rows[0]["Size"]})
            return {"IsTruncated": False, "Versions": rows,
                    "DeleteMarkers": [{"Key": rows[0]["Key"]}] if self.delete_marker else []}
        if operation in ("head-object", "get-object"):
            key = arguments[arguments.index("--key") + 1]
            version = arguments[arguments.index("--version-id") + 1]
            self.assert_get(key, version, arguments)
            content = self.objects[key]
            if operation == "get-object":
                Path(arguments[-1]).write_bytes(
                    content[:-1] + b"X" if self.corrupt_download else content)
            return {"VersionId": version, "ContentLength": len(content),
                    "ChecksumSHA256": "invalid" if self.corrupt_head and operation == "head-object"
                    else base64.b64encode(hashlib.sha256(content).digest()).decode(),
                    "ServerSideEncryption": "aws:kms", "BucketKeyEnabled": True}
        raise AssertionError(f"unreviewed AWS operation: {operation}")

    def assert_get(self, key, version, arguments):
        if key not in self.objects or version != self.version[key] or "ENABLED" not in arguments:
            raise AssertionError("download was not bound to an exact reviewed version")


class PlatformEtcdPrerequisite(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        self.output.chmod(0o700)
        payload = b"snapshot database".ljust(512, b"\0")
        self.snapshot = payload + hashlib.sha256(payload).digest()
        self.snapshot_sha = hashlib.sha256(self.snapshot).hexdigest()
        self.publication_id = "b" * 32
        self.prefix = f"etcd/{self.snapshot_sha}/{self.publication_id}/"
        integrity = {"bytes": len(self.snapshot), "sha256": self.snapshot_sha,
                     "embedded_sha256": hashlib.sha256(payload).hexdigest()}
        self.manifest = {"format": 1, "snapshot": "etcd.snapshot",
                         "created_at": datetime.now(timezone.utc).isoformat(),
                         "source_node": producer.backup.CONTROL_PLANE,
                         "metadata": {"hash": "00000001", "revision": 1,
                                      "total_keys": 1, "total_size": 512},
                         "integrity": integrity}
        self.reader = self.make_reader()

    def make_reader(self):
        return SourceBucket(self.snapshot, json.dumps(self.manifest).encode(), self.prefix)

    def restore_proof(self, source, _destination, _archive):
        integrity = producer.backup.verify(source)["integrity"]
        return source, {"validation": "offline-database-restore",
                        "source_integrity": integrity,
                        "restore_checksum_enabled": True,
                        "source_unchanged": True,
                        "control_plane_recovery_tested": False,
                        "server_started": False,
                        "snapshot_status": {"revision": 1, "total_keys": 1},
                        "restored_status": {"revision": 1, "total_keys": 1}}

    def stage(self):
        with patch.object(producer, "reviewed_context"), \
                patch.object(producer.offline, "restore_check", side_effect=self.restore_proof):
            return producer.stage("a" * 40, self.snapshot_sha, self.publication_id,
                                  Path("/unused/pinned-etcd-archive"), self.output, self.reader)

    def test_stages_only_after_exact_version_download_and_offline_restore(self):
        receipt = self.stage()
        value = producer.platform.read_private_json(receipt)
        self.assertEqual(value["snapshotSha256"], self.snapshot_sha)
        self.assertEqual(value["objectVersionId"], self.reader.version[self.prefix + "etcd.snapshot"])
        self.assertEqual(value["manifestVersionId"], self.reader.version[self.prefix + "manifest.json"])
        self.assertEqual(value["sourceSha"], "a" * 40)
        self.assertTrue(value["offlineRestoreVerified"])
        self.assertFalse(value["controlPlaneRecoveryTested"])
        self.assertEqual(len([call for call in self.reader.calls if call[1] == "get-object"]), 2)
        self.assertEqual(len([call for call in self.reader.calls if call[1] == "head-object"]), 2)
        self.assertFalse(any(call[1] == "put-object" for call in self.reader.calls))
        self.assertEqual(list(self.output.glob("off-node-etcd-evidence-*")), [])

    def test_ambiguous_or_deleted_s3_history_fails_before_download(self):
        for field in ("extra_version", "delete_marker"):
            with self.subTest(field=field):
                self.reader = self.make_reader()
                setattr(self.reader, field, True)
                with self.assertRaisesRegex(ValueError, "ambiguous"):
                    self.stage()
                self.assertFalse(any(call[1] == "get-object" for call in self.reader.calls))
                self.assertFalse((self.output / producer.RECEIPT).exists())

    def test_changed_s3_bytes_fail_before_restore(self):
        self.reader.corrupt_download = True
        with patch.object(producer, "reviewed_context"), \
                patch.object(producer.offline, "restore_check") as restore, \
                self.assertRaisesRegex(ValueError, "readback differs"):
            producer.stage("a" * 40, self.snapshot_sha, self.publication_id,
                           Path("/unused"), self.output, self.reader)
        restore.assert_not_called()
        self.assertEqual(list(self.output.glob("off-node-etcd-evidence-*")), [])

    def test_bad_head_metadata_fails_before_download(self):
        self.reader.corrupt_head = True
        with self.assertRaisesRegex(ValueError, "HEAD metadata differs"):
            self.stage()
        self.assertFalse(any(call[1] == "get-object" for call in self.reader.calls))

    def test_oversized_manifest_fails_before_download(self):
        self.reader.objects[self.prefix + "manifest.json"] = b"x" * (1048576 + 1)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.stage()
        self.assertFalse(any(call[1] == "get-object" for call in self.reader.calls))

    def test_stale_or_wrong_source_fails_without_receipt(self):
        for field, value in (("created_at", "2000-01-01T00:00:00+00:00"),
                             ("source_node", "zimaboard-0")):
            with self.subTest(field=field):
                changed = dict(self.manifest, **{field: value})
                self.reader = SourceBucket(self.snapshot, json.dumps(changed).encode(), self.prefix)
                with patch.object(producer.offline, "restore_check") as restore, \
                        self.assertRaises(ValueError):
                    self.stage()
                restore.assert_not_called()
                self.assertFalse((self.output / producer.RECEIPT).exists())

    def test_unverified_restore_fails_without_receipt(self):
        proof = self.restore_proof
        def unverified(source, destination, archive):
            path, value = proof(source, destination, archive)
            value["restored_status"]["revision"] = 2
            return path, value
        with patch.object(producer, "reviewed_context"), \
                patch.object(producer.offline, "restore_check", side_effect=unverified), \
                self.assertRaisesRegex(ValueError, "incomplete"):
            producer.stage("a" * 40, self.snapshot_sha, self.publication_id,
                           Path("/unused"), self.output, self.reader)
        self.assertFalse((self.output / producer.RECEIPT).exists())

    def test_reviewed_context_rejects_stale_main(self):
        sha = "a" * 40
        def git(command, **_kwargs):
            if command[1] == "rev-parse":
                return subprocess.CompletedProcess(command, 0, sha + "\n", "")
            if command[1] == "status":
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[1] == "show":
                relative = command[2].split(":", 1)[1]
                return subprocess.CompletedProcess(command, 0,
                                                   (ROOT / relative).read_bytes(), b"")
            if command[1] == "ls-remote":
                return subprocess.CompletedProcess(command, 0,
                                                   "b" * 40 + "\trefs/heads/main\n", "")
            raise AssertionError(command)
        with patch.dict(producer.os.environ, {"GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                                             "GITHUB_EVENT_NAME": "workflow_dispatch"}), \
                patch.object(producer.platform, "protected_context"), \
                patch.object(producer.platform, "require_reviewed_execution_config",
                             return_value=b"{}"), \
                patch.object(producer.platform, "validate_config"), \
                patch.object(producer.subprocess, "run", side_effect=git), \
                self.assertRaisesRegex(ValueError, "no longer current main"):
            producer.reviewed_context(sha)

    def test_reviewed_context_rejects_untracked_and_changed_helper(self):
        sha = "a" * 40
        def git(command, **_kwargs):
            if command[1] == "rev-parse":
                return subprocess.CompletedProcess(command, 0, sha + "\n", "")
            if command[1] == "status":
                self.assertIn("--untracked-files=all", command)
                return subprocess.CompletedProcess(command, 0, "?? scripts/unreviewed.py\n", "")
            raise AssertionError("source check should stop before any further operation")
        with patch.dict(producer.os.environ, {"GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                                             "GITHUB_EVENT_NAME": "workflow_dispatch"}), \
                patch.object(producer.platform, "protected_context"), \
                patch.object(producer.platform, "require_reviewed_execution_config",
                             return_value=b"{}"), \
                patch.object(producer.platform, "validate_config"), \
                patch.object(producer.subprocess, "run", side_effect=git), \
                self.assertRaisesRegex(ValueError, "source differs"):
            producer.reviewed_context(sha)

        def changed_helper(command, **_kwargs):
            if command[1] == "rev-parse":
                return subprocess.CompletedProcess(command, 0, sha + "\n", "")
            if command[1] == "status":
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[1] == "show":
                return subprocess.CompletedProcess(command, 0, b"changed", b"")
            raise AssertionError("changed helper should stop before remote main check")
        with patch.dict(producer.os.environ, {"GITHUB_REPOSITORY": "Stuhlmuller/homelab",
                                             "GITHUB_EVENT_NAME": "workflow_dispatch"}), \
                patch.object(producer.platform, "protected_context"), \
                patch.object(producer.platform, "require_reviewed_execution_config",
                             return_value=b"{}"), \
                patch.object(producer.platform, "validate_config"), \
                patch.object(producer.subprocess, "run", side_effect=changed_helper), \
                self.assertRaisesRegex(ValueError, "helper differs"):
            producer.reviewed_context(sha)

    def test_reader_rejects_unreviewed_aws_mutation(self):
        reader = producer.S3Reader()
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            reader.call("s3api", "put-object")


if __name__ == "__main__":
    unittest.main()
