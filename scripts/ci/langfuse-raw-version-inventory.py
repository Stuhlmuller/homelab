#!/usr/bin/env python3
"""Privately inventory every version of Langfuse's expiring raw-object bucket."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "IaC/langfuse-blob-storage.hcl"


class InventoryBlocked(Exception):
    pass


def declared_bucket():
    source = CONFIG.read_text()
    values = {}
    for key in ("account_id", "region", "bucket"):
        matches = re.findall(rf'^\s*{key}\s*=\s*"([a-z0-9-]+)"\s*$', source, re.M)
        if len(matches) != 1:
            raise InventoryBlocked("bucket declaration is ambiguous")
        values[key] = matches[0]
    if (not re.fullmatch(r"[0-9]{12}", values["account_id"]) or
            values["region"] != "us-west-2" or
            values["bucket"] != f'homelab-langfuse-{values["account_id"]}-{values["region"]}'):
        raise InventoryBlocked("bucket declaration changed")
    return values


def aws(*args):
    result = subprocess.run(["aws", "--region", "us-west-2", *args],
                            text=True, capture_output=True, check=False)
    if result.returncode:
        raise InventoryBlocked("AWS version inventory read failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InventoryBlocked("AWS version inventory response is invalid") from error


def inventory(call, bucket, account):
    owner = ("--expected-bucket-owner", account)
    versioning = call("s3api", "get-bucket-versioning", "--bucket", bucket, *owner)
    if versioning.get("Status") != "Enabled":
        raise InventoryBlocked("raw-object bucket versioning is not enabled")
    encryption = call("s3api", "get-bucket-encryption", "--bucket", bucket, *owner)
    configuration = encryption.get("ServerSideEncryptionConfiguration")
    rules = configuration.get("Rules", []) if isinstance(configuration, dict) else []
    if not isinstance(rules, list) or not any(
            isinstance(rule, dict) and
            isinstance(rule.get("ApplyServerSideEncryptionByDefault"), dict) and
            rule["ApplyServerSideEncryptionByDefault"].get("SSEAlgorithm") == "aws:kms"
            for rule in rules):
        raise InventoryBlocked("raw-object bucket KMS encryption is not enabled")
    seen = set()
    objects = []
    deletes = []
    marker = None
    for _ in range(100):
        args = ["s3api", "list-object-versions", "--bucket", bucket, *owner,
                "--no-paginate", "--max-keys", "1000"]
        if marker:
            args.extend(("--key-marker", marker[0]))
            if marker[1]:
                args.extend(("--version-id-marker", marker[1]))
        page = call(*args)
        if type(page.get("IsTruncated")) is not bool:
            raise InventoryBlocked("raw-object version page lacks truncation state")
        for kind, entries, output in (("object", page.get("Versions", []), objects),
                                      ("delete", page.get("DeleteMarkers", []), deletes)):
            if not isinstance(entries, list):
                raise InventoryBlocked("raw-object version page is malformed")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise InventoryBlocked("raw-object version entry is malformed")
                key, version = entry.get("Key"), entry.get("VersionId")
                if not isinstance(key, str) or not key or not isinstance(version, str) or not version:
                    raise InventoryBlocked("raw-object version identity is missing")
                identity = (key, version)
                if identity in seen:
                    raise InventoryBlocked("raw-object version repeats across pages")
                seen.add(identity)
                item = {"key": key, "version": version}
                if kind == "object":
                    size = entry.get("Size")
                    if type(size) is not int or size < 0:
                        raise InventoryBlocked("raw-object version size is invalid")
                    head = call("s3api", "head-object", "--bucket", bucket,
                                "--key", key, "--version-id", version, *owner)
                    if (head.get("VersionId") != version or
                            head.get("ContentLength") != size or
                            head.get("ServerSideEncryption") != "aws:kms"):
                        raise InventoryBlocked("raw-object version readback differs from inventory")
                    get_args = ["s3api", "get-object", "--bucket", bucket,
                                "--key", key, "--version-id", version, *owner]
                    if size:
                        get_args.extend(("--range", "bytes=0-0"))
                    probe = call(*get_args, os.devnull)
                    if (probe.get("VersionId") != version or
                            probe.get("ContentLength") != min(size, 1) or
                            probe.get("ServerSideEncryption") != "aws:kms" or
                            (size and probe.get("ContentRange") != f"bytes 0-0/{size}")):
                        raise InventoryBlocked("raw-object version content probe failed")
                    item["bytes"] = size
                output.append(item)
        if not page["IsTruncated"]:
            return {"bucket": bucket, "account": account,
                    "objects": sorted(objects, key=lambda x: (x["key"], x["version"])),
                    "delete_markers": sorted(deletes, key=lambda x: (x["key"], x["version"]))}
        next_key = page.get("NextKeyMarker")
        next_version = page.get("NextVersionIdMarker") or ""
        next_marker = (next_key, next_version)
        if not isinstance(next_key, str) or not next_key or not isinstance(next_version, str) or next_marker == marker:
            raise InventoryBlocked("raw-object version pagination is incomplete")
        marker = next_marker
    raise InventoryBlocked("raw-object version inventory exceeds page budget")


def write_private(path, report):
    if path.exists() or not path.parent.is_dir():
        raise InventoryBlocked("inventory destination must be absent in an existing directory")
    content = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    return hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        values = declared_bucket()
        identity = aws("sts", "get-caller-identity")
        if identity.get("Account") != values["account_id"]:
            raise InventoryBlocked("AWS account differs from bucket owner")
        report = inventory(aws, values["bucket"], values["account_id"])
        digest = write_private(args.output, report)
        print(f'Langfuse raw versions inventoried: objects={len(report["objects"])} '
              f'delete_markers={len(report["delete_markers"])} '
              f'bytes={sum(item["bytes"] for item in report["objects"])} sha256={digest}')
    except (InventoryBlocked, OSError) as error:
        print(f"Langfuse raw version inventory blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
