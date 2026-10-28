#!/usr/bin/env python3
"""Offline fixtures for the protected platform recovery receipt publisher."""

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "platform_recovery_receipt_publish",
    ROOT / "scripts/platform-recovery-receipt-publish.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)

SHA = "a" * 40
ID = "e" * 32
SOURCE = f"homelab-etcd-backups-{publisher.ACCOUNT}-{publisher.REGION}"
TARGET = f"homelab-application-backups-{publisher.ACCOUNT}-{publisher.REGION}"


class FakeAWS:
    def __init__(self, source, target, objects):
        self.source, self.target = source, target
        self.objects = objects
        self.writes = []
        self.reads = []
        self.guard_checks = 0

    def check(self):
        return None

    def check_guard(self):
        self.guard_checks += 1

    def sole_version(self, bucket, key):
        return self.objects[(bucket, key)][0]

    def download(self, bucket, key, version, path, *, max_size):
        actual_version, content = self.objects[(bucket, key)]
        if version != actual_version or len(content) > max_size:
            raise ValueError("changed fixture object")
        path.write_bytes(content)
        path.chmod(0o600)
        self.reads.append(key)
        return hashlib.sha256(content).hexdigest()

    def write_once(self, key, content, directory, *, before_write):
        before_write()
        self.writes.append((key, json.loads(content)))


class PublisherTests(unittest.TestCase):
    def fixture(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        captured = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        source_time = now.isoformat()
        snapshot = b"synthetic snapshot fixture"
        snapshot_sha = hashlib.sha256(snapshot).hexdigest()
        snapshot_key = f"etcd/{snapshot_sha}/{ID}/etcd.snapshot"
        manifest_key = f"etcd/{snapshot_sha}/{ID}/manifest.json"
        integrity = {"bytes": len(snapshot), "sha256": snapshot_sha,
                     "embedded_sha256": "f" * 64}
        metadata = {"hash": "1234abcd", "revision": 4,
                    "total_keys": 2, "total_size": 100}
        manifest = {"format": 1, "snapshot": "etcd.snapshot",
                    "created_at": source_time, "source_node": "10.1.0.199",
                    "metadata": metadata, "integrity": integrity}
        manifest_bytes = (json.dumps(manifest) + "\n").encode()
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        restore = {"format": 1, "completed_at": source_time,
                   "validation": "offline-database-restore",
                   "control_plane_recovery_tested": False,
                   "source_unchanged": True, "restore_checksum_enabled": True,
                   "server_started": False, "source_integrity": integrity,
                   "snapshot_status": metadata,
                   "restored_status": {**metadata, "hash": "different"},
                   "tool": {"version": publisher.RESTORE.VERSION,
                            "platform": "darwin-arm64",
                            "archive_sha256": publisher.RESTORE.ARCHIVES["darwin-arm64"]}}
        restore_bytes = (json.dumps(restore) + "\n").encode()
        common = {"format": 1, "scope": "operator-local-candidate",
                  "verified": False, "sourceSha": SHA,
                  "capturedAt": captured, "targetBucket": TARGET}
        direct = {**common, "targetKey": f"{publisher.PREFIX}/{SHA}/direct-recovery.json",
                  "nodes": ["zimaboard-0", "zimaboard-1", "zimaboard-2", "acer"],
                  "endpoint": "10.1.0.199:50000",
                  "controlPlaneEndpoint": "10.1.0.199:50000",
                  "nodeAddresses": {"zimaboard-0": "10.1.0.200",
                                    "zimaboard-1": "10.1.0.201",
                                    "zimaboard-2": "10.1.0.202", "acer": "10.1.0.199"},
                  "nodeEndpoints": {"zimaboard-0": "10.1.0.200:50000",
                                    "zimaboard-1": "10.1.0.201:50000",
                                    "zimaboard-2": "10.1.0.202:50000",
                                    "acer": "10.1.0.199:50000"},
                  "transport": "direct-lan-authenticated-talos",
                  "talosMtls": True, "etcdStatusRead": True,
                  "directClusterHealth": True, "interface": "en0",
                  "sourceAddress": "10.1.0.50", "talosconfigSha256": "1" * 64}
        backup = {**common, "targetKey": f"{publisher.PREFIX}/{SHA}/off-node-etcd-backup.json",
                  "offNode": True, "offlineRestoreVerified": True,
                  "snapshotSha256": snapshot_sha,
                  "objectVersionId": "snapshot-version", "offsiteBucket": SOURCE,
                  "snapshotKey": snapshot_key, "manifestKey": manifest_key,
                  "manifestVersionId": "manifest-version",
                  "manifestSha256": manifest_sha,
                  "manifestBytes": len(manifest_bytes),
                  "snapshotBytes": len(snapshot),
                  "restoreReceiptSha256": hashlib.sha256(restore_bytes).hexdigest()}
        stage = f"platform-candidates/{SHA}/{ID}"
        objects = {
            (SOURCE, f"{stage}/direct-recovery.candidate.json"):
                ("direct-version", publisher.canonical(direct)),
            (SOURCE, f"{stage}/off-node-etcd-backup.candidate.json"):
                ("backup-version", publisher.canonical(backup)),
            (SOURCE, f"{stage}/offline-restore.receipt.json"):
                ("restore-version", restore_bytes),
            (SOURCE, snapshot_key): ("snapshot-version", snapshot),
            (SOURCE, manifest_key): ("manifest-version", manifest_bytes),
        }
        args = SimpleNamespace(expected_sha=SHA, candidate_id=ID,
                               direct_sha256=hashlib.sha256(
                                   publisher.canonical(direct)).hexdigest(),
                               backup_sha256=hashlib.sha256(
                                   publisher.canonical(backup)).hexdigest(),
                               restore_sha256=hashlib.sha256(restore_bytes).hexdigest())
        return args, FakeAWS(SOURCE, TARGET, objects), manifest

    def test_reviewed_exact_versions_publish_two_private_receipts(self):
        args, aws, manifest = self.fixture()
        with patch.object(publisher, "context") as context, \
             patch.object(publisher.OFFSITE.backup, "verify", return_value=manifest):
            self.assertTrue(publisher.promote(args, aws))
        self.assertGreaterEqual(context.call_count, 3)
        self.assertEqual(len(aws.writes), 2)
        self.assertTrue(all(value["verified"] is True for _, value in aws.writes))
        self.assertTrue(all(value["sourceSha"] == SHA for _, value in aws.writes))
        self.assertTrue(any(key.endswith("/etcd.snapshot") for key in aws.reads))
        self.assertGreaterEqual(aws.guard_checks, 4)

    def guard(self):
        resources = [f"arn:aws:s3:::{TARGET}/{publisher.PREFIX}/*/{name}.json"
                     for name in ("placement", *publisher.NAMES,
                                  "artifact-publication")]
        return {"Statement": [
            {"Sid": "DenyOtherPrerequisiteWriters", "Effect": "Deny",
             "Principal": "*", "Action": ["s3:PutObject"],
             "Resource": resources,
             "Condition": {"ArnNotEquals": {"aws:PrincipalArn":
                           f"arn:aws:iam::{publisher.ACCOUNT}:role/{publisher.ROLE}"}}},
            {"Sid": "DenyPrerequisiteDeletion", "Effect": "Deny",
             "Principal": "*", "Action": ["s3:DeleteObject", "s3:DeleteObjectVersion"],
             "Resource": resources},
        ]}

    def test_exact_live_bucket_guard_is_required(self):
        guard = self.guard()
        publisher.guarded_bucket_policy(guard, TARGET)
        for mutate in (
                lambda value: value["Statement"].pop(),
                lambda value: value["Statement"][0]["Condition"].update(
                    {"ArnNotEquals": {"aws:PrincipalArn": "arn:aws:iam::1:role/other"}}),
                lambda value: value["Statement"][1]["Action"].pop(),
                lambda value: value["Statement"][0]["Resource"].pop(),
                lambda value: value["Statement"][0].update({"Principal": {"AWS": "*"}}),
        ):
            changed = self.guard()
            mutate(changed)
            with self.subTest(changed=changed), self.assertRaisesRegex(
                    ValueError, "authoritative bucket guard"):
                publisher.guarded_bucket_policy(changed, TARGET)

    def test_malformed_candidate_type_fails_before_any_receipt_write(self):
        args, aws, manifest = self.fixture()
        key = (SOURCE, f"platform-candidates/{SHA}/{ID}/direct-recovery.candidate.json")
        aws.objects[key] = ("direct-version", b"[]\n")
        args.direct_sha256 = hashlib.sha256(b"[]\n").hexdigest()
        with patch.object(publisher, "context"), \
             patch.object(publisher.OFFSITE.backup, "verify", return_value=manifest):
            with self.assertRaisesRegex(ValueError, "must be an object"):
                publisher.promote(args, aws)
        self.assertEqual(aws.writes, [])

    def test_changed_manifest_version_fails_before_any_receipt_write(self):
        args, aws, manifest = self.fixture()
        key = next(key for key in aws.objects if key[1].endswith("/manifest.json"))
        aws.objects[key] = ("unexpected-version", aws.objects[key][1])
        with patch.object(publisher, "context"), \
             patch.object(publisher.OFFSITE.backup, "verify", return_value=manifest):
            with self.assertRaisesRegex(ValueError, "exact versions differ"):
                publisher.promote(args, aws)
        self.assertEqual(aws.writes, [])

    def test_ambient_git_selector_fails_before_remote_check(self):
        with patch.dict(os.environ, {"GIT_DIR": "/tmp/other"}):
            with patch.object(publisher, "quiet") as quiet:
                with self.assertRaisesRegex(ValueError, "protected main changed"):
                    publisher.current_main(SHA)
                quiet.assert_not_called()

    def test_wrong_origin_fails_before_main_query(self):
        with patch.object(publisher, "quiet", side_effect=[str(publisher.ROOT),
                                                          "https://evil.example/repo.git"]) as quiet:
            with self.assertRaisesRegex(ValueError, "protected main changed"):
                publisher.current_main(SHA)
            self.assertEqual(quiet.call_count, 2)

    def test_non_object_restore_fails_closed(self):
        args, aws, manifest = self.fixture()
        key = (SOURCE, f"platform-candidates/{SHA}/{ID}/offline-restore.receipt.json")
        aws.objects[key] = ("restore-version", b"[]\n")
        args.restore_sha256 = hashlib.sha256(b"[]\n").hexdigest()
        with patch.object(publisher, "context"), \
             patch.object(publisher.OFFSITE.backup, "verify", return_value=manifest):
            with self.assertRaisesRegex(ValueError, "must be an object"):
                publisher.promote(args, aws)
        self.assertEqual(aws.writes, [])

    def test_malformed_nested_restore_fails_before_publication(self):
        args, aws, manifest = self.fixture()
        key = (SOURCE, f"platform-candidates/{SHA}/{ID}/offline-restore.receipt.json")
        restore = json.loads(aws.objects[key][1])
        restore["restored_status"] = []
        content = (json.dumps(restore) + "\n").encode()
        aws.objects[key] = ("restore-version", content)
        args.restore_sha256 = hashlib.sha256(content).hexdigest()
        backup_key = (SOURCE, f"platform-candidates/{SHA}/{ID}/off-node-etcd-backup.candidate.json")
        backup = json.loads(aws.objects[backup_key][1])
        backup["restoreReceiptSha256"] = args.restore_sha256
        aws.objects[backup_key] = ("backup-version", publisher.canonical(backup))
        args.backup_sha256 = hashlib.sha256(aws.objects[backup_key][1]).hexdigest()
        with patch.object(publisher, "context"), \
             patch.object(publisher.OFFSITE.backup, "verify", return_value=manifest):
            with self.assertRaisesRegex(ValueError, "malformed"):
                publisher.promote(args, aws)
        self.assertEqual(aws.writes, [])


if __name__ == "__main__":
    unittest.main()
