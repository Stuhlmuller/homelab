#!/usr/bin/env python3
"""Read back one exact Enterprise ciphertext version with scoped AWS identity.

This only proves that the proposed ciphertext bytes exist in the declared
versioned, KMS-encrypted bucket. It does not prove publication run provenance,
an isolated restore, or a continuous writer fence; its receipt is never
publishable.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "oce_s3_proof_chain", ROOT / "scripts/ci/openclaw-enterprise-recovery-chain.py")
CHAIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHAIN)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
PART_SIZE = 64 * 1024 * 1024
MAX_JSON = 128 * 1024
RECEIPT_FIELDS = {
    "scope", "publishable", "sourceSha", "backupId", "materialSha256",
    "installationId", "namespaceId", "agentId", "revisionId",
    "ciphertextSha256", "ciphertextBytes", "bucket", "key", "versionId",
    "publisherRunId", "restoreRunId",
}


class Blocked(RuntimeError):
    pass


def require(condition):
    if not condition:
        raise Blocked("Enterprise S3 readback is incomplete or changed")


def _aws(run, operation, *args, timeout=90):
    service, command = operation
    invocation = ["aws", "--region", "us-east-1", service, command, *args,
                  "--output", "json"]
    try:
        result = run(invocation, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                     timeout=timeout, check=False)
        require(result.returncode == 0 and
                isinstance(result.stdout, bytes) and
                len(result.stdout) <= MAX_JSON)
        value = json.loads(result.stdout)
        require(isinstance(value, dict))
        return value
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError):
        raise Blocked("Enterprise S3 request failed") from None


def _inputs(receipt):
    require(isinstance(receipt, dict) and set(receipt) == RECEIPT_FIELDS and
            receipt["scope"] == "source-only-recovery-chain" and
            receipt["publishable"] is False and
            all(isinstance(receipt.get(key), str) and HEX64.fullmatch(receipt[key])
                for key in ("backupId", "materialSha256", "ciphertextSha256")) and
            isinstance(receipt.get("sourceSha"), str) and
            SHA.fullmatch(receipt["sourceSha"]) and
            type(receipt.get("ciphertextBytes")) is int and
            0 < receipt["ciphertextBytes"] <= CHAIN.MAX_CIPHERTEXT_BYTES and
            all(CHAIN.OCE._valid_resource_id(receipt.get(field), prefix)
                for field, prefix in (("installationId", "ins_"),
                                      ("namespaceId", "ns_"),
                                      ("agentId", "agt_"),
                                      ("revisionId", "rev_"))) and
            all(type(receipt.get(key)) is int and receipt[key] > 0
                for key in ("publisherRunId", "restoreRunId")) and
            receipt["publisherRunId"] != receipt["restoreRunId"] and
            isinstance(receipt.get("versionId"), str) and
            0 < len(receipt["versionId"]) <= 1024 and
            receipt["versionId"] != "null" and
            not receipt["versionId"].startswith("-") and
            all(32 <= ord(char) < 127 for char in receipt["versionId"]))
    destination = CHAIN.OFFSITE.read_inputs(ROOT / "IaC/application-backup-storage.hcl")
    require(set(destination) == {"account_id", "region", "bucket"} and
            re.fullmatch(r"[0-9]{12}", destination["account_id"]) and
            destination["region"] == "us-east-1" and
            destination["bucket"] ==
            f"homelab-application-backups-{destination['account_id']}-us-east-1" and
            receipt["bucket"] == destination["bucket"] and
            receipt["key"] ==
            f"openclaw-enterprise/new/{receipt['backupId']}.tar.age")
    return destination


def _kms(value, account):
    require(value.get("ServerSideEncryption") == "aws:kms" and
            isinstance(value.get("SSEKMSKeyId"), str) and
            re.fullmatch(rf"arn:aws:kms:us-east-1:{account}:key/[A-Za-z0-9-]+",
                         value["SSEKMSKeyId"]))


def _file_identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode, value.st_uid, value.st_nlink)


def _verify_version(receipt, run):
    """Hash every byte of the exact S3 version through bounded range reads."""
    destination = _inputs(receipt)
    account = destination["account_id"]
    identity = _aws(run, ("sts", "get-caller-identity"))
    require(identity.get("Account") == account and
            isinstance(identity.get("Arn"), str) and
            re.fullmatch(rf"arn:aws:sts::{account}:assumed-role/"
                         r"homelab-oce-recovery-publisher/[A-Za-z0-9+=,.@_-]+",
                         identity["Arn"]))
    common = ("--bucket", receipt["bucket"], "--expected-bucket-owner", account)
    versioning = _aws(run, ("s3api", "get-bucket-versioning"), *common)
    require(versioning.get("Status") == "Enabled")
    encryption = _aws(run, ("s3api", "get-bucket-encryption"), *common)
    rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules")
    require(isinstance(rules, list) and len(rules) == 1 and
            isinstance(rules[0], dict) and
            rules[0].get("ApplyServerSideEncryptionByDefault") == {
                "SSEAlgorithm": "aws:kms",
                "KMSMasterKeyID":
                f"arn:aws:kms:us-east-1:{account}:alias/aws/s3",
            } and rules[0].get("BucketKeyEnabled") is True)
    source = (*common, "--key", receipt["key"], "--version-id", receipt["versionId"])
    head = _aws(run, ("s3api", "head-object"), *source)
    _kms(head, account)
    require(head.get("VersionId") == receipt["versionId"] and
            type(head.get("ContentLength")) is int and
            head["ContentLength"] == receipt["ciphertextBytes"] and
            head.get("Metadata") == {
                "source-sha": receipt["sourceSha"],
                "backup-id": receipt["backupId"],
                "material-sha256": receipt["materialSha256"],
                "ciphertext-sha256": receipt["ciphertextSha256"],
            })
    digest = hashlib.sha256()
    total = 0
    with tempfile.TemporaryDirectory(prefix="oce-s3-readback-") as directory:
        body = Path(directory) / "range"
        while total < receipt["ciphertextBytes"]:
            count = min(PART_SIZE, receipt["ciphertextBytes"] - total)
            end = total + count - 1
            response = _aws(run, ("s3api", "get-object"), *source, "--range",
                            f"bytes={total}-{end}", str(body), timeout=600)
            _kms(response, account)
            require(response.get("SSEKMSKeyId") == head["SSEKMSKeyId"] and
                    response.get("VersionId") == receipt["versionId"] and
                    response.get("ContentRange") ==
                    f"bytes {total}-{end}/{receipt['ciphertextBytes']}" and
                    response.get("ContentLength") == count)
            try:
                metadata = body.lstat()
                require(stat.S_ISREG(metadata.st_mode) and
                        metadata.st_uid == os.getuid() and
                        stat.S_IMODE(metadata.st_mode) == 0o600 and
                        metadata.st_nlink == 1 and metadata.st_size == count)
                descriptor = os.open(body, os.O_RDONLY | os.O_NOFOLLOW |
                                     os.O_CLOEXEC | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as stream:
                    require(_file_identity(os.fstat(stream.fileno())) ==
                            _file_identity(metadata))
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                    require(_file_identity(os.fstat(stream.fileno())) ==
                            _file_identity(metadata))
                require(_file_identity(body.lstat()) == _file_identity(metadata))
                body.unlink()
            except OSError:
                raise Blocked("Enterprise S3 readback file is unavailable") from None
            total += count
    require(total == receipt["ciphertextBytes"] and
            digest.hexdigest() == receipt["ciphertextSha256"])
    return {"scope": "s3-version-readback", "publishable": False,
            "sourceSha": receipt["sourceSha"], "backupId": receipt["backupId"],
            "materialSha256": receipt["materialSha256"],
            "bucket": receipt["bucket"], "key": receipt["key"],
            "versionId": receipt["versionId"],
            "ciphertextBytes": total, "ciphertextSha256": digest.hexdigest(),
            "kms": "aws:kms", "versioning": "Enabled"}


def verify_version(receipt, *, run=subprocess.run):
    """Run the readback with private local file creation for AWS CLI bodies."""
    previous_umask = os.umask(0o077)
    try:
        return _verify_version(receipt, run)
    finally:
        os.umask(previous_umask)


def _write_private_receipt(path, proof):
    output = Path(path)
    parent = output.parent.lstat()
    require(output.is_absolute() and output.parent.resolve() == output.parent and
            stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid() and
            stat.S_IMODE(parent.st_mode) == 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".oce-s3-proof-", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(proof, sort_keys=True,
                                    separators=(",", ":")).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output, follow_symlinks=False)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain-receipt", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        source = CHAIN._private_json(args.chain_receipt)
        proof = verify_version(source)
        _write_private_receipt(args.receipt, proof)
    except (Blocked, CHAIN.Blocked, OSError, ValueError):
        raise SystemExit("Enterprise S3 readback blocked; private diagnostics withheld") from None


if __name__ == "__main__":
    main()
