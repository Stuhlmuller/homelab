#!/usr/bin/env python3
"""Source-only, fail-closed publisher for one encrypted Enterprise recovery set.

The caller must provide a protected credential context and a previously staged
material receipt. This module does not acquire credentials, dispatch a workflow,
close a writer fence, or promote a backup receipt.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


CHAIN = module("oce_s3_publish_chain", "scripts/ci/openclaw-enterprise-recovery-chain.py")
PROOF = module("oce_s3_publish_proof", "scripts/ci/openclaw-enterprise-s3-proof.py")
PART_SIZE = 64 * 1024 * 1024
MAX_PARTS = 10_000
MATERIAL_FIELDS = {
    "scope", "publishable", "sourceSha", "backupId", "materialSha256",
    "markerSha256", "installationId", "namespaceId", "agentId", "revisionId",
}


class Blocked(RuntimeError):
    pass


def require(condition):
    if not condition:
        raise Blocked("Enterprise ciphertext publication is incomplete or changed")


def _destination(material):
    require(isinstance(material, dict) and set(material) == MATERIAL_FIELDS and
            material["scope"] == "source-only-material" and
            material["publishable"] is False and
            isinstance(material.get("sourceSha"), str) and
            CHAIN.SHA.fullmatch(material["sourceSha"]) and
            all(isinstance(material.get(key), str) and
                CHAIN.HEX64.fullmatch(material[key])
                for key in ("backupId", "materialSha256", "markerSha256")) and
            all(CHAIN.OCE._valid_resource_id(material.get(field), prefix)
                for field, prefix in (("installationId", "ins_"),
                                      ("namespaceId", "ns_"),
                                      ("agentId", "agt_"),
                                      ("revisionId", "rev_"))))
    target = CHAIN.OFFSITE.read_inputs(ROOT / "IaC/application-backup-storage.hcl")
    require(set(target) == {"account_id", "region", "bucket"} and
            re.fullmatch(r"[0-9]{12}", target["account_id"]) and
            target["region"] == "us-east-1" and
            target["bucket"] ==
            f"homelab-application-backups-{target['account_id']}-us-east-1")
    return target, f"openclaw-enterprise/new/{material['backupId']}.tar.age"


def _private_scratch(path):
    path = Path(path)
    try:
        info = path.lstat()
        require(path.is_absolute() and path.resolve() == path and
                stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and
                stat.S_IMODE(info.st_mode) == 0o700)
    except OSError:
        raise Blocked("Enterprise publication scratch is unavailable") from None
    return path


def _context(run, target):
    account = target["account_id"]
    identity = PROOF._aws(run, ("sts", "get-caller-identity"))
    require(identity.get("Account") == account and
            isinstance(identity.get("Arn"), str) and
            re.fullmatch(rf"arn:aws:sts::{account}:assumed-role/"
                         r"homelab-oce-recovery-publisher/[A-Za-z0-9+=,.@_-]+",
                         identity["Arn"]))
    common = ("--bucket", target["bucket"], "--expected-bucket-owner", account)
    versioning = PROOF._aws(run, ("s3api", "get-bucket-versioning"), *common)
    require(versioning.get("Status") == "Enabled")
    encryption = PROOF._aws(run, ("s3api", "get-bucket-encryption"), *common)
    configuration = encryption.get("ServerSideEncryptionConfiguration")
    require(isinstance(configuration, dict) and configuration.get("Rules") == [{
        "ApplyServerSideEncryptionByDefault": {
            "SSEAlgorithm": "aws:kms",
            "KMSMasterKeyID": f"arn:aws:kms:us-east-1:{account}:alias/aws/s3",
        },
        "BucketKeyEnabled": True,
    }])
    return common


def _unused_key(run, common, key):
    versions = PROOF._aws(run, ("s3api", "list-object-versions"), *common,
                          "--prefix", key, "--max-keys", "1000")
    require(versions.get("IsTruncated") in (None, False) and
            all(isinstance(versions.get(field, []), list) and
                all(isinstance(item, dict) and item.get("Key") != key
                    for item in versions.get(field, []))
                for field in ("Versions", "DeleteMarkers")))


def _stable_ciphertext(path):
    try:
        record = CHAIN._private_file_digest(path, CHAIN.MAX_CIPHERTEXT_BYTES)
        metadata = Path(path).lstat()
        require(record["bytes"] > 0 and stat.S_ISREG(metadata.st_mode))
        return record, CHAIN._identity(metadata)
    except (CHAIN.Blocked, OSError):
        raise Blocked("Enterprise ciphertext file is unavailable") from None


def _upload_parts(run, path, scratch, common, key, upload_id, expected, identity):
    parts = []
    digest = hashlib.sha256()
    total = 0
    with tempfile.TemporaryDirectory(prefix="oce-s3-publish-", dir=scratch) as directory:
        body = Path(directory) / "part"
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW |
                             os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            with os.fdopen(descriptor, "rb") as source:
                require(CHAIN._identity(os.fstat(source.fileno())) == identity)
                while total < expected["bytes"]:
                    count = min(PART_SIZE, expected["bytes"] - total)
                    body_descriptor = os.open(body, os.O_WRONLY | os.O_CREAT |
                                              os.O_EXCL | os.O_CLOEXEC, 0o600)
                    with os.fdopen(body_descriptor, "wb") as output:
                        remaining = count
                        while remaining:
                            chunk = source.read(min(1024 * 1024, remaining))
                            require(bool(chunk))
                            output.write(chunk)
                            digest.update(chunk)
                            remaining -= len(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    require(body.stat().st_size == count)
                    part = PROOF._aws(run, ("s3api", "upload-part"), *common,
                                      "--key", key, "--upload-id", upload_id,
                                      "--part-number", str(len(parts) + 1),
                                      "--body", str(body), timeout=600)
                    etag = part.get("ETag")
                    require(isinstance(etag, str) and 1 <= len(etag) <= 256 and
                            all(32 <= ord(char) < 127 for char in etag))
                    parts.append({"ETag": etag, "PartNumber": len(parts) + 1})
                    total += count
                    body.unlink()
                require(source.read(1) == b"" and
                        CHAIN._identity(os.fstat(source.fileno())) == identity)
        except OSError:
            raise Blocked("Enterprise ciphertext transfer failed") from None
        require(total == expected["bytes"] and
                digest.hexdigest() == expected["sha256"] and
                CHAIN._identity(Path(path).lstat()) == identity and
                len(parts) <= MAX_PARTS)
        manifest = Path(directory) / "parts.json"
        manifest_descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT |
                                      os.O_EXCL | os.O_CLOEXEC, 0o600)
        with os.fdopen(manifest_descriptor, "w") as output:
            output.write(json.dumps({"Parts": parts}, separators=(",", ":")))
            output.flush()
            os.fsync(output.fileno())
        return PROOF._aws(run, ("s3api", "complete-multipart-upload"), *common,
                          "--key", key, "--upload-id", upload_id,
                          "--multipart-upload", f"file://{manifest}",
                          "--if-none-match", "*", timeout=600)


def publish_ciphertext(material, ciphertext, scratch, *, run,
                       readback=PROOF.verify_object_version):
    """Upload once and read back an exact version; never infer a restore receipt."""
    target, key = _destination(material)
    scratch = _private_scratch(scratch)
    ciphertext = Path(ciphertext)
    expected, identity = _stable_ciphertext(ciphertext)
    require((expected["bytes"] + PART_SIZE - 1) // PART_SIZE <= MAX_PARTS and
            scratch != ciphertext.parent)
    common = _context(run, target)
    _unused_key(run, common, key)
    metadata = {
        "source-sha": material["sourceSha"],
        "backup-id": material["backupId"],
        "material-sha256": material["materialSha256"],
        "ciphertext-sha256": expected["sha256"],
    }
    created = PROOF._aws(run, ("s3api", "create-multipart-upload"), *common,
                         "--key", key, "--metadata", json.dumps(metadata),
                         "--server-side-encryption", "aws:kms",
                         "--ssekms-key-id",
                         f"arn:aws:kms:us-east-1:{target['account_id']}:alias/aws/s3",
                         "--bucket-key-enabled")
    upload_id = created.get("UploadId")
    require(isinstance(upload_id, str) and 1 <= len(upload_id) <= 1024 and
            all(32 <= ord(char) < 127 for char in upload_id))
    try:
        completed = _upload_parts(run, ciphertext, scratch, common, key,
                                  upload_id, expected, identity)
    except (Blocked, PROOF.Blocked, OSError):
        try:
            PROOF._aws(run, ("s3api", "abort-multipart-upload"), *common,
                       "--key", key, "--upload-id", upload_id)
        except (Blocked, PROOF.Blocked, OSError):
            pass
        raise Blocked("Enterprise multipart publication failed; outcome unverified") from None
    version = completed.get("VersionId")
    require(isinstance(version, str) and 0 < len(version) <= 1024 and
            version != "null" and not version.startswith("-") and
            all(32 <= ord(char) < 127 for char in version))
    object_record = {
        "sourceSha": material["sourceSha"], "backupId": material["backupId"],
        "materialSha256": material["materialSha256"],
        "ciphertextSha256": expected["sha256"],
        "ciphertextBytes": expected["bytes"], "bucket": target["bucket"],
        "key": key, "versionId": version,
    }
    proof = readback(object_record, run=run)
    require(proof.get("scope") == "s3-version-readback" and
            proof.get("publishable") is False and
            all(proof.get(field) == object_record[field]
                for field in ("sourceSha", "backupId", "materialSha256",
                              "ciphertextSha256", "ciphertextBytes", "bucket",
                              "key", "versionId")))
    require(_stable_ciphertext(ciphertext)[0] == expected and
            CHAIN._identity(ciphertext.lstat()) == identity)
    return {"scope": "source-only-s3-publication", "publishable": False,
            **object_record}
