#!/usr/bin/env python3
"""Manually publish and retrieve verified etcd snapshots in the declared S3 bucket."""

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


CONFIG = Path(__file__).resolve().parents[1] / "IaC/config/etcd-backup-storage.json"
RECEIPT = "publication.json"
FILES = ("etcd.snapshot", "manifest.json")
spec = importlib.util.spec_from_file_location(
    "talos_etcd_backup", Path(__file__).with_name("talos-etcd-backup.py")
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def destination():
    value = json.loads(CONFIG.read_text())
    if (set(value) != {"account_id", "region", "bucket"}
            or not re.fullmatch(r"[0-9]{12}", value["account_id"])
            or value["region"] != "us-east-1"
            or value["bucket"] != f"homelab-etcd-backups-{value['account_id']}-{value['region']}"):
        raise ValueError("invalid committed offsite destination")
    return value


def private_file(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError("operation files must be regular, owned, mode-0600 files")


def digest(path):
    private_file(path)
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
            size += len(chunk)
    if not 0 < size <= 5 * 1024 ** 3:
        raise ValueError("single-object publication requires 1 byte through 5 GiB")
    return {"bytes": size, "sha256": sha.hexdigest()}


def checksum(record):
    return base64.b64encode(bytes.fromhex(record["sha256"])).decode("ascii")


def sync_file(path):
    private_file(path)
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def save(path, value):
    """Durably replace only this invocation's private receipt."""
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    backup.sync_directory(path.parent)


class AWS:
    """Fixed AWS API operations through an explicit existing file-backed profile."""

    def __init__(self, executable, profile, target):
        if not executable.is_absolute():
            raise ValueError("AWS CLI must be an absolute executable path")
        self.executable = executable.resolve(strict=True)
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise ValueError("AWS CLI must be an executable file")
        if not re.fullmatch(r"[A-Za-z0-9_+=,.@-]{1,128}", profile):
            raise ValueError("invalid existing AWS profile name")
        self.profile, self.target = profile, target
        # Existing ~/.aws profiles/SSO cache remain available. Ignore exported
        # credentials, config selectors, endpoints, or other AWS overrides.
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}

    def call(self, service, operation, arguments=(), missing=False):
        endpoint = f"https://{service if service == 'sts' else 's3'}.{self.target['region']}.amazonaws.com"
        command = [str(self.executable), "--profile", self.profile,
                   "--region", self.target["region"], "--endpoint-url", endpoint,
                   "--output", "json", "--no-cli-pager", "--no-cli-auto-prompt",
                   "--cli-connect-timeout", "15", "--cli-read-timeout", "120",
                   service, operation]
        if service == "s3api":
            command += ["--bucket", self.target["bucket"],
                        "--expected-bucket-owner", self.target["account_id"]]
        result = subprocess.run(command + list(arguments), env=self.environment,
                                capture_output=True, text=True, timeout=600, check=False)
        if result.returncode:
            if missing and re.search(r"\((404|NoSuchKey|NotFound)\)", result.stderr):
                return None
            raise ValueError(f"AWS {operation} failed; retain local files and check the existing session")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("unexpected AWS metadata response")
        return value

    def check(self):
        identity = self.call("sts", "get-caller-identity")
        if identity.get("Account") != self.target["account_id"]:
            raise ValueError("AWS session account differs from the committed bucket owner")
        if self.call("s3api", "get-bucket-versioning").get("Status") != "Enabled":
            raise ValueError("offsite bucket versioning must be enabled")


def object_metadata(value, expected, version=None):
    actual_version = value.get("VersionId")
    if (not isinstance(actual_version, str) or not actual_version or actual_version == "null"
            or (version is not None and actual_version != version)
            or value.get("ChecksumSHA256") != checksum(expected)
            or value.get("ContentLength") != expected["bytes"]
            or value.get("ServerSideEncryption") != "aws:kms"
            or value.get("BucketKeyEnabled") is not True):
        raise ValueError("S3 version, length, checksum, or encryption differs from the publication")
    return actual_version


def load(directory, target, require_files=True):
    directory = backup.private_directory(directory)
    private_file(directory / RECEIPT)
    value = json.loads((directory / RECEIPT).read_text())
    identifier = value.get("id", "")
    integrity = value.get("source_integrity", {})
    if (value.get("format") != 1 or value.get("destination") != target
            or not re.fullmatch(r"[0-9a-f]{32}", identifier)
            or not re.fullmatch(r"[0-9a-f]{64}", integrity.get("sha256", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", integrity.get("embedded_sha256", ""))
            or value.get("prefix") != f"etcd/{integrity['sha256']}/{identifier}"
            or set(value.get("objects", {})) != set(FILES)):
        raise ValueError("publication receipt does not match the verified local copy")
    for name in FILES:
        item = value["objects"][name]
        expected = item.get("digest", {})
        if (set(expected) != {"bytes", "sha256"} or type(expected["bytes"]) is not int
                or not 0 < expected["bytes"] <= 5 * 1024 ** 3
                or not re.fullmatch(r"[0-9a-f]{64}", expected["sha256"])):
            raise ValueError("invalid publication object digest")
        if require_files and expected != digest(directory / name):
            raise ValueError("publication file changed since the receipt was created")
        version = item.get("version_id")
        if version is not None and (not isinstance(version, str) or not version or version == "null"):
            raise ValueError("invalid immutable object version")
    if value["objects"][FILES[0]]["digest"] != {key: integrity[key] for key in ("bytes", "sha256")}:
        raise ValueError("snapshot digest differs from its embedded-checksum record")
    if require_files and backup.verify(directory)["integrity"] != integrity:
        raise ValueError("publication copy differs from its embedded-checksum record")
    return directory, value


def retrieve(publication, destination_path, aws):
    publication, value = load(publication, aws.target, require_files=False)
    if value.get("status") not in ("published", "verified"):
        raise ValueError("publication is incomplete; resume it before retrieval")
    if any(not item.get("version_id") for item in value["objects"].values()):
        raise ValueError("retrieval requires both immutable version IDs")
    output = backup.private_directory(destination_path)
    if output == publication or publication in output.parents:
        raise ValueError("retrieval output must be outside the publication copy")
    aws.check()
    pending = Path(tempfile.mkdtemp(prefix=".partial-retrieval-", dir=output))
    # Deliberately retain failed/partial downloads; never remove recovery data.
    for name in FILES:
        item = value["objects"][name]
        args = ["--key", f"{value['prefix']}/{name}", "--version-id", item["version_id"],
                "--checksum-mode", "ENABLED"]
        metadata = aws.call("s3api", "get-object", [*args, str(pending / name)])
        (pending / name).chmod(0o600)
        sync_file(pending / name)
        object_metadata(metadata, item["digest"], item["version_id"])
        if digest(pending / name) != item["digest"]:
            raise ValueError("downloaded bytes do not match the immutable publication")
    restored = backup.verify(pending)
    if restored["integrity"] != value["source_integrity"]:
        raise ValueError("downloaded backup integrity differs from the publication")
    if load(publication, aws.target, require_files=False)[1] != value:
        raise ValueError("publication receipt changed during retrieval")
    save(pending / "retrieval.json", {
        "format": 1, "verified_at": datetime.now(timezone.utc).isoformat(),
        "destination": aws.target, "prefix": value["prefix"], "objects": value["objects"],
        "source_integrity": restored["integrity"], "offline_checksum_verified": True,
        "control_plane_restore_tested": False,
    })
    complete = pending.with_name(pending.name.removeprefix(".partial-"))
    pending.rename(complete)
    backup.sync_directory(output)
    return complete


def publish(source, destination_path, aws, resume=None):
    source = backup.private_directory(source)
    original = backup.verify(source)
    output = backup.private_directory(destination_path)
    if output == source or source in output.parents:
        raise ValueError("publication output must be outside the original backup")
    if resume is None:
        publication = Path(tempfile.mkdtemp(prefix="publication-", dir=output))
        for name in FILES:
            shutil.copyfile(source / name, publication / name)
            (publication / name).chmod(0o600)
            sync_file(publication / name)
        if backup.verify(publication) != original:
            raise ValueError("working copy differs from the verified original")
        identifier = uuid.uuid4().hex
        value = {
            "format": 1, "id": identifier, "destination": aws.target,
            "prefix": f"etcd/{original['integrity']['sha256']}/{identifier}",
            "source_integrity": original["integrity"], "status": "incomplete",
            "objects": {name: {"digest": digest(publication / name), "version_id": None}
                        for name in FILES},
        }
        save(publication / RECEIPT, value)
    else:
        publication, value = load(resume, aws.target)
        if backup.verify(publication) != original:
            raise ValueError("resume source differs from the retained publication copy")
    # A previous attempt may have stopped specifically at this durability gate.
    # Recheck the retained publication's actual parent before resuming uploads.
    backup.sync_directory(publication.parent)
    aws.check()
    for name in FILES:  # Snapshot first; the manifest is the completion marker.
        load(publication, aws.target)
        if backup.verify(source) != original:
            raise ValueError("source backup changed during publication")
        item = value["objects"][name]
        expected_version = item["version_id"]
        args = ["--key", f"{value['prefix']}/{name}", "--checksum-mode", "ENABLED"]
        if item["version_id"]:
            args += ["--version-id", item["version_id"]]
        metadata = aws.call("s3api", "head-object", args, missing=not item["version_id"])
        if metadata is None:
            result = aws.call("s3api", "put-object", [
                "--key", f"{value['prefix']}/{name}", "--body", str(publication / name),
                "--if-none-match", "*", "--checksum-algorithm", "SHA256",
                "--checksum-sha256", checksum(item["digest"]),
                "--server-side-encryption", "aws:kms", "--ssekms-key-id",
                f"arn:aws:kms:{aws.target['region']}:{aws.target['account_id']}:alias/aws/s3",
                "--bucket-key-enabled",
            ])
            version = result.get("VersionId")
            if not version or version == "null" or result.get("ChecksumSHA256") != checksum(item["digest"]):
                raise ValueError("S3 did not confirm an immutable checksummed upload")
            expected_version = version
            metadata = aws.call("s3api", "head-object", [*args, "--version-id", version])
        item["version_id"] = object_metadata(metadata, item["digest"], expected_version)
        save(publication / RECEIPT, value)
    if backup.verify(source) != original:
        raise ValueError("source backup changed during publication")
    load(publication, aws.target)
    value["status"] = "published"
    save(publication / RECEIPT, value)
    downloaded = retrieve(publication, output, aws)
    value["status"] = "verified"
    value["verified_at"] = datetime.now(timezone.utc).isoformat()
    value["retrieval_directory"] = str(downloaded)
    save(publication / RECEIPT, value)
    return publication, downloaded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aws-cli", type=Path, required=True)
    parser.add_argument("--profile", default="default", help="existing file-backed AWS profile")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("publish")
    create.add_argument("--backup-directory", type=Path, required=True)
    create.add_argument("--destination", type=Path, required=True)
    create.add_argument("--resume-directory", type=Path)
    download = commands.add_parser("retrieve")
    download.add_argument("--publication-directory", type=Path, required=True)
    download.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    previous = os.umask(0o077)
    try:
        aws = AWS(args.aws_cli, args.profile, destination())
        if args.command == "publish":
            publication, downloaded = publish(args.backup_directory, args.destination,
                                               aws, args.resume_directory)
            print(f"Verified offsite publication: {publication}")
        else:
            downloaded = retrieve(args.publication_directory, args.destination, aws)
        print(f"Version-specific download verified offline: {downloaded}")
        print("Control-plane restore and unattended offsite freshness were not tested.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("Offsite operation failed. Retain the original, publication receipt, and "
              "partial downloads; check local integrity and the existing AWS session. "
              "No remote cleanup was attempted.", file=sys.stderr)
        return 1
    finally:
        os.umask(previous)


if __name__ == "__main__":
    sys.exit(main())
