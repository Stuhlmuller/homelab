#!/usr/bin/env python3
"""Retain S3-verified preflight and extraction receipts for the protected backup."""

import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time


spec = importlib.util.spec_from_file_location(
    "application_backup", Path(__file__).resolve().parents[1] / "application-backup.py"
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
MAX_PREFLIGHT_AGE = 4 * 60 * 60
MAX_RECEIPT_BYTES = 16 * 1024


def binding(run_id, stage, source_sha):
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("invalid workflow run ID")
    pvc_uid, pv_uid = os.environ["EXPECTED_PVC_UID"], os.environ["EXPECTED_PV_UID"]
    if (not re.fullmatch(r"[0-9a-f]{40}", source_sha)
            or not all(backup.RSC.UID.fullmatch(uid) for uid in (pvc_uid, pv_uid))):
        raise ValueError("invalid backup source or storage identity")
    return {"format": 1, "stage": stage, "source_sha": source_sha,
            "workflow_run_id": run_id, "pvc_uid": pvc_uid, "pv_uid": pv_uid}


def verify_preflight(aws, workspace, run_id, source_sha):
    expected = binding(run_id, "preflight", source_sha)
    key = f"applications/octelium-rscstore/preflight/{run_id}.json"
    args = ["--key", key, "--checksum-mode", "ENABLED"]
    metadata = aws.call("s3api", "head-object", args)
    version = metadata.get("VersionId")
    length = metadata.get("ContentLength")
    if (not isinstance(version, str) or not version or version == "null"
            or type(length) is not int or not 0 < length <= MAX_RECEIPT_BYTES):
        raise ValueError("invalid preflight object metadata")
    payload = workspace / "prior-preflight.json"
    if payload.exists() or payload.is_symlink():
        raise ValueError("preflight scratch already exists")
    returned = aws.call("s3api", "get-object", [*args, "--version-id", version, str(payload)])
    payload.chmod(0o600)
    digest = backup.OFFSITE.digest(payload)
    backup.OFFSITE.object_metadata(metadata, digest, version)
    backup.OFFSITE.object_metadata(returned, digest, version)
    receipt = json.loads(payload.read_text())
    created = receipt.pop("retained_at", None)
    if (receipt != expected or type(created) is not int
            or not 0 <= time.time() - created <= MAX_PREFLIGHT_AGE):
        raise ValueError("preflight source, storage identities or freshness differ")
    backup.write(workspace / "authorized-preflight.json", backup.canonical({
        **expected, "retained_at": created, "version_id": version,
    }))


def retain(aws, workspace, run_id, stage):
    receipt = binding(run_id, stage, os.environ["EXPECTED_SHA"])
    receipt["retained_at"] = int(time.time())
    payload = workspace / "workflow-receipt.json"
    if stage == "backup":
        proof = workspace / "proof/proof.json"
        backup.OFFSITE.private_file(proof)
        if proof.stat().st_size > MAX_RECEIPT_BYTES:
            raise ValueError("oversized proof")
        data = json.loads(proof.read_text())
        if (data.get("proof") != "isolated-file-extraction-only"
                or not backup.ID.fullmatch(data.get("capture_id", ""))):
            raise ValueError("unverified extraction receipt")
        receipt["extraction"] = data
    elif stage != "preflight":
        raise ValueError("unsupported receipt stage")
    backup.write(payload, backup.canonical(receipt))
    digest = backup.OFFSITE.digest(payload)
    key = f"applications/octelium-rscstore/{stage}/{run_id}.json"
    version = backup.upload(aws, key, payload, digest, create_only=True)
    backup.download(aws, key, {"digest": digest, "version_id": version},
                    workspace / "workflow-receipt-readback.json")


if __name__ == "__main__":
    workspace = backup.OFFSITE.backup.private_directory(Path(sys.argv[2]))
    aws = backup.OFFSITE.AWS(Path(sys.argv[1]), "octelium-rscstore", backup.target())
    aws.check()
    rules = aws.call("s3api", "get-bucket-encryption")["ServerSideEncryptionConfiguration"]["Rules"]
    if (len(rules) != 1 or rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] != "aws:kms"
            or rules[0].get("BucketKeyEnabled") is not True):
        raise ValueError("backup destination must have SSE-KMS and a bucket key")
    if sys.argv[4] == "authorize":
        verify_preflight(aws, workspace, sys.argv[3], sys.argv[5])
    else:
        retain(aws, workspace, sys.argv[3], sys.argv[4])
