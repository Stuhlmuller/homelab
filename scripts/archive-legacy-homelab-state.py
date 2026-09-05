#!/usr/bin/env python3
"""Preserve exact legacy homelab state versions under AWS-managed S3 encryption.

Does not replace live state, remove original versions, or delete KMS keys.
Format reference: OpenTofu v1.11.5 internal/encryption/method/aesgcm/aesgcm.go.
"""
import base64
import hashlib
import json
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def decode_state(envelope, data_key):
    encrypted = base64.b64decode(envelope["encrypted_data"], validate=True)
    plaintext = AESGCM(data_key).decrypt(encrypted[:12], encrypted[12:], None)
    state = json.loads(plaintext)
    assert state["version"] == 4, "Unexpected state format"
    assert state["lineage"] == envelope["lineage"], "Lineage mismatch"
    assert state["serial"] == envelope["serial"], "Serial mismatch"
    return plaintext


def main():
    config = json.loads((Path(__file__).resolve().parent / "config/legacy-homelab-state-migration.json").read_text())
    session = boto3.Session()
    assert session.client("sts").get_caller_identity()["Account"] == config["account_id"]
    s3 = session.client("s3", region_name=config["region"])
    kms = session.client("kms", region_name=config["source_key_region"])
    target = session.client("kms", region_name=config["region"]).describe_key(KeyId=config["archive_kms_key"])["KeyMetadata"]
    assert target["KeyManager"] == "AWS"
    for source in config["versions"]:
        assert source["key"].startswith("IaC/homelab/")
        response = s3.get_object(Bucket=config["bucket"], Key=source["key"], VersionId=source["version"])
        envelope = json.loads(response["Body"].read())
        response["Body"].close()
        assert set(envelope["meta"]) == {"key_provider.aws_kms.main"}, "Unexpected encryption provider"
        metadata = json.loads(base64.b64decode(envelope["meta"]["key_provider.aws_kms.main"], validate=True))
        key = kms.decrypt(KeyId=config["source_key_arn"], CiphertextBlob=base64.b64decode(metadata["ciphertext_blob"], validate=True))
        assert key["KeyId"] == config["source_key_arn"]
        plaintext = decode_state(envelope, key.pop("Plaintext"))
        identity = json.dumps(source, sort_keys=True).encode()
        destination = config["archive_prefix"] + hashlib.sha256(identity).hexdigest() + ".tfstate"
        digest = hashlib.sha256(plaintext).hexdigest()
        try:
            s3.put_object(Bucket=config["bucket"], Key=destination, Body=plaintext,
                          ServerSideEncryption="aws:kms", SSEKMSKeyId=target["Arn"],
                          BucketKeyEnabled=True, IfNoneMatch="*",
                          Metadata={"sha256": digest, "source-key": source["key"], "source-version": source["version"]})
        except ClientError as error:
            if error.response["Error"]["Code"] != "PreconditionFailed":
                raise RuntimeError("Archive write failed; AWS details suppressed") from None
        archived = s3.get_object(Bucket=config["bucket"], Key=destination)
        restored = archived["Body"].read()
        archived["Body"].close()
        assert archived["ServerSideEncryption"] == "aws:kms" and archived["SSEKMSKeyId"] == target["Arn"]
        assert archived["Metadata"]["sha256"] == digest
        assert restored == plaintext, "Archive readback mismatch"
        del plaintext, restored
    print(f"Archived and verified {len(config['versions'])} historical homelab states; originals retained")


if __name__ == "__main__":
    main()
