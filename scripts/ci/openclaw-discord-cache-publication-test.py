#!/usr/bin/env python3
"""Exercise immutable S3 publication and fail-closed reader transfer boundaries."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = load(ROOT / "scripts/openclaw-discord-offline-cache.py", "discord_builder")
PUBLICATION = load(ROOT / "scripts/ci/openclaw-discord-cache-publication.py", "discord_publication")


def bundle(directory):
    directory.mkdir()
    tar = directory / "npm-cache.tar"
    with tarfile.open(tar, "w") as output:
        item = tarfile.TarInfo("_cacache/content")
        item.size = 5
        output.addfile(item, io.BytesIO(b"cache"))
    lock = {"packages": {"node_modules/@openclaw/discord": {
        "version": "2026.9.5", "integrity": BUILDER.INTEGRITY}}}
    lock_path = directory / "dependency-lock.json"
    lock_path.write_text(json.dumps(lock))
    manifest = {"schema": 1, "image": BUILDER.IMAGE, "platform": "linux/amd64",
                "package": BUILDER.SPEC, "npm_integrity": BUILDER.INTEGRITY,
                "cache_sha256": PUBLICATION.digest(tar),
                "dependency_lock_sha256": PUBLICATION.digest(lock_path),
                "validation": "fresh-state-network-none-install-and-runtime-inspect"}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    BUILDER.verify_bundle(directory, ROOT)


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.corrupt = False
        self.ambiguous = False

    def __call__(self, operation, *arguments):
        def option(name):
            return arguments[arguments.index(name) + 1]

        key = option("--key") if "--key" in arguments else (
            option("--prefix") if "--prefix" in arguments else None)
        version = option("--version-id") if "--version-id" in arguments else "v1"
        if operation == "list-object-versions":
            if key in self.objects:
                versions = [{"Key": key, "VersionId": "v1", "Size": len(self.objects[key])}]
                if self.ambiguous:
                    versions.append({"Key": key, "VersionId": "v2", "Size": len(self.objects[key])})
            else:
                versions = []
            return {"IsTruncated": False, "Versions": versions, "DeleteMarkers": []}
        if operation == "put-object":
            if key in self.objects or option("--if-none-match") != "*":
                raise ValueError("overwrite refused")
            self.objects[key] = Path(option("--body")).read_bytes()
            self.writes.append(key)
            return {"VersionId": "v1"}
        if operation == "head-object":
            if version != "v1":
                raise ValueError("wrong version")
            return {"VersionId": version, "ContentLength": len(self.objects[key]),
                    "ServerSideEncryption": "aws:kms"}
        if operation == "get-object":
            if version != "v1":
                raise ValueError("wrong version")
            body = self.objects[key]
            if self.corrupt and key.endswith("npm-cache.tar"):
                body = body[:-1] + bytes([body[-1] ^ 1])
            Path(arguments[-1]).write_bytes(body)
            return {"VersionId": version, "ContentLength": len(self.objects[key])}
        raise ValueError("unexpected S3 operation")


class Publication(unittest.TestCase):
    def test_bucket_and_reader_identity_are_fixed(self):
        with mock.patch.object(PUBLICATION, "aws", side_effect=lambda operation, *args: (
                {"Status": "Enabled"} if operation == "get-bucket-versioning" else
                {"ServerSideEncryptionConfiguration": {"Rules": [{
                    "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]}})):
            PUBLICATION.check_bucket("homelab-application-backups-716182248480-us-east-1")
            with self.assertRaisesRegex(ValueError, "unreviewed"):
                PUBLICATION.check_bucket("other-bucket")
        pod = {"metadata": {"uid": "00000000-0000-0000-0000-000000000001"},
               "status": {"phase": "Running"}, "spec": {
                   "securityContext": {"runAsUser": 1000},
                   "automountServiceAccountToken": False,
                   "containers": [{"name": "reader", "image": BUILDER.IMAGE}]}}
        with mock.patch.object(PUBLICATION, "call", return_value=json.dumps(pod).encode()):
            PUBLICATION.reader_context("openclaw-retirement-reader-test",
                                       pod["metadata"]["uid"], BUILDER)
        for changed in ({"metadata": {"uid": "changed"}},
                        {"spec": {**pod["spec"], "securityContext": {"runAsUser": 0}}},
                        {"spec": {**pod["spec"], "containers": [{"name": "reader",
                                                                   "image": "unreviewed"}]}}):
            altered = {**pod, **changed}
            with mock.patch.object(PUBLICATION, "call", return_value=json.dumps(altered).encode()):
                with self.assertRaisesRegex(ValueError, "identity changed"):
                    PUBLICATION.reader_context("openclaw-retirement-reader-test",
                                               pod["metadata"]["uid"], BUILDER)

    def test_bundle_rejects_tampering_and_tar_links(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch) / "bundle"
            bundle(directory)
            (directory / "npm-cache.tar").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "digest"):
                BUILDER.verify_bundle(directory, ROOT)
            bundle_dir = Path(scratch) / "second"
            bundle(bundle_dir)
            tar = bundle_dir / "npm-cache.tar"
            with tarfile.open(tar, "w") as output:
                item = tarfile.TarInfo("_cacache/escape")
                item.type = tarfile.SYMTYPE
                item.linkname = "/private/state"
                output.addfile(item)
            manifest = json.loads((bundle_dir / "manifest.json").read_text())
            manifest["cache_sha256"] = PUBLICATION.digest(tar)
            (bundle_dir / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "unsafe"):
                BUILDER.verify_bundle(bundle_dir, ROOT)
            with tarfile.open(tar, "w"):
                pass
            manifest["cache_sha256"] = PUBLICATION.digest(tar)
            (bundle_dir / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "no package content"):
                BUILDER.verify_bundle(bundle_dir, ROOT)

    def test_publish_and_transfer_bind_exact_versions_before_reader_write(self):
        sha = "a" * 40
        ref = sha + "/123"
        store = FakeS3()
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch) / "bundle"
            bundle(directory)
            with mock.patch.object(PUBLICATION, "aws", side_effect=store), \
                    mock.patch.object(PUBLICATION, "check_bucket"):
                self.assertEqual(PUBLICATION.publish("bucket", sha, "123", directory), ref)
                self.assertEqual([key.rsplit("/", 1)[-1] for key in store.writes],
                                 [*PUBLICATION.NAMES, "final.json"])
                with self.assertRaisesRegex(ValueError, "already used"):
                    PUBLICATION.publish("bucket", sha, "123", directory)

                transfers = []
                calls = []
                original_load = PUBLICATION.load
                def fake_load(path, name):
                    if path == PUBLICATION.DOWNLOAD:
                        return type("Download", (), {"restore_version": staticmethod(
                            lambda *arguments: transfers.append(arguments))})
                    return original_load(path, name)

                with mock.patch.object(PUBLICATION, "load", side_effect=fake_load), \
                        mock.patch.object(PUBLICATION, "reader_context"), \
                        mock.patch.object(PUBLICATION, "call", side_effect=lambda command, **kw:
                                          calls.append((command, kw)) or b""):
                    PUBLICATION.transfer("bucket", ref, "openclaw-retirement-reader-test",
                                         "00000000-0000-0000-0000-000000000001", sha, "456")
                self.assertEqual(len(transfers), 3)
                self.assertTrue(all(item[3].startswith("/archive/private/discord-cache-456/")
                                    and item[2] == "v1" for item in transfers))
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[-1][0][-2], PUBLICATION.REMOTE_COMPLETE)
                completion = json.loads(calls[-1][1]["data"])
                self.assertEqual((completion["cacheRef"], completion["transferRunId"]),
                                 (ref, "456"))

                store.ambiguous = True
                with self.assertRaisesRegex(ValueError, "ambiguous"):
                    PUBLICATION.transfer("bucket", ref, "openclaw-retirement-reader-test",
                                         "00000000-0000-0000-0000-000000000001", sha, "457")
                store.ambiguous = False
                store.corrupt = True
                with self.assertRaisesRegex(ValueError, "differs from receipt"):
                    PUBLICATION.transfer("bucket", ref, "openclaw-retirement-reader-test",
                                         "00000000-0000-0000-0000-000000000001", sha, "458")
                self.assertEqual(len(calls), 2)

    def test_completion_marker_requires_remote_exact_bytes(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch) / "discord-cache-456"
            directory.mkdir(mode=0o700)
            data = b"cache"
            files = {}
            for name in PUBLICATION.NAMES:
                file = directory / name
                file.write_bytes(data)
                file.chmod(0o600)
                files[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                               "versionId": "v1"}
            receipt = {"format": 1, "cacheRef": "a" * 40 + "/123",
                       "transferSha": "a" * 40, "transferRunId": "456", "files": files}
            command = ["python3", "-c", PUBLICATION.REMOTE_COMPLETE,
                       os.path.realpath(directory)]
            (directory / "manifest.json").write_bytes(b"wrong")
            failure = subprocess.run(command, input=json.dumps(receipt).encode(),
                                     capture_output=True, timeout=5)
            self.assertNotEqual(failure.returncode, 0)
            self.assertFalse((directory / "completed.json").exists())
            (directory / "manifest.json").write_bytes(data)
            success = subprocess.run(command, input=json.dumps(receipt).encode(),
                                     capture_output=True, timeout=5)
            self.assertEqual(success.returncode, 0, success.stderr.decode())
            self.assertEqual(json.loads((directory / "completed.json").read_text()), receipt)


if __name__ == "__main__":
    unittest.main()
