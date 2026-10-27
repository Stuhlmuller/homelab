#!/usr/bin/env python3
"""Prepare and check an owner's signed direct-LAN Talos probe assertion.

This verifies an explicit human assertion about a private candidate. It does
not prove the network route cryptographically or publish a platform receipt.
"""

import argparse
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_KEY = ROOT / "scripts/config/platform-direct-recovery-owner.asc"
OWNER_FINGERPRINT = "2E0AE9393F24306F26A9AEB5A86F8F76C83C03EC"
PURPOSE = "openclaw-enterprise-direct-talos-recovery-v1"
STATEMENT = (
    "I reviewed the private candidate from the current-main local Talos probe, "
    "confirmed the host's direct LAN route for the authenticated requests to "
    "all four named nodes, and authorize this exact candidate for separate "
    "protected prerequisite review. I understand the socket check alone is "
    "not cryptographic proof of the network route."
)
EXPECTED_FIELDS = {
    "sourceSha", "verified", "candidateVerified", "capturedAt", "publicationId",
    "transport", "endpoint", "nodes", "talosMtls", "clientRole",
    "clientCertNotAfter", "serverVersions", "lanSourceAddress",
}
TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")
PUBLICATION_ID = re.compile(r"[0-9a-f]{32}\Z")


def load_candidate_module():
    spec = importlib.util.spec_from_file_location(
        "platform_direct_recovery_prerequisite",
        ROOT / "scripts/platform-direct-recovery-prerequisite.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


candidate_module = load_candidate_module()
platform = candidate_module.platform


def reviewed_source(source_sha):
    candidate_module.reviewed_context(source_sha)
    for relative in (
        "scripts/platform-direct-recovery-attestation.py",
        "scripts/config/platform-direct-recovery-owner.asc",
    ):
        path = ROOT / relative
        committed = subprocess.run(
            ["git", "--no-replace-objects", "show", f"{source_sha}:{relative}"],
            cwd=ROOT, capture_output=True, timeout=15, check=True)
        if committed.stdout != path.read_bytes():
            raise ValueError("owner attestation verifier differs from reviewed source")


def private_file(path, limit=1048576):
    if path is None or not path.is_absolute():
        raise ValueError("owner attestation input requires an absolute private path")
    directory = platform.private_directory(path.parent)
    directory_fd = os.open(
        directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
        getattr(os, "O_NOFOLLOW", 0))
    try:
        directory_info = os.fstat(directory_fd)
        if (not stat.S_ISDIR(directory_info.st_mode) or
                directory_info.st_uid != os.getuid() or
                stat.S_IMODE(directory_info.st_mode) != 0o700):
            raise ValueError("owner attestation directory changed")
        descriptor = os.open(
            path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or
                    not 0 < info.st_size <= limit):
                raise ValueError("owner attestation input is not a private regular file")
            chunks = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if len(content) != info.st_size:
                raise ValueError("owner attestation input changed during read")
            return content
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_fd)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def parse_time(value):
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise ValueError("direct-recovery time is invalid")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def checked_candidate(source_sha, path):
    raw = private_file(path)
    try:
        record = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("direct-recovery candidate is invalid") from None
    if not isinstance(record, dict) or set(record) != EXPECTED_FIELDS or raw != canonical(record):
        raise ValueError("direct-recovery candidate must be exact canonical JSON")
    if (record["sourceSha"] != source_sha or record["verified"] is not False or
            record["candidateVerified"] is not True or
            record["transport"] != "direct-lan-authenticated-talos" or
            record["endpoint"] != "10.1.0.199:50000" or
            record["nodes"] != list(platform.NODES) or
            record["talosMtls"] is not True or record["clientRole"] != "os:admin" or
            not isinstance(record["publicationId"], str) or
            not PUBLICATION_ID.fullmatch(record["publicationId"])):
        raise ValueError("direct-recovery candidate differs from reviewed probe")
    captured = parse_time(record["capturedAt"])
    platform.fresh_recovery_time(record["capturedAt"])
    expires = parse_time(record["clientCertNotAfter"])
    if (expires < captured + timedelta(hours=24) or
            expires < datetime.now(timezone.utc) + timedelta(hours=3)):
        raise ValueError("direct-recovery Talos client expires too soon")
    versions = record["serverVersions"]
    if (not isinstance(versions, dict) or set(versions) != set(platform.NODES) or
            any(not isinstance(tag, str) or
                not candidate_module.VERSION_TAG.fullmatch(tag)
                for tag in versions.values())):
        raise ValueError("direct-recovery node version evidence is incomplete")
    if not isinstance(record["lanSourceAddress"], str):
        raise ValueError("direct-recovery LAN source address is invalid")
    try:
        source = ipaddress.IPv4Address(record["lanSourceAddress"])
    except (ipaddress.AddressValueError, TypeError):
        raise ValueError("direct-recovery LAN source address is invalid") from None
    if (source not in ipaddress.IPv4Network("10.1.0.0/24") or
            str(source) in platform.ADDRESSES):
        raise ValueError("direct-recovery LAN source address is invalid")
    return record, raw


def attestation_for(record, candidate_bytes):
    return {
        "schemaVersion": 1,
        "purpose": PURPOSE,
        "statement": STATEMENT,
        "sourceSha": record["sourceSha"],
        "publicationId": record["publicationId"],
        "capturedAt": record["capturedAt"],
        "candidateSha256": hashlib.sha256(candidate_bytes).hexdigest(),
    }


def prepare(source_sha, candidate_path, attestation_path):
    reviewed_source(source_sha)
    record, raw = checked_candidate(source_sha, candidate_path)
    if not attestation_path.is_absolute():
        raise ValueError("owner attestation output requires an absolute path")
    directory = platform.private_directory(attestation_path.parent)
    candidate_module.write_private_json(
        directory / attestation_path.name, attestation_for(record, raw))
    return directory / attestation_path.name


def verified_owner_signature(attestation_bytes, signature_bytes):
    if not re.fullmatch(r"[0-9A-F]{40}", OWNER_FINGERPRINT):
        raise ValueError("invalid pinned owner fingerprint")
    certificate = PUBLIC_KEY.read_bytes()
    if not 0 < len(certificate) <= 65536:
        raise ValueError("invalid committed owner certificate")
    with tempfile.TemporaryDirectory(prefix="oce-direct-owner-") as home:
        os.chmod(home, 0o700)
        def isolated_file(name, content):
            path = Path(home) / name
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            return path

        # GPG receives only the bytes already checked by verify(), never the
        # mutable caller paths that supplied them.
        checked_attestation = isolated_file("attestation.json", attestation_bytes)
        checked_signature = isolated_file("attestation.sig", signature_bytes)

        def gpg(*args, data=None):
            return subprocess.run(
                ["gpg", "--homedir", home, "--batch", "--no-tty",
                 "--no-auto-key-retrieve", *args], input=data,
                capture_output=True, timeout=30, check=False)

        if gpg("--import", data=certificate).returncode != 0:
            raise ValueError("committed owner certificate is unusable")
        keys = gpg("--with-colons", "--fingerprint", "--fingerprint", "--list-keys")
        lines = keys.stdout.decode(errors="replace").splitlines()
        primaries = [line for line in lines if line.startswith("pub:")]
        fingerprints = [line.split(":")[9] for line in lines if line.startswith("fpr:")]
        if (keys.returncode != 0 or len(primaries) != 1 or not fingerprints or
                fingerprints[0] != OWNER_FINGERPRINT):
            raise ValueError("committed owner certificate fingerprint differs")
        result = gpg("--status-fd", "1", "--verify", str(checked_signature),
                     str(checked_attestation))
        valid = [line.split() for line in result.stdout.decode(errors="replace").splitlines()
                 if line.startswith("[GNUPG:] VALIDSIG ")]
        if (result.returncode != 0 or len(valid) != 1 or len(valid[0]) < 3 or
                valid[0][2] != OWNER_FINGERPRINT):
            raise ValueError("owner attestation signature is untrusted")


def verify(source_sha, candidate_path, attestation_path, signature_path):
    reviewed_source(source_sha)
    record, raw = checked_candidate(source_sha, candidate_path)
    attestation = private_file(attestation_path)
    if attestation != canonical(attestation_for(record, raw)):
        raise ValueError("owner attestation differs from exact candidate")
    signature = private_file(signature_path, limit=65536)
    verified_owner_signature(attestation, signature)
    # A future protected publisher must re-run these checks. This verifier never
    # changes candidate.verified or creates a maintenance prerequisite.
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--attestation", required=True, type=Path)
    parser.add_argument("--signature", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "prepare" and args.signature is None:
            prepare(args.expected_sha, args.candidate, args.attestation)
            print("Private owner attestation prepared for review and detached signing.")
        elif args.action == "verify" and args.signature is not None:
            verify(args.expected_sha, args.candidate, args.attestation, args.signature)
            print("Owner attestation verified; no platform receipt published.")
        else:
            raise ValueError("signature is required only for verification")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("Owner attestation blocked; no platform receipt published. Private details withheld.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
