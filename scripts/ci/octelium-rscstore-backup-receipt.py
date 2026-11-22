#!/usr/bin/env python3
"""Retain S3-verified preflight and extraction receipts for the protected backup."""

import importlib.util
import json
import os
from pathlib import Path
import re
import sys


spec = importlib.util.spec_from_file_location(
    "application_backup", Path(__file__).resolve().parents[1] / "application-backup.py"
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def retain(executable, workspace, run_id, stage):
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("invalid workflow run ID")
    workspace = backup.OFFSITE.backup.private_directory(workspace)
    aws = backup.OFFSITE.AWS(executable, "octelium-rscstore", backup.target())
    aws.check()
    encryption = aws.call("s3api", "get-bucket-encryption")
    rules = encryption["ServerSideEncryptionConfiguration"]["Rules"]
    if (len(rules) != 1 or rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] != "aws:kms"
            or rules[0].get("BucketKeyEnabled") is not True):
        raise ValueError("backup destination must have SSE-KMS and a bucket key")
    source_sha = os.environ["EXPECTED_SHA"]
    pvc_uid, pv_uid = os.environ["EXPECTED_PVC_UID"], os.environ["EXPECTED_PV_UID"]
    if (not re.fullmatch(r"[0-9a-f]{40}", source_sha)
            or not all(backup.RSC.UID.fullmatch(uid) for uid in (pvc_uid, pv_uid))):
        raise ValueError("invalid backup source or storage identity")
    payload = workspace / "workflow-receipt.json"
    receipt = {"format": 1, "stage": stage, "source_sha": source_sha,
               "workflow_run_id": run_id, "pvc_uid": pvc_uid, "pv_uid": pv_uid}
    if stage == "backup":
        proof = workspace / "proof/proof.json"
        backup.OFFSITE.private_file(proof)
        if proof.stat().st_size > 16384:
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
    retain(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
