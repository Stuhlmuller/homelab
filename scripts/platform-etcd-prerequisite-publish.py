#!/usr/bin/env python3
"""Publish one reviewed, offline-restored etcd prerequisite under a unique key.

Only the protected production workflow may call this producer. The raw snapshot
stays in the dedicated etcd bucket; the application bucket gets a small receipt.
"""

import argparse
import base64
import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


candidate = module("platform_etcd_prerequisite", ROOT / "scripts/platform-etcd-prerequisite.py")
platform = candidate.platform


def reviewed_publisher(source_sha):
    candidate.reviewed_context(source_sha)
    path = ROOT / "scripts/platform-etcd-prerequisite-publish.py"
    committed = subprocess.run(
        ["git", "--no-replace-objects", "show",
         f"{source_sha}:scripts/platform-etcd-prerequisite-publish.py"],
        cwd=ROOT, capture_output=True, timeout=15, check=True)
    if committed.stdout != path.read_bytes():
        raise ValueError("prerequisite publisher differs from the reviewed commit")
    if os.environ.get("GITHUB_ACTOR_ID") != "57728706" or os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("off-node publication needs the reviewed owner dispatch")


def receipt(value, source_sha, snapshot_sha, publication_id):
    expected = {
        "sourceSha", "verified", "capturedAt", "offNode", "offlineRestoreVerified",
        "snapshotSha256", "objectVersionId", "manifestVersionId", "objectPrefix",
        "offlineRestore", "controlPlaneRecoveryTested",
    }
    if (not isinstance(value, dict) or set(value) != expected or
            value["sourceSha"] != source_sha or value["snapshotSha256"] != snapshot_sha or
            value["objectPrefix"] != f"etcd/{snapshot_sha}/{publication_id}/" or
            value["verified"] is not True or value["offNode"] is not True or
            value["offlineRestoreVerified"] is not True or
            value["offlineRestore"] != "etcdutl-offline-database-restore" or
            value["controlPlaneRecoveryTested"] is not False or
            any(not isinstance(value[field], str) or value[field] in ("", "null")
                for field in ("objectVersionId", "manifestVersionId"))):
        raise ValueError("off-node candidate differs from the exact reviewed proof")
    # The candidate's timestamp is the snapshot manifest creation time. A
    # second restore of an old snapshot cannot renew its six-hour validity.
    platform.fresh_recovery_time(value["capturedAt"])


def publish(source_sha, snapshot_sha, publication_id, archive, output, store=None):
    if (not isinstance(source_sha, str) or not platform.SHA.fullmatch(source_sha) or
            not isinstance(snapshot_sha, str) or not candidate.SHA.fullmatch(snapshot_sha) or
            not isinstance(publication_id, str) or not candidate.IDENTIFIER.fullmatch(publication_id)):
        raise ValueError("invalid off-node publication identity")
    reviewed_publisher(source_sha)
    path = candidate.stage(source_sha, snapshot_sha, publication_id, archive, output)
    value = platform.read_private_json(path)
    receipt(value, source_sha, snapshot_sha, publication_id)
    content = path.read_bytes()
    if not 0 < len(content) <= 1048576:
        raise ValueError("off-node prerequisite candidate has invalid length")
    checksum = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
    key = platform.prerequisite_key(source_sha, "off-node-etcd-backup", publication_id)
    reviewed_publisher(source_sha)
    store = store or platform.DurableReceipts(platform.receipt_target())
    store.check()

    def versions():
        found = store.call("s3api", "list-object-versions", ["--prefix", key, "--no-paginate"])
        if found.get("IsTruncated") is not False or found.get("DeleteMarkers"):
            raise ValueError("off-node prerequisite history is partial or deleted")
        listed = found.get("Versions", [])
        if not isinstance(listed, list) or any(item.get("Key") != key for item in listed):
            raise ValueError("off-node prerequisite history has a foreign key")
        return listed

    if versions():
        raise ValueError("off-node prerequisite key already has a version")
    if platform.current_main_sha() != source_sha:
        raise ValueError("main advanced before off-node prerequisite publication")
    response = store.call("s3api", "put-object", [
        "--key", key, "--body", str(path), "--if-none-match", "*",
        "--checksum-algorithm", "SHA256", "--checksum-sha256", checksum,
        "--server-side-encryption", "aws:kms", "--ssekms-key-id",
        f"arn:aws:kms:{store.target['region']}:{store.target['account_id']}:alias/aws/s3",
        "--bucket-key-enabled",
    ])
    version = response.get("VersionId")
    if (not isinstance(version, str) or version in ("", "null") or
            response.get("ChecksumSHA256") != checksum):
        raise ValueError("off-node prerequisite upload has no verified version")
    listed = versions()
    if (len(listed) != 1 or listed[0].get("VersionId") != version or
            listed[0].get("IsLatest") is not True):
        raise ValueError("off-node prerequisite has ambiguous post-write history")
    head = store.call("s3api", "head-object", [
        "--key", key, "--version-id", version, "--checksum-mode", "ENABLED"])
    if (head.get("VersionId") != version or head.get("ChecksumSHA256") != checksum or
            head.get("ContentLength") != len(content) or
            head.get("ServerSideEncryption") != "aws:kms" or
            head.get("BucketKeyEnabled") is not True or
            store.download(key, version, path.parent) != content):
        raise ValueError("off-node prerequisite exact-version readback differs")
    if platform.current_main_sha() != source_sha:
        raise ValueError("main advanced after off-node prerequisite publication")
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--publication-id", required=True)
    parser.add_argument("--etcd-archive", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    previous_umask = os.umask(0o077)
    try:
        publish(args.expected_sha, args.snapshot_sha256, args.publication_id,
                args.etcd_archive, args.output_directory)
        print("Exact off-node etcd prerequisite published; private version and raw bytes withheld.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("Off-node prerequisite publication blocked; no completion claimed. Private diagnostics withheld.",
              file=sys.stderr)
        return 1
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    sys.exit(main())
