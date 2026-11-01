#!/usr/bin/env python3
"""Stage a platform etcd receipt from immutable S3 bytes and an offline restore.

This does not publish a prerequisite. A protected, narrowly scoped publisher
must review and write the staged receipt before platform maintenance can use it.
"""

import argparse
import base64
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{64}\Z")
IDENTIFIER = re.compile(r"[0-9a-f]{32}\Z")
SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
NAMES = ("etcd.snapshot", "manifest.json")
RECEIPT = "off-node-etcd-backup.json"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


backup = module("platform_talos_etcd_backup", ROOT / "scripts/talos-etcd-backup.py")
offsite = module("platform_etcd_offsite_backup", ROOT / "scripts/etcd-offsite-backup.py")
offline = module("platform_etcd_offline_restore", ROOT / "scripts/etcd-offline-restore-check.py")
platform = module("platform_etcd_maintenance", ROOT / "scripts/platform-maintenance.py")


def reviewed_context(source_sha):
    """Bind the candidate to the current main dispatch revision before reads."""
    if not isinstance(source_sha, str) or not SOURCE_SHA.fullmatch(source_sha):
        raise ValueError("invalid reviewed source revision")
    if (os.environ.get("GITHUB_REPOSITORY") != "Stuhlmuller/homelab" or
            os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise ValueError("off-node proof requires reviewed repository dispatch")
    platform.protected_context(source_sha)
    config_path = ROOT / "scripts/config/platform-maintenance.json"
    platform.validate_config(json.loads(
        platform.require_reviewed_execution_config(config_path, source_sha)))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, timeout=15, check=True)
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                            cwd=ROOT, capture_output=True, text=True,
                            timeout=15, check=True)
    if head.stdout.strip() != source_sha or status.stdout.strip():
        raise ValueError("prerequisite source differs from the reviewed commit")
    for relative in ("scripts/platform-etcd-prerequisite.py",
                     "scripts/platform-maintenance.py", "scripts/talos-etcd-backup.py",
                     "scripts/etcd-offsite-backup.py", "scripts/etcd-offline-restore-check.py"):
        committed = subprocess.run(["git", "show", f"{source_sha}:{relative}"],
                                   cwd=ROOT, capture_output=True, timeout=15, check=True)
        if committed.stdout != (ROOT / relative).read_bytes():
            raise ValueError("prerequisite helper differs from the reviewed commit")
    result = subprocess.run(
        ["git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
         "refs/heads/main"], cwd=ROOT, capture_output=True, text=True,
        timeout=30, check=True)
    if result.stdout.strip() != f"{source_sha}\trefs/heads/main":
        raise ValueError("reviewed revision is no longer current main")


class S3Reader:
    """Read only the committed etcd bucket through the real AWS S3 endpoint."""

    def __init__(self):
        self.target = offsite.destination()

    def call(self, service, operation, arguments=()):
        if (service, operation) not in {
                ("sts", "get-caller-identity"),
                ("s3api", "get-bucket-versioning"),
                ("s3api", "get-bucket-encryption"),
                ("s3api", "list-object-versions"),
                ("s3api", "head-object"),
                ("s3api", "get-object")}:
            raise ValueError("unreviewed prerequisite AWS operation")
        region = self.target["region"]
        endpoint = f"https://{'sts' if service == 'sts' else 's3'}.{region}.amazonaws.com"
        command = ["aws", "--region", region, "--endpoint-url", endpoint,
                   "--output", "json", "--no-cli-pager", "--no-cli-auto-prompt",
                   "--cli-connect-timeout", "15", "--cli-read-timeout", "120",
                   service, operation]
        if service == "s3api":
            command += ["--bucket", self.target["bucket"],
                        "--expected-bucket-owner", self.target["account_id"]]
        result = subprocess.run(command + list(arguments), capture_output=True,
                                text=True, timeout=600, check=False)
        if result.returncode:
            raise ValueError(f"off-node prerequisite {operation} failed")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("invalid off-node prerequisite AWS metadata")
        return value

    def check(self):
        if self.call("sts", "get-caller-identity").get("Account") != self.target["account_id"]:
            raise ValueError("off-node account differs from committed bucket owner")
        if self.call("s3api", "get-bucket-versioning").get("Status") != "Enabled":
            raise ValueError("off-node bucket is not versioned")
        rules = self.call("s3api", "get-bucket-encryption").get(
            "ServerSideEncryptionConfiguration", {}).get("Rules", [])
        if not rules or rules[0].get("ApplyServerSideEncryptionByDefault", {}).get(
                "SSEAlgorithm") != "aws:kms":
            raise ValueError("off-node bucket is not KMS encrypted")

    def versions(self, prefix):
        value = self.call("s3api", "list-object-versions",
                          ["--prefix", prefix, "--no-paginate"])
        versions = value.get("Versions")
        if (value.get("IsTruncated") is not False or value.get("DeleteMarkers") or
                not isinstance(versions, list) or len(versions) != 2):
            raise ValueError("off-node publication history is ambiguous")
        found = {}
        for item in versions:
            key, version, size = item.get("Key"), item.get("VersionId"), item.get("Size")
            if (key not in {prefix + name for name in NAMES} or key in found or
                    not isinstance(version, str) or version in ("", "null") or
                    item.get("IsLatest") is not True or type(size) is not int or
                    not 0 < size <= (1048576 if key.endswith("manifest.json") else 5 * 1024 ** 3)):
                raise ValueError("off-node publication history is ambiguous")
            found[key] = (version, size)
        return found

    def download(self, key, version, expected_size, path):
        if path.exists() or path.is_symlink():
            raise ValueError("off-node download destination already exists")
        arguments = ["--key", key, "--version-id", version, "--checksum-mode", "ENABLED"]
        head = self.call("s3api", "head-object", arguments)
        checksum = head.get("ChecksumSHA256")
        try:
            valid_checksum = (isinstance(checksum, str) and
                              len(base64.b64decode(checksum, validate=True)) == 32)
        except ValueError:
            valid_checksum = False
        if (head.get("VersionId") != version or
                head.get("ContentLength") != expected_size or
                head.get("ServerSideEncryption") != "aws:kms" or
                head.get("BucketKeyEnabled") is not True or not valid_checksum):
            raise ValueError("exact-version off-node HEAD metadata differs")
        metadata = self.call("s3api", "get-object", [
            *arguments, str(path)])
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("off-node download is not a private regular file")
        path.chmod(0o600)
        size = info.st_size
        if size != expected_size:
            raise ValueError("off-node object has invalid length")
        actual_checksum = base64.b64encode(bytes.fromhex(offsite.digest(path)["sha256"])).decode()
        if (metadata.get("VersionId") != version or
                metadata.get("ContentLength") != size or
                metadata.get("ChecksumSHA256") != checksum or
                metadata.get("ServerSideEncryption") != "aws:kms" or
                metadata.get("BucketKeyEnabled") is not True or
                actual_checksum != checksum):
            raise ValueError("exact-version off-node readback differs")


def source_time(record):
    if record.get("source_node") != backup.CONTROL_PLANE:
        raise ValueError("snapshot source differs from reviewed control plane")
    value = record.get("created_at")
    if not isinstance(value, str):
        raise ValueError("snapshot creation time is absent")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("snapshot creation time is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("snapshot creation time is not UTC")
    captured = parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    platform.fresh_recovery_time(captured)
    return captured


def stage(source_sha, snapshot_sha, publication_id, archive, output, reader=None):
    """Read one immutable S3 pair and restore its snapshot before staging proof."""
    if (not isinstance(source_sha, str) or not SOURCE_SHA.fullmatch(source_sha) or
            not isinstance(snapshot_sha, str) or not SHA.fullmatch(snapshot_sha) or
            not isinstance(publication_id, str) or
            not IDENTIFIER.fullmatch(publication_id)):
        raise ValueError("invalid reviewed snapshot identity")
    reviewed_context(source_sha)
    output = platform.private_directory(output)
    result_path = output / RECEIPT
    if result_path.exists() or result_path.is_symlink():
        raise ValueError("off-node prerequisite candidate already exists")
    reader = reader or S3Reader()
    if reader.target != offsite.destination():
        raise ValueError("off-node destination differs from committed bucket")
    prefix = f"etcd/{snapshot_sha}/{publication_id}/"
    reader.check()
    versions = reader.versions(prefix)
    work = Path(tempfile.mkdtemp(prefix="off-node-etcd-evidence-", dir=output))
    try:
        source = work / "source"
        source.mkdir(mode=0o700)
        for name in NAMES:
            version, size = versions[prefix + name]
            reader.download(prefix + name, version, size, source / name)
        record = backup.verify(source)
        if record.get("integrity", {}).get("sha256") != snapshot_sha:
            raise ValueError("downloaded snapshot differs from reviewed digest")
        captured = source_time(record)
        _, proof = offline.restore_check(source, work, archive)
        if (proof.get("validation") != "offline-database-restore" or
                proof.get("source_integrity") != record["integrity"] or
                proof.get("restore_checksum_enabled") is not True or
                proof.get("source_unchanged") is not True or
                proof.get("control_plane_recovery_tested") is not False or
                proof.get("server_started") is not False or
                proof.get("snapshot_status", {}).get("revision") !=
                proof.get("restored_status", {}).get("revision") or
                proof.get("snapshot_status", {}).get("total_keys") !=
                proof.get("restored_status", {}).get("total_keys")):
            raise ValueError("offline database restore proof is incomplete")
        if backup.verify(source) != record:
            raise ValueError("off-node source changed during restore")
        candidate = {
            "sourceSha": source_sha, "verified": True, "capturedAt": captured,
            "offNode": True, "offlineRestoreVerified": True,
            "snapshotSha256": snapshot_sha,
            "objectVersionId": versions[prefix + backup.SNAPSHOT][0],
            "manifestVersionId": versions[prefix + backup.MANIFEST][0],
            "objectPrefix": prefix,
            "offlineRestore": "etcdutl-offline-database-restore",
            "controlPlaneRecoveryTested": False,
        }
    finally:
        # This invocation created only a downloaded working copy, never the
        # source object or an operator backup. Keep just the small candidate.
        shutil.rmtree(work)
    fd = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(candidate, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    backup.sync_directory(output)
    return result_path


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
        stage(args.expected_sha, args.snapshot_sha256, args.publication_id,
              args.etcd_archive, args.output_directory)
        print("Off-node etcd prerequisite candidate staged from exact-version S3 and offline restore; publication remains disabled.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("Off-node prerequisite candidate failed; retain private evidence. No platform receipt was published.",
              file=sys.stderr)
        return 1
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    sys.exit(main())
