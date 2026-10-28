#!/usr/bin/env python3
"""Promote reviewed operator recovery candidates through protected production CI.

Only the two recovery prerequisites are supported here. Placement and artifact
publication require their own measured producers. Inputs are opaque IDs and
SHA-256 digests; private candidate JSON never enters workflow_dispatch or logs.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[0-9a-f]{32}\Z")
VERSION = re.compile(r"[\x21-\x7e]{1,1024}\Z")
ACCOUNT = "716182248480"
REGION = "us-east-1"
ROLE = "homelab-platform-receipt-publisher"
PREFIX = "openclaw-enterprise/platform/receipts"
NAMES = ("direct-recovery", "off-node-etcd-backup")


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


OFFSITE = module("platform_publisher_offsite", "etcd-offsite-backup.py")
PLATFORM = module("platform_publisher_gate", "platform-maintenance.py")
RESTORE = module("platform_publisher_restore", "etcd-offline-restore-check.py")


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def checksum(content):
    return base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")


def file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest(), base64.b64encode(digest.digest()).decode("ascii")


def quiet(command, *, timeout=30):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_") and key != "GH_HOST"}
    result = subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=False)
    if result.returncode or len(result.stdout) > 128 * 1024:
        raise ValueError("protected main verification failed")
    return result.stdout.decode("utf-8").strip()


def current_main(expected):
    if (any(key in os.environ for key in
            ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
             "GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
             "GH_HOST")) or
            not SHA.fullmatch(expected) or
            quiet(["git", "rev-parse", "--show-toplevel"]) != str(ROOT) or
            quiet(["git", "remote", "get-url", "origin"]) not in
            ("https://github.com/Stuhlmuller/homelab.git",
             "https://github.com/Stuhlmuller/homelab",
             "git@github.com:Stuhlmuller/homelab.git") or
            quiet(["git", "rev-parse", "HEAD"]) != expected or
            quiet(["git", "status", "--porcelain"]) or
            quiet(["gh", "api", "--hostname", "github.com",
                   "repos/Stuhlmuller/homelab/git/ref/heads/main",
                   "--jq", ".object.sha"]) != expected):
        raise ValueError("protected main changed during receipt review")


def context(expected):
    env = os.environ
    if (env.get("GITHUB_ACTIONS") != "true" or
            env.get("GITHUB_REPOSITORY") != "Stuhlmuller/homelab" or
            env.get("GITHUB_REF") != "refs/heads/main" or
            env.get("GITHUB_SHA") != expected or
            env.get("GITHUB_WORKFLOW") != "Platform Recovery Receipt Publication" or
            env.get("GITHUB_ACTOR_ID") != "57728706" or
            env.get("GITHUB_RUN_ATTEMPT") != "1"):
        raise ValueError("receipt publisher requires the protected owner dispatch")
    current_main(expected)


def targets():
    source = OFFSITE.destination()
    target = OFFSITE.read_inputs(ROOT / "IaC/application-backup-storage.hcl")
    if (source != {"account_id": ACCOUNT, "region": REGION,
                   "bucket": f"homelab-etcd-backups-{ACCOUNT}-{REGION}"} or
            target != {"account_id": ACCOUNT, "region": REGION,
                       "bucket": f"homelab-application-backups-{ACCOUNT}-{REGION}"}):
        raise ValueError("unreviewed receipt or offsite bucket")
    return source["bucket"], target["bucket"]


def guarded_bucket_policy(document, bucket):
    if not isinstance(document, dict) or not isinstance(document.get("Statement"), list):
        raise ValueError("authoritative bucket guard is missing")
    role_arn = f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
    resources = {f"arn:aws:s3:::{bucket}/{PREFIX}/*/{name}.json"
                 for name in ("placement", *NAMES, "artifact-publication")}
    expected = {
        "DenyOtherPrerequisiteWriters": {
            "Sid": "DenyOtherPrerequisiteWriters", "Effect": "Deny",
            "Principal": "*", "Action": ["s3:PutObject"],
            "Resource": resources,
            "Condition": {"ArnNotEquals": {"aws:PrincipalArn": role_arn}},
        },
        "DenyPrerequisiteDeletion": {
            "Sid": "DenyPrerequisiteDeletion", "Effect": "Deny",
            "Principal": "*", "Action": ["s3:DeleteObject", "s3:DeleteObjectVersion"],
            "Resource": resources,
        },
    }
    for sid, required in expected.items():
        matches = [item for item in document["Statement"]
                   if isinstance(item, dict) and item.get("Sid") == sid]
        if len(matches) != 1 or set(matches[0]) != set(required):
            raise ValueError("authoritative bucket guard differs from reviewed policy")
        actual = matches[0]
        if (any(actual[key] != value for key, value in required.items()
                if key not in ("Resource", "Action")) or
                not isinstance(actual["Resource"], list) or
                len(actual["Resource"]) != len(resources) or
                set(actual["Resource"]) != resources or
                actual["Action"] != required["Action"]):
            raise ValueError("authoritative bucket guard differs from reviewed policy")


class AWS:
    """No raw AWS output, diagnostics, or private object bodies enter the log."""

    def __init__(self, source, target):
        self.source = source
        self.target = target

    def call(self, service, operation, bucket=None, arguments=(), *, timeout=180):
        host = "s3" if service == "s3api" else "sts"
        command = ["aws", "--region", REGION, "--endpoint-url",
                   f"https://{host}.{REGION}.amazonaws.com", "--output", "json",
                   "--no-cli-pager", "--no-cli-auto-prompt", "--cli-connect-timeout", "15",
                   "--cli-read-timeout", "120", service, operation]
        if service == "s3api":
            if bucket not in (self.source, self.target):
                raise ValueError("unreviewed S3 bucket")
            command += ["--bucket", bucket, "--expected-bucket-owner", ACCOUNT]
        env = dict(os.environ)
        for key in tuple(env):
            if (key in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_CONFIG_FILE",
                        "AWS_SHARED_CREDENTIALS_FILE", "AWS_CA_BUNDLE") or
                    key.startswith("AWS_ENDPOINT_URL")):
                env.pop(key, None)
        result = subprocess.run(command + list(arguments), env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        if result.returncode or len(result.stdout) > 128 * 1024:
            raise ValueError("private AWS verification failed")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("private AWS metadata is invalid")
        return value

    def check(self):
        caller = self.call("sts", "get-caller-identity")
        if (caller.get("Account") != ACCOUNT or
                not re.fullmatch(rf"arn:aws:sts::{ACCOUNT}:assumed-role/{ROLE}/"
                                 r"homelab-platform-[0-9]+", str(caller.get("Arn")))):
            raise ValueError("receipt publisher has the wrong AWS identity")
        for bucket in (self.source, self.target):
            if self.call("s3api", "get-bucket-versioning", bucket).get("Status") != "Enabled":
                raise ValueError("receipt evidence bucket is not versioned")
            rules = self.call("s3api", "get-bucket-encryption", bucket).get(
                "ServerSideEncryptionConfiguration", {}).get("Rules", [])
            if (not isinstance(rules, list) or len(rules) != 1 or
                    rules[0].get("ApplyServerSideEncryptionByDefault") !=
                    {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID":
                     f"arn:aws:kms:{REGION}:{ACCOUNT}:alias/aws/s3"} or
                    rules[0].get("BucketKeyEnabled") is not True):
                raise ValueError("receipt evidence bucket encryption differs")
        self.check_guard()

    def check_guard(self):
        response = self.call("s3api", "get-bucket-policy", self.target)
        raw = response.get("Policy")
        if not isinstance(raw, str) or len(raw) > 128 * 1024:
            raise ValueError("authoritative bucket guard is missing")
        guarded_bucket_policy(json.loads(raw), self.target)

    def sole_version(self, bucket, key):
        result = self.call("s3api", "list-object-versions", bucket,
                           ["--prefix", key, "--no-paginate"])
        versions = result.get("Versions", [])
        if (result.get("IsTruncated") is not False or result.get("DeleteMarkers") or
                not isinstance(versions, list) or len(versions) != 1 or
                versions[0].get("Key") != key or
                versions[0].get("IsLatest") is not True or
                not VERSION.fullmatch(str(versions[0].get("VersionId"))) or
                versions[0]["VersionId"] == "null"):
            raise ValueError("private S3 object history is ambiguous")
        return versions[0]["VersionId"]

    def absent(self, key):
        result = self.call("s3api", "list-object-versions", self.target,
                           ["--prefix", key, "--no-paginate"])
        if (result.get("IsTruncated") is not False or result.get("DeleteMarkers") or
                result.get("Versions")):
            return False
        return True

    def download(self, bucket, key, version, path, *, max_size):
        if path.exists() or path.is_symlink():
            raise ValueError("private download path already exists")
        head = self.call("s3api", "head-object", bucket,
                         ["--key", key, "--version-id", version,
                          "--checksum-mode", "ENABLED"])
        size = head.get("ContentLength")
        if (head.get("VersionId") != version or type(size) is not int or
                not 0 < size <= max_size or
                head.get("ServerSideEncryption") != "aws:kms" or
                head.get("BucketKeyEnabled") is not True or
                not re.fullmatch(rf"arn:aws:kms:{REGION}:{ACCOUNT}:key/[A-Za-z0-9-]+",
                                 str(head.get("SSEKMSKeyId"))) or
                not isinstance(head.get("ChecksumSHA256"), str)):
            raise ValueError("private S3 object metadata differs")
        response = self.call("s3api", "get-object", bucket,
                             ["--key", key, "--version-id", version,
                              "--checksum-mode", "ENABLED", str(path)], timeout=600)
        path.chmod(0o600)
        actual_size, digest, actual_checksum = file_digest(path)
        if (actual_size != size or response.get("VersionId") != version or
                response.get("ChecksumSHA256") != head["ChecksumSHA256"] or
                actual_checksum != head["ChecksumSHA256"] or
                response.get("ContentLength") != size or
                response.get("ServerSideEncryption") != "aws:kms"):
            raise ValueError("private S3 object bytes differ from exact version")
        if self.sole_version(bucket, key) != version:
            raise ValueError("private S3 object changed during readback")
        return digest

    def write_once(self, key, content, directory, *, before_write):
        if len(content) > 1048576:
            raise ValueError("platform receipt exceeds private JSON limit")
        if not self.absent(key):
            version = self.sole_version(self.target, key)
            target = directory / "existing.json"
            if self.download(self.target, key, version, target,
                             max_size=1048576) != sha256(content) or target.read_bytes() != content:
                raise ValueError("existing prerequisite receipt differs")
            target.unlink()
            return
        path = directory / "publish.json"
        path.write_bytes(content)
        path.chmod(0o600)
        expected = checksum(content)
        before_write()
        response = self.call("s3api", "put-object", self.target, [
            "--key", key, "--body", str(path), "--if-none-match", "*",
            "--checksum-algorithm", "SHA256", "--checksum-sha256", expected,
            "--server-side-encryption", "aws:kms", "--ssekms-key-id",
            f"arn:aws:kms:{REGION}:{ACCOUNT}:alias/aws/s3", "--bucket-key-enabled"])
        path.unlink()
        version = response.get("VersionId")
        if (not VERSION.fullmatch(str(version)) or version == "null" or
                response.get("ChecksumSHA256") != expected or
                self.sole_version(self.target, key) != version):
            raise ValueError("platform prerequisite write lacks exact-version proof")
        readback = directory / "readback.json"
        if (self.download(self.target, key, version, readback, max_size=1048576)
                != sha256(content) or readback.read_bytes() != content):
            raise ValueError("platform prerequisite readback differs")
        readback.unlink()


def fresh_manifest_time(value):
    if (not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?\+00:00", value)):
        raise ValueError("offsite snapshot timestamp is invalid")
    result = datetime.fromisoformat(value).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    PLATFORM.fresh_recovery_time(result)
    return result


def fresh_restore_time(value):
    if (not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?\+00:00", value)):
        raise ValueError("offline restore timestamp is invalid")
    result = datetime.fromisoformat(value).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    PLATFORM.fresh_recovery_time(result)
    return result


def validate_candidates(direct, backup, restore, manifest, source_sha,
                        source_bucket, target_bucket, source_record):
    if (not all(isinstance(item, dict) for item in
                (direct, backup, restore, manifest)) or
            not isinstance(manifest.get("integrity"), dict) or
            not isinstance(manifest.get("metadata"), dict) or
            not isinstance(restore.get("restored_status"), dict)):
        raise ValueError("private candidate or offsite manifest is malformed")
    nodes = ["zimaboard-0", "zimaboard-1", "zimaboard-2", "acer"]
    addresses = ["10.1.0.200", "10.1.0.201", "10.1.0.202", "10.1.0.199"]
    for name, value in (("direct-recovery", direct),
                        ("off-node-etcd-backup", backup)):
        if (value.get("format") != 1 or value.get("scope") != "operator-local-candidate" or
                value.get("verified") is not False or value.get("sourceSha") != source_sha or
                value.get("targetBucket") != target_bucket or
                value.get("targetKey") != f"{PREFIX}/{source_sha}/{name}.json"):
            raise ValueError("reviewed candidate source binding differs")
        PLATFORM.fresh_recovery_time(value.get("capturedAt"))
    if (direct.get("nodes") != nodes or direct.get("endpoint") != "10.1.0.199:50000" or
            direct.get("controlPlaneEndpoint") != direct.get("endpoint") or
            direct.get("nodeAddresses") != dict(zip(nodes, addresses)) or
            direct.get("nodeEndpoints") !=
            {name: f"{address}:50000" for name, address in zip(nodes, addresses)} or
            direct.get("transport") != "direct-lan-authenticated-talos" or
            direct.get("talosMtls") is not True or
            direct.get("etcdStatusRead") is not True or
            direct.get("directClusterHealth") is not True or
            not re.fullmatch(r"en[0-9]+", str(direct.get("interface"))) or
            ipaddress.ip_address(direct.get("sourceAddress")) not in
            ipaddress.ip_network("10.1.0.0/24") or
            str(direct.get("sourceAddress")) in addresses or
            not DIGEST.fullmatch(str(direct.get("talosconfigSha256")))):
        raise ValueError("reviewed direct-LAN evidence is incomplete")
    snap_sha = backup.get("snapshotSha256")
    prefix = f"etcd/{snap_sha}/"
    if (backup.get("offNode") is not True or
            backup.get("offlineRestoreVerified") is not True or
            not DIGEST.fullmatch(str(snap_sha)) or
            backup.get("offsiteBucket") != source_bucket or
            not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}/etcd\.snapshot",
                             str(backup.get("snapshotKey"))) or
            backup.get("manifestKey") !=
            backup["snapshotKey"].removesuffix("etcd.snapshot") + "manifest.json" or
            any(not VERSION.fullmatch(str(backup.get(field))) or
                backup[field] == "null" for field in
                ("objectVersionId", "manifestVersionId")) or
            any(type(backup.get(field)) is not int or backup[field] <= 0
                for field in ("snapshotBytes", "manifestBytes")) or
            any(not DIGEST.fullmatch(str(backup.get(field)))
                for field in ("manifestSha256", "restoreReceiptSha256"))):
        raise ValueError("reviewed off-node evidence is incomplete")
    if (manifest.get("source_node") != "10.1.0.199" or
            backup["snapshotSha256"] != manifest["integrity"]["sha256"] or
            backup["snapshotBytes"] != manifest["integrity"]["bytes"] or
            backup["manifestSha256"] != source_record["manifestSha256"] or
            backup["manifestBytes"] != source_record["manifestBytes"] or
            backup["capturedAt"] != fresh_manifest_time(manifest.get("created_at")) or
            restore.get("format") != 1 or
            restore.get("validation") != "offline-database-restore" or
            restore.get("control_plane_recovery_tested") is not False or
            restore.get("source_unchanged") is not True or
            restore.get("restore_checksum_enabled") is not True or
            restore.get("server_started") is not False or
            restore.get("source_integrity") != manifest["integrity"] or
            restore.get("snapshot_status") != manifest["metadata"] or
            fresh_restore_time(restore.get("completed_at")) < backup["capturedAt"] or
            not isinstance(restore.get("tool"), dict) or
            restore["tool"].get("version") != RESTORE.VERSION or
            restore["tool"].get("platform") not in ("darwin-amd64", "darwin-arm64") or
            restore["tool"].get("archive_sha256") !=
            RESTORE.ARCHIVES[restore["tool"]["platform"]] or
            any(restore.get("restored_status", {}).get(field) !=
                manifest["metadata"].get(field) for field in ("revision", "total_keys"))):
        raise ValueError("downloaded snapshot and offline restore linkage differ")
    return direct, backup


def promote(args, aws):
    source_sha = args.expected_sha
    context(source_sha)
    source_bucket, target_bucket = targets()
    if (aws.source, aws.target) != (source_bucket, target_bucket):
        raise ValueError("unreviewed AWS destinations")
    aws.check()
    stage_prefix = f"platform-candidates/{source_sha}/{args.candidate_id}"
    keys = {
        "direct-recovery": f"{stage_prefix}/direct-recovery.candidate.json",
        "off-node-etcd-backup": f"{stage_prefix}/off-node-etcd-backup.candidate.json",
        "offline-restore": f"{stage_prefix}/offline-restore.receipt.json",
    }
    reviewed = {"direct-recovery": args.direct_sha256,
                "off-node-etcd-backup": args.backup_sha256,
                "offline-restore": args.restore_sha256}
    with tempfile.TemporaryDirectory(prefix="platform-publisher-") as temporary:
        directory = Path(temporary)
        contents = {}
        versions = {}
        for name, key in keys.items():
            version = aws.sole_version(source_bucket, key)
            path = directory / f"{name}.json"
            digest = aws.download(source_bucket, key, version, path, max_size=1048576)
            if digest != reviewed[name]:
                raise ValueError("staged candidate differs from reviewed digest")
            contents[name] = path.read_bytes()
            versions[name] = version
        direct = json.loads(contents["direct-recovery"])
        backup = json.loads(contents["off-node-etcd-backup"])
        restore = json.loads(contents["offline-restore"])
        if not all(isinstance(item, dict) for item in (direct, backup, restore)):
            raise ValueError("staged candidate JSON must be an object")
        for name in NAMES:
            if contents[name] != canonical({"direct-recovery": direct,
                                            "off-node-etcd-backup": backup}[name]):
                raise ValueError("staged candidate is not canonical")
        snapshot_key = backup.get("snapshotKey")
        manifest_key = backup.get("manifestKey")
        snapshot_sha = backup.get("snapshotSha256")
        if (not isinstance(snapshot_key, str) or not isinstance(manifest_key, str) or
                not DIGEST.fullmatch(str(snapshot_sha)) or
                not re.fullmatch(rf"etcd/{snapshot_sha}/[0-9a-f]{{32}}/etcd\.snapshot",
                                 snapshot_key) or
                manifest_key != snapshot_key.removesuffix("etcd.snapshot") +
                "manifest.json"):
            raise ValueError("offsite object key differs")
        snapshot_version = aws.sole_version(source_bucket, snapshot_key)
        manifest_version = aws.sole_version(source_bucket, manifest_key)
        if (snapshot_version != backup.get("objectVersionId") or
                manifest_version != backup.get("manifestVersionId")):
            raise ValueError("offsite exact versions differ from reviewed candidate")
        snap_path = directory / "etcd.snapshot"
        manifest_path = directory / "manifest.json"
        snapshot_digest = aws.download(source_bucket, snapshot_key, snapshot_version,
                                       snap_path, max_size=5 * 1024 ** 3)
        manifest_digest = aws.download(source_bucket, manifest_key, manifest_version,
                                       manifest_path, max_size=1048576)
        manifest = OFFSITE.backup.verify(directory)
        if (snapshot_digest != backup.get("snapshotSha256") or
                manifest_digest != backup.get("manifestSha256") or
                snap_path.stat().st_size != backup.get("snapshotBytes") or
                manifest_path.stat().st_size != backup.get("manifestBytes") or
                sha256(contents["offline-restore"]) != backup.get("restoreReceiptSha256")):
            raise ValueError("offsite readback differs from offline restore evidence")
        source_record = {"manifestSha256": manifest_digest,
                         "manifestBytes": manifest_path.stat().st_size}
        validate_candidates(direct, backup, restore, manifest, source_sha,
                            source_bucket, target_bucket, source_record)
        # Recheck all exact versions and main after the potentially long snapshot
        # transfer. A source change or ambiguous history blocks both writes.
        context(source_sha)
        for name, key in {**keys, "snapshot": snapshot_key,
                          "manifest": manifest_key}.items():
            version = versions.get(name, snapshot_version if name == "snapshot"
                                   else manifest_version)
            if aws.sole_version(source_bucket, key) != version:
                raise ValueError("reviewed S3 evidence changed before publication")
        for name, candidate in (("direct-recovery", direct),
                                ("off-node-etcd-backup", backup)):
            record = {key: value for key, value in candidate.items()
                      if key not in ("scope", "verified", "targetBucket", "targetKey")}
            record.update({"scope": "protected-platform-prerequisite", "verified": True,
                           "reviewedCandidateSha256": reviewed[name],
                           "candidateBucket": source_bucket,
                           "candidateKey": keys[name],
                           "candidateVersionId": versions[name],
                           "offlineRestoreCandidateSha256": reviewed["offline-restore"],
                           "offlineRestoreCandidateVersionId": versions["offline-restore"]})
            key = f"{PREFIX}/{source_sha}/{name}.json"
            def before_write():
                context(source_sha)
                aws.check_guard()
                for receipt in (direct, backup):
                    PLATFORM.fresh_recovery_time(receipt["capturedAt"])
                    age = (datetime.now(timezone.utc) - datetime.strptime(
                        receipt["capturedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(
                            tzinfo=timezone.utc)).total_seconds()
                    if age > PLATFORM.MAX_RECOVERY_AGE_SECONDS - 600:
                        raise ValueError("reviewed recovery candidate is near expiry")
            if aws.sole_version(source_bucket, keys[name]) != versions[name]:
                raise ValueError("candidate changed immediately before publication")
            before_write()
            aws.write_once(key, canonical(record), directory,
                           before_write=before_write)
        for name, key in {**keys, "snapshot": snapshot_key,
                          "manifest": manifest_key}.items():
            version = versions.get(name, snapshot_version if name == "snapshot"
                                   else manifest_version)
            if aws.sole_version(source_bucket, key) != version:
                raise ValueError("offsite source version changed after publication")
        context(source_sha)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--direct-sha256", required=True)
    parser.add_argument("--backup-sha256", required=True)
    parser.add_argument("--restore-sha256", required=True)
    args = parser.parse_args()
    if (not SHA.fullmatch(args.expected_sha) or not ID.fullmatch(args.candidate_id) or
            any(not DIGEST.fullmatch(value) for value in
                (args.direct_sha256, args.backup_sha256, args.restore_sha256))):
        parser.error("expected SHA, candidate ID, and reviewed digests are invalid")
    previous = os.umask(0o077)
    try:
        source, target = targets()
        promote(args, AWS(source, target))
        print("Protected recovery prerequisites published and read back; private evidence withheld.")
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError,
            subprocess.SubprocessError, json.JSONDecodeError):
        print("Recovery receipt publication blocked; private candidate, S3, and Talos "
              "diagnostics withheld. Retain staged versions and inspect privately.",
              file=sys.stderr)
        return 1
    finally:
        os.umask(previous)


if __name__ == "__main__":
    sys.exit(main())
