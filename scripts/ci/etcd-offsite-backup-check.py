#!/usr/bin/env python3
"""Exercise publication/retrieval failures without AWS access or real snapshot data."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "offsite", Path(__file__).resolve().parents[1] / "etcd-offsite-backup.py"
)
offsite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offsite)


class PublicationFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.output = self.root / "output"
        self.source.mkdir(mode=0o700)
        self.output.mkdir(mode=0o700)
        data = b"synthetic etcd bytes".ljust(4096, b"\0")
        self.snapshot = self.source / offsite.FILES[0]
        self.snapshot.write_bytes(data + hashlib.sha256(data).digest())
        self.snapshot.chmod(0o600)
        record = {"format": 1, "snapshot": offsite.FILES[0],
                  "metadata": {"hash": "0123abcd", "revision": 42,
                               "total_keys": 7, "total_size": 4096},
                  "integrity": offsite.backup.snapshot_digest(self.snapshot)}
        manifest = self.source / offsite.FILES[1]
        manifest.write_text(json.dumps(record))
        manifest.chmod(0o600)
        self.tool = self.root / "aws"
        self.tool.write_text("not executed; mocked client")
        self.tool.chmod(0o700)
        self.target = offsite.destination()
        self.aws = offsite.AWS(self.tool, "default", self.target)
        self.remote = {}
        self.calls = []
        self.account = self.target["account_id"]
        self.versioning = "Enabled"
        self.fail_operation = None
        self.lose_put_response = False
        self.corrupt_download = False
        self.wrong_returned_version = False
        self.fail_manifest = False
        self.after_get = None
        context = patch.object(offsite.subprocess, "run", side_effect=self.client)
        context.start()
        self.addCleanup(context.stop)

    def metadata(self, version, data):
        return {"VersionId": version, "ContentLength": len(data),
                "ChecksumSHA256": offsite.checksum({"sha256": hashlib.sha256(data).hexdigest()}),
                "ServerSideEncryption": "aws:kms", "BucketKeyEnabled": True}

    def client(self, command, **kwargs):
        self.assertEqual(command[0], str(self.tool))
        self.assertFalse(any(k.startswith("AWS_") for k in kwargs["env"]))
        self.assertEqual(kwargs["timeout"], 600)
        service = "s3api" if "s3api" in command else "sts"
        index = command.index(service)
        operation, args = command[index + 1], command[index + 2:]
        self.calls.append((operation, args))
        self.assertEqual(command[command.index("--profile") + 1], "default")
        self.assertEqual(command[command.index("--region") + 1], "us-east-1")
        host = "s3" if service == "s3api" else "sts"
        self.assertEqual(command[command.index("--endpoint-url") + 1],
                         f"https://{host}.us-east-1.amazonaws.com")
        if service == "s3api":
            self.assertEqual(args[args.index("--bucket") + 1], self.target["bucket"])
            self.assertEqual(args[args.index("--expected-bucket-owner") + 1], self.account)
        if operation == self.fail_operation:
            return subprocess.CompletedProcess(command, 1, "", "PRIVATE AWS DIAGNOSTICS (403)")
        if operation == "get-caller-identity":
            value = {"Account": self.account}
        elif operation == "get-bucket-versioning":
            value = {"Status": self.versioning}
        elif operation in ("head-object", "get-object"):
            key = args[args.index("--key") + 1]
            values = self.remote.get(key, {})
            if not values:
                return subprocess.CompletedProcess(command, 1, "", "An error occurred (404)")
            version = args[args.index("--version-id") + 1] if "--version-id" in args else next(reversed(values))
            data = values[version]
            value = self.metadata(version, data)
            if operation == "get-object":
                self.assertIn("--version-id", args)
                self.assertEqual(args[args.index("--checksum-mode") + 1], "ENABLED")
                with Path(args[-1]).open("xb") as output:
                    output.write(b"changed" if self.corrupt_download else data)
                if self.after_get:
                    self.after_get()
            if self.wrong_returned_version:
                value["VersionId"] = "wrong-version"
        elif operation == "put-object":
            key = args[args.index("--key") + 1]
            if self.fail_manifest and key.endswith("/manifest.json"):
                return subprocess.CompletedProcess(command, 1, "", "(403) AccessDenied")
            self.assertEqual(args[args.index("--if-none-match") + 1], "*")
            self.assertEqual(args[args.index("--server-side-encryption") + 1], "aws:kms")
            self.assertIn("--bucket-key-enabled", args)
            body = args[args.index("--body") + 1]
            self.assertFalse(body.startswith(("file://", "fileb://")))
            data = Path(body).read_bytes()
            version = f"version-{len(self.remote) + 1}"
            value = self.metadata(version, data)
            self.assertEqual(args[args.index("--checksum-sha256") + 1], value["ChecksumSHA256"])
            if key in self.remote:
                return subprocess.CompletedProcess(command, 1, "", "(412) PreconditionFailed")
            self.remote[key] = {version: data}
            if self.lose_put_response:
                self.lose_put_response = False
                raise subprocess.TimeoutExpired(command, 600)
        else:
            self.fail(f"unexpected mutation or enumeration: {operation}")
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

    def publish(self, resume=None):
        return offsite.publish(self.source, self.output, self.aws, resume)

    def publication(self):
        return next(self.output.glob("publication-*"))


class PublicationTests(PublicationFixture):
    def test_publishes_snapshot_then_manifest_and_verifies_download(self):
        original = self.snapshot.read_bytes()
        publication, downloaded = self.publish()
        value = json.loads((publication / offsite.RECEIPT).read_text())
        self.assertEqual(value["status"], "verified")
        self.assertEqual(self.snapshot.read_bytes(), original)
        self.assertEqual(offsite.backup.verify(downloaded), offsite.backup.verify(self.source))
        puts = [args[args.index("--key") + 1].split("/")[-1]
                for name, args in self.calls if name == "put-object"]
        self.assertEqual(puts, list(offsite.FILES))
        for directory in (publication, downloaded):
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            for path in directory.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_ambiguous_success_resumes_without_overwriting(self):
        self.lose_put_response = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.publish()
        publication = self.publication()
        self.assertEqual(len(self.remote), 1)
        self.publish(publication)
        self.assertEqual(len(self.remote), 2)
        self.assertEqual(sum(op == "put-object" for op, _ in self.calls), 2)
        self.assertEqual(json.loads((publication / offsite.RECEIPT).read_text())["status"], "verified")

    def test_partial_publication_retains_receipt_and_original(self):
        self.fail_operation = "get-object"
        with self.assertRaises(ValueError):
            self.publish()
        publication = self.publication()
        self.assertEqual(json.loads((publication / offsite.RECEIPT).read_text())["status"], "published")
        self.assertTrue(list(self.output.glob(".partial-retrieval-*")))
        offsite.backup.verify(self.source)
        self.fail_operation = None
        self.publish(publication)
        self.assertEqual(sum(op == "put-object" for op, _ in self.calls), 2)

    def test_failed_manifest_leaves_snapshot_and_resumes_only_missing_object(self):
        self.fail_manifest = True
        with self.assertRaises(ValueError):
            self.publish()
        publication = self.publication()
        record = json.loads((publication / offsite.RECEIPT).read_text())
        self.assertEqual(record["status"], "incomplete")
        self.assertIsNotNone(record["objects"][offsite.FILES[0]]["version_id"])
        self.assertIsNone(record["objects"][offsite.FILES[1]]["version_id"])
        self.assertEqual(len(self.remote), 1)
        self.fail_manifest = False
        self.publish(publication)
        snapshot_puts = [args for op, args in self.calls if op == "put-object"
                         and args[args.index("--key") + 1].endswith("/etcd.snapshot")]
        self.assertEqual(len(snapshot_puts), 1)

    def test_wrong_account_or_unversioned_bucket_never_uploads(self):
        self.account = "000000000000"
        with self.assertRaisesRegex(ValueError, "account"):
            self.publish()
        self.assertEqual([op for op, _ in self.calls], ["get-caller-identity"])
        self.account = self.target["account_id"]
        self.versioning = "Suspended"
        with self.assertRaisesRegex(ValueError, "versioning"):
            self.publish()
        self.assertFalse(self.remote)

    def test_changed_source_or_copy_rejected_before_resume_network(self):
        self.lose_put_response = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.publish()
        publication = self.publication()
        before = len(self.calls)
        (publication / offsite.FILES[0]).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.publish(publication)
        self.assertEqual(len(self.calls), before)
        self.snapshot.write_bytes(b"changed original")
        with self.assertRaises(ValueError):
            self.publish(publication)
        self.assertEqual(len(self.calls), before)

    def test_existing_different_object_is_never_overwritten(self):
        self.lose_put_response = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.publish()
        key = next(iter(self.remote))
        self.remote[key]["external-version"] = b"different bytes"
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.publish(self.publication())
        self.assertEqual(sum(op == "put-object" for op, _ in self.calls), 1)

    def test_receipt_only_retrieval_uses_recorded_versions_even_when_latest_changed(self):
        publication, _ = self.publish()
        receipt_only = self.root / "receipt-only"
        receipt_only.mkdir(mode=0o700)
        shutil.copyfile(publication / offsite.RECEIPT, receipt_only / offsite.RECEIPT)
        (receipt_only / offsite.RECEIPT).chmod(0o600)
        for versions in self.remote.values():
            versions["external-latest"] = b"different bytes"
        result = offsite.retrieve(receipt_only, self.output, self.aws)
        self.assertEqual(offsite.backup.verify(result), offsite.backup.verify(self.source))
        self.assertEqual(len(list(receipt_only.iterdir())), 1)

    def test_corrupt_download_and_wrong_version_never_report_verification(self):
        self.corrupt_download = True
        with self.assertRaisesRegex(ValueError, "downloaded bytes"):
            self.publish()
        publication = self.publication()
        self.assertEqual(json.loads((publication / offsite.RECEIPT).read_text())["status"], "published")
        self.corrupt_download = False
        self.wrong_returned_version = True
        with self.assertRaisesRegex(ValueError, "version"):
            offsite.retrieve(publication, self.output, self.aws)

    def test_invalid_receipt_cannot_choose_other_keys_or_unversioned_downloads(self):
        publication, _ = self.publish()
        path = publication / offsite.RECEIPT
        record = json.loads(path.read_text())
        before = len(self.calls)
        for change in ({"prefix": "unrelated/prefix"}, {"destination": {}}, {"id": "../path"}):
            path.write_text(json.dumps(record | change))
            with self.assertRaises(ValueError):
                offsite.retrieve(publication, self.output, self.aws)
        record["objects"][offsite.FILES[0]]["version_id"] = None
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "immutable"):
            offsite.retrieve(publication, self.output, self.aws)
        self.assertEqual(len(self.calls), before)

    def test_exported_credentials_and_endpoints_are_ignored(self):
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "unused", "AWS_ENDPOINT_URL": "unused",
                                     "AWS_PROFILE": "unused", "AWS_CONFIG_FILE": "unused"}):
            client = offsite.AWS(self.tool, "default", self.target)
        self.assertFalse(any(k.startswith("AWS_") for k in client.environment))
        client.check()

    def test_private_paths_required(self):
        self.output.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "0700"):
            self.publish()
        self.assertFalse(self.calls)
        self.output.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "outside"):
            offsite.publish(self.source, self.source, self.aws)

    def test_changed_receipt_during_retrieval_does_not_publish_success(self):
        publication, _ = self.publish()
        original_downloads = list(self.output.glob("retrieval-*"))
        def change_receipt():
            path = publication / offsite.RECEIPT
            record = json.loads(path.read_text())
            record["verified_at"] = "changed concurrently"
            path.write_text(json.dumps(record))
        self.after_get = change_receipt
        with self.assertRaisesRegex(ValueError, "changed during retrieval"):
            offsite.retrieve(publication, self.output, self.aws)
        self.assertEqual(list(self.output.glob("retrieval-*")), original_downloads)

    def test_copy_or_initial_parent_sync_failure_prevents_all_network(self):
        with patch.object(offsite, "sync_file", side_effect=OSError("file sync failed")):
            with self.assertRaises(OSError):
                self.publish()
        self.assertFalse(self.calls)
        original = offsite.backup.sync_directory
        def fail_parent(path):
            if path == self.output:
                raise OSError("parent sync failed")
            original(path)
        with patch.object(offsite.backup, "sync_directory", side_effect=fail_parent):
            with self.assertRaises(OSError):
                self.publish()
        self.assertFalse(self.calls)
        offsite.backup.verify(self.source)

    def test_download_sync_failure_preserves_published_receipt_without_verified_output(self):
        original = offsite.sync_file
        def fail_download(path):
            if path.parent.name.startswith(".partial-retrieval-"):
                raise OSError("download sync failed")
            original(path)
        with patch.object(offsite, "sync_file", side_effect=fail_download):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(json.loads((self.publication() / offsite.RECEIPT).read_text())["status"], "published")
        self.assertFalse(list(self.output.glob("retrieval-*")))
        self.assertTrue(list(self.output.glob(".partial-retrieval-*")))

    def test_resume_repeats_failed_publication_parent_sync_before_network(self):
        original = offsite.backup.sync_directory
        def fail_parent(path):
            if path == self.output:
                raise OSError("parent remains unavailable")
            original(path)
        other_output = self.root / "another-output"
        other_output.mkdir(mode=0o700)
        with patch.object(offsite.backup, "sync_directory", side_effect=fail_parent):
            with self.assertRaises(OSError):
                self.publish()
            with self.assertRaises(OSError):
                offsite.publish(self.source, other_output, self.aws, self.publication())
        self.assertFalse(self.calls)
        offsite.backup.verify(self.source)


if __name__ == "__main__":
    unittest.main()
