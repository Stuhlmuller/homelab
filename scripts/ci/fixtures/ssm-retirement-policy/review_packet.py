"""Unwired verification of the #805 owner approval and exact plan bytes."""

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


UNIT = "IaC/homelab/us-west-2/shared/aws-ssm-parameters"
PACKET_CONTEXT = {
    "version": 1,
    "decision": "approve-ssm-retirement-805",
    "repository": "Stuhlmuller/homelab",
    "unit": UNIT,
    "backend": "s3://rstuhlmuller-aws-s3-use1-datalake/IaC/homelab/live/aws-ssm-parameters/terraform.tfstate",
    "account": "716182248480",
    "region": "us-west-2",
    "delete_names": [
        "/homelab/argocd-image-updater/github-app/id",
        "/homelab/argocd-image-updater/github-app/installation-id",
        "/homelab/argocd-image-updater/github-app/private-key",
        "/homelab/github-actions-runner/registration-token",
    ],
}
MAX_AGE_SECONDS = 3600
REJECTED_SIGNATURE_STATUS = {
    "BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "NO_PUBKEY",
    "KEYEXPIRED", "SIGEXPIRED", "KEYREVOKED", "NODATA", "FAILURE", "ERROR",
}


def canonical_packet(revision, plan_sha256, created_at):
    if (not re.fullmatch(r"[0-9a-f]{40}", revision)
            or not re.fullmatch(r"[0-9a-f]{64}", plan_sha256)
            or type(created_at) is not int or created_at <= 0):
        raise ValueError("Invalid retirement review packet identity")
    return (json.dumps({
        **PACKET_CONTEXT,
        "revision": revision,
        "plan_sha256": plan_sha256,
        "created_at": created_at,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode()


@contextlib.contextmanager
def open_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as artifact:
        info = os.fstat(artifact.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                or not info.st_size):
            raise ValueError("Retirement artifacts must be private regular files")
        yield artifact


def read_private(path, limit):
    with open_private(path) as artifact:
        data = artifact.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("Retirement approval artifact exceeds its size limit")
    return data


def verify_signature(status, owner_primary, owner_signer, created_at, now):
    if not all(re.fullmatch(r"[A-F0-9]{40}", fingerprint) for fingerprint in (owner_primary, owner_signer)):
        raise ValueError("The approved owner primary and signing fingerprints are required")
    fields = [line.removeprefix("[GNUPG:] ").split() for line in status.splitlines()
              if line.startswith("[GNUPG:] ")]
    valid = [row for row in fields if len(row) > 0 and row[0] == "VALIDSIG"]
    if (len(valid) != 1 or any(row and row[0] in REJECTED_SIGNATURE_STATUS for row in fields)
            or sum(bool(row and row[0] == "NEWSIG") for row in fields) != 1):
        raise ValueError("Exact owner OpenPGP signature required")
    row = valid[0]
    # GnuPG VALIDSIG lists the signing fingerprint first and optional primary
    # fingerprint last. Accept binary document signatures with SHA-2 only.
    if (len(row) not in (10, 11) or row[1] != owner_signer
            or (row[10] if len(row) == 11 else row[1]) != owner_primary
            or row[8] not in {"8", "9", "10"} or row[9] != "00"
            or not row[3].isdigit() or not created_at <= int(row[3]) <= now
            or not row[4].isdigit() or (int(row[4]) and int(row[4]) <= now)):
        raise ValueError("Owner signing identity, signature format, or timestamp is invalid")


@contextlib.contextmanager
def verified_plan(plan, packet, signature, *, current_main, owner_keyring,
                  owner_primary, owner_signer, now):
    """Yield a private exact copy for plan-shape checking and future replay.

    The protected caller must independently establish current_main and enroll
    owner_keyring/owner fingerprints. This fixture does not choose either.
    """
    packet_bytes = read_private(packet, 8192)
    data = json.loads(packet_bytes)
    if not isinstance(data, dict) or set(data) != set(PACKET_CONTEXT) | {"revision", "plan_sha256", "created_at"}:
        raise ValueError("Unexpected retirement review packet fields")
    if (packet_bytes != canonical_packet(data["revision"], data["plan_sha256"], data["created_at"])
            or data["revision"] != current_main
            or not 0 <= now - data["created_at"] <= MAX_AGE_SECONDS):
        raise ValueError("Retirement packet is invalid, stale, or not for current main")

    with tempfile.TemporaryDirectory(prefix="ssm-retirement-verified-") as temporary:
        private = Path(temporary)
        signature_copy = private / "approval.sig"
        signature_copy.write_bytes(read_private(signature, 16384))
        result = subprocess.run(
            ["gpgv", "--homedir", str(private), "--keyring", str(owner_keyring.resolve(strict=True)),
             "--status-fd", "1", "--", str(signature_copy), "-"],
            input=packet_bytes, capture_output=True, check=True, timeout=30,
        )
        verify_signature(result.stdout.decode(), owner_primary, owner_signer, data["created_at"], now)

        digest = hashlib.sha256()
        plan_copy = private / "retirement.tfplan"
        fd = os.open(plan_copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as target, open_private(plan) as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
                target.write(block)
        if digest.hexdigest() != data["plan_sha256"]:
            raise ValueError("Saved plan bytes differ from the signed review packet")
        yield plan_copy
