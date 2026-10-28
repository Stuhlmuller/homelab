#!/usr/bin/env python3
"""Copy exact Langfuse raw-object versions into a private, versioned offsite set."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "IaC/langfuse-blob-storage.hcl"
DESTINATION = ROOT / "IaC/application-backup-storage.hcl"
VALUES = ROOT / "clusters/homelab/apps/langfuse/values.yaml"
MAX_PAGES = 100
MAX_OBJECTS = 10000
MAX_BYTES = 5 * 1024**3
HTTP_PROPERTIES = {
    "CacheControl": "--cache-control",
    "ContentDisposition": "--content-disposition",
    "ContentEncoding": "--content-encoding",
    "ContentLanguage": "--content-language",
    "ContentType": "--content-type",
    "Expires": "--expires",
    "WebsiteRedirectLocation": "--website-redirect-location",
}


class BackupBlocked(Exception):
    pass


def hcl_string(path, key):
    values = re.findall(rf'^\s*{key}\s*=\s*"([a-z0-9-]+)"\s*$', path.read_text(), re.M)
    if len(values) != 1:
        raise BackupBlocked("bucket declaration is ambiguous")
    return values[0]


def declared_buckets():
    account = hcl_string(SOURCE, "account_id")
    source_region = hcl_string(SOURCE, "region")
    source = hcl_string(SOURCE, "bucket")
    destination_account = hcl_string(DESTINATION, "account_id")
    destination_region = hcl_string(DESTINATION, "region")
    destination = hcl_string(DESTINATION, "bucket")
    if (not re.fullmatch(r"[0-9]{12}", account) or source_region != "us-west-2" or
            destination_account != account or destination_region != "us-east-1" or
            source != f"homelab-langfuse-{account}-{source_region}" or
            destination != f"homelab-application-backups-{account}-us-east-1"):
        raise BackupBlocked("bucket identity differs from the committed contract")
    configured = re.findall(r"^\s*bucket:\s*(homelab-langfuse-[a-z0-9-]+)\s*$",
                            VALUES.read_text(), re.M)
    if configured != [source]:
        raise BackupBlocked("workload raw bucket differs from infrastructure")
    return account, source, destination


def aws(region, *arguments, file=None):
    command = ["aws", "--region", region, "--no-cli-pager", "s3api", *arguments]
    if file is not None:
        command.append(str(file))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise BackupBlocked("private AWS object operation failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BackupBlocked("AWS object response is invalid") from error


def bucket_ready(call, region, bucket, account):
    owner = ("--expected-bucket-owner", account)
    versioning = call(region, "get-bucket-versioning", "--bucket", bucket, *owner)
    if versioning.get("Status") != "Enabled":
        raise BackupBlocked("bucket versioning is not enabled")
    encryption = call(region, "get-bucket-encryption", "--bucket", bucket, *owner)
    config = encryption.get("ServerSideEncryptionConfiguration")
    rules = config.get("Rules", []) if isinstance(config, dict) else []
    if not isinstance(rules, list) or not any(
            isinstance(rule, dict) and
            isinstance(rule.get("ApplyServerSideEncryptionByDefault"), dict) and
            rule["ApplyServerSideEncryptionByDefault"].get("SSEAlgorithm") == "aws:kms" and
            rule.get("BucketKeyEnabled") is True
            for rule in rules):
        raise BackupBlocked("bucket KMS encryption is not enabled")


def list_versions(call, bucket, account):
    owner = ("--expected-bucket-owner", account)
    result = []
    marker = None
    seen = set()
    total_bytes = 0
    for _ in range(MAX_PAGES):
        args = ["list-object-versions", "--bucket", bucket, *owner,
                "--no-paginate", "--max-keys", "1000"]
        if marker:
            args.extend(("--key-marker", marker[0]))
            if marker[1]:
                args.extend(("--version-id-marker", marker[1]))
        page = call("us-west-2", *args)
        if type(page.get("IsTruncated")) is not bool:
            raise BackupBlocked("raw version page has no truncation state")
        for label, entries in (("object", page.get("Versions", [])),
                               ("delete", page.get("DeleteMarkers", []))):
            if not isinstance(entries, list):
                raise BackupBlocked("raw version page is malformed")
            for entry in entries:
                key, version = entry.get("Key"), entry.get("VersionId")
                if not isinstance(key, str) or not key or not isinstance(version, str) or not version:
                    raise BackupBlocked("raw version identity is missing")
                identity = (key, version)
                if identity in seen:
                    raise BackupBlocked("raw version repeats across pages")
                seen.add(identity)
                item = {"kind": label, "key": key, "version": version,
                        "last_modified": entry.get("LastModified"),
                        "is_latest": entry.get("IsLatest")}
                if not isinstance(item["last_modified"], str) or type(item["is_latest"]) is not bool:
                    raise BackupBlocked("raw version ordering is incomplete")
                if label == "object":
                    size = entry.get("Size")
                    if type(size) is not int or size < 0:
                        raise BackupBlocked("raw version size is invalid")
                    item["bytes"] = size
                    total_bytes += size
                result.append(item)
                if len(result) > MAX_OBJECTS or total_bytes > MAX_BYTES:
                    raise BackupBlocked("raw version set exceeds the reviewed copy budget")
        if not page["IsTruncated"]:
            return sorted(result, key=lambda item: (item["key"], item["version"])), total_bytes
        next_key = page.get("NextKeyMarker")
        next_version = page.get("NextVersionIdMarker") or ""
        next_marker = (next_key, next_version)
        if not isinstance(next_key, str) or not next_key or not isinstance(next_version, str) or next_marker == marker:
            raise BackupBlocked("raw version pagination is incomplete")
        marker = next_marker
    raise BackupBlocked("raw version inventory exceeds page budget")


def digest_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def object_key(prefix, item):
    identity = (item["key"] + "\0" + item["version"]).encode()
    return prefix + "/objects/" + hashlib.sha256(identity).hexdigest()


def object_properties(response):
    if response.get("StorageClass", "STANDARD") != "STANDARD" or any(
            field in response for field in (
                "ObjectLockMode", "ObjectLockRetainUntilDate", "ObjectLockLegalHoldStatus")):
        raise BackupBlocked("raw version has unsupported retention properties")
    properties = {}
    for name in HTTP_PROPERTIES:
        if name in response:
            if not isinstance(response[name], str):
                raise BackupBlocked("raw version HTTP property is malformed")
            properties[name] = response[name]
    metadata = response.get("Metadata", {})
    if (not isinstance(metadata, dict) or
            any(not isinstance(key, str) or not isinstance(value, str)
                for key, value in metadata.items())):
        raise BackupBlocked("raw version user metadata is malformed")
    properties["Metadata"] = metadata
    return properties


def get_version_tags(call, region, bucket, account, key, version):
    result = call(region, "get-object-tagging", "--bucket", bucket,
                  "--key", key, "--version-id", version,
                  "--expected-bucket-owner", account)
    if result.get("VersionId") != version or not isinstance(result.get("TagSet"), list):
        raise BackupBlocked("raw version tag response is incomplete")
    tags = result["TagSet"]
    if (len(tags) > 10 or any(not isinstance(tag, dict) or
                             not isinstance(tag.get("Key"), str) or not tag["Key"] or
                             not isinstance(tag.get("Value"), str) for tag in tags)):
        raise BackupBlocked("raw version tag response is malformed")
    if len({tag["Key"] for tag in tags}) != len(tags):
        raise BackupBlocked("raw version tags repeat")
    return sorted(tags, key=lambda tag: tag["Key"])


def copy_version(call, source, destination, account, prefix, item, scratch):
    source_file = scratch / "source.bin"
    dest_file = scratch / "readback.bin"
    owner = ("--expected-bucket-owner", account)
    try:
        received = call("us-west-2", "get-object", "--bucket", source,
                        "--key", item["key"], "--version-id", item["version"], *owner,
                        file=source_file)
        source_hash, actual_size = digest_file(source_file)
        if (received.get("VersionId") != item["version"] or
                received.get("ContentLength") != item["bytes"] or
                received.get("ServerSideEncryption") != "aws:kms" or
                actual_size != item["bytes"]):
            raise BackupBlocked("raw version bytes differ from inventory")
        properties = object_properties(received)
        tags = get_version_tags(call, "us-west-2", source, account,
                                item["key"], item["version"])
        headers = []
        for field, option in HTTP_PROPERTIES.items():
            if field in properties:
                headers.extend((option, properties[field]))
        if properties["Metadata"]:
            headers.extend(("--metadata", json.dumps(properties["Metadata"],
                                                    sort_keys=True, separators=(",", ":"))))
        if tags:
            headers.extend(("--tagging", urlencode([(tag["Key"], tag["Value"])
                                                     for tag in tags])))
        key = object_key(prefix, item)
        published = call("us-east-1", "put-object", "--bucket", destination,
                         "--key", key, "--body", str(source_file),
                         "--server-side-encryption", "aws:kms", "--if-none-match", "*",
                         *headers, *owner)
        version = published.get("VersionId")
        if not isinstance(version, str) or not version or version == "null":
            raise BackupBlocked("offsite object has no immutable version")
        source_file.unlink()
        readback = call("us-east-1", "get-object", "--bucket", destination,
                        "--key", key, "--version-id", version, *owner, file=dest_file)
        verified_hash, verified_size = digest_file(dest_file)
        if (readback.get("VersionId") != version or
                readback.get("ServerSideEncryption") != "aws:kms" or
                readback.get("ContentLength") != item["bytes"] or
                object_properties(readback) != properties or
                get_version_tags(call, "us-east-1", destination, account,
                                 key, version) != tags or
                verified_hash != source_hash or verified_size != item["bytes"]):
            raise BackupBlocked("offsite object readback differs from source")
        return {**item, "sha256": source_hash, "properties": properties, "tags": tags,
                "offsite_key": key, "offsite_version": version}
    finally:
        source_file.unlink(missing_ok=True)
        dest_file.unlink(missing_ok=True)


def publish_complete(call, destination, account, prefix, manifest, scratch):
    content = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    source_file = scratch / "complete.json"
    dest_file = scratch / "complete-readback.json"
    source_file.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    key = prefix + "/complete.json"
    owner = ("--expected-bucket-owner", account)
    try:
        published = call("us-east-1", "put-object", "--bucket", destination,
                         "--key", key, "--body", str(source_file),
                         "--server-side-encryption", "aws:kms", "--if-none-match", "*",
                         "--metadata", f"sha256={digest}", *owner)
        version = published.get("VersionId")
        if not isinstance(version, str) or not version or version == "null":
            raise BackupBlocked("offsite completion marker has no version")
        readback = call("us-east-1", "get-object", "--bucket", destination,
                        "--key", key, "--version-id", version, *owner, file=dest_file)
        if (readback.get("VersionId") != version or
                readback.get("ServerSideEncryption") != "aws:kms" or
                readback.get("ContentLength") != len(content) or
                readback.get("Metadata", {}).get("sha256") != digest or
                dest_file.read_bytes() != content):
            raise BackupBlocked("offsite completion marker readback failed")
        return digest
    finally:
        source_file.unlink(missing_ok=True)
        dest_file.unlink(missing_ok=True)


def backup(call, account, source, destination, prefix, scratch):
    bucket_ready(call, "us-west-2", source, account)
    bucket_ready(call, "us-east-1", destination, account)
    before, total_bytes = list_versions(call, source, account)
    if not before:
        raise BackupBlocked("raw version set is empty")
    copied = []
    for item in before:
        copied.append(copy_version(call, source, destination, account, prefix, item, scratch)
                      if item["kind"] == "object" else item)
    after, after_bytes = list_versions(call, source, account)
    if after != before or after_bytes != total_bytes:
        raise BackupBlocked("raw version set changed during copy")
    for item in copied:
        if item["kind"] == "object" and get_version_tags(
                call, "us-west-2", source, account, item["key"], item["version"]) != item["tags"]:
            raise BackupBlocked("raw version tags changed during copy")
    manifest = {"format": 1, "source_bucket": source, "offsite_bucket": destination,
                "prefix": prefix, "items": copied}
    digest = publish_complete(call, destination, account, prefix, manifest, scratch)
    return sum(item["kind"] == "object" for item in before), total_bytes, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    try:
        if (not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) or
                not re.fullmatch(r"[1-9][0-9]*", args.run_id) or
                not re.fullmatch(r"[1-9][0-9]*", args.run_attempt) or
                not args.scratch.is_dir()):
            raise BackupBlocked("protected run identity is invalid")
        account, source, destination = declared_buckets()
        identity = subprocess.run(["aws", "sts", "get-caller-identity", "--output", "json"],
                                  capture_output=True, text=True, check=False)
        if identity.returncode or json.loads(identity.stdout).get("Account") != account:
            raise BackupBlocked("AWS account differs from bucket owner")
        prefix = (f"langfuse/raw-versions/{args.expected_sha}/"
                  f"{args.run_id}/{args.run_attempt}")
        with tempfile.TemporaryDirectory(prefix="langfuse-raw-", dir=args.scratch) as temp:
            count, size, digest = backup(aws, account, source, destination,
                                         prefix, Path(temp))
        print(f"Langfuse raw versions copied: objects={count} bytes={size} sha256={digest}")
    except (BackupBlocked, OSError, json.JSONDecodeError) as error:
        print(f"Langfuse raw version backup blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
