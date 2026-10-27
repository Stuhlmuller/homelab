#!/usr/bin/env python3
"""Bind a staged Enterprise recovery set to proposed publication/restore receipts.

This is an offline, source-only consistency check. It cannot authenticate S3,
GitHub run provenance, or an isolated restore. It never promotes a marker or
returns a publishable backup receipt.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat


ROOT = Path(__file__).resolve().parents[2]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


COORDINATOR = module("oce_recovery_chain_coordinator",
                     "scripts/ci/openclaw-enterprise-backup-coordinator.py")
OCE = COORDINATOR.OCE
OFFSITE = module("oce_recovery_chain_offsite", "scripts/etcd-offsite-backup.py")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
RESOURCE_VERSION = re.compile(r"[1-9][0-9]*\Z")
MAX_FILES = 100_000
MAX_BYTES = 34 * 1024 ** 3
MAX_CIPHERTEXT_BYTES = 36 * 1024 ** 3
REQUIRED_FILES = {
    "recovery.json", "journal/journal.json", "bootstrap/output.json",
    "bootstrap/initial-admin-password", "bootstrap/initial-admin-service-key.json",
    "agent/identity.json", "tenant/metadata.json",
    "postgres-root/tls.crt", "postgres-root/tls.key", "postgres-admin/password",
    "postgres-migrator/password", "postgres-app/password", "postgres-backup/password",
    "auth/secret", "gateway/occ", "gateway-ca/tls.crt", "gateway-ca/tls.key",
}


class Blocked(RuntimeError):
    pass


def require(condition):
    if not condition:
        raise Blocked("Enterprise recovery chain is incomplete or changed")


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_nlink)


def _private_file_digest(path, maximum, *, allow_empty=False, return_bytes=False):
    """Hash one stable owned regular file, rejecting link and inode swaps."""
    path = Path(path)
    try:
        parent = path.parent.lstat()
        require(path.is_absolute() and path.parent.resolve() == path.parent and
                stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid() and
                stat.S_IMODE(parent.st_mode) == 0o700)
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and
                stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1 and
                (allow_empty or before.st_size > 0) and before.st_size <= maximum)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW |
                             os.O_CLOEXEC | os.O_NONBLOCK)
        digest = hashlib.sha256()
        count = 0
        chunks = [] if return_bytes else None
        with os.fdopen(descriptor, "rb") as stream:
            require(_identity(os.fstat(stream.fileno())) == _identity(before))
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                count += len(chunk)
                require(count <= maximum)
                digest.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
            require(_identity(os.fstat(stream.fileno())) == _identity(before))
        require(count == before.st_size and _identity(path.lstat()) == _identity(before))
    except OSError:
        raise Blocked("Enterprise recovery file is unavailable") from None
    record = {"bytes": count, "sha256": digest.hexdigest()}
    return (record, b"".join(chunks)) if chunks is not None else record


def _private_json(path):
    try:
        _, raw = _private_file_digest(path, 8 * 1024 * 1024, return_bytes=True)
        value = json.loads(raw)
        require(isinstance(value, dict) and
                raw == json.dumps(value, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False).encode())
        return value
    except (OSError, UnicodeError, ValueError):
        raise Blocked("Enterprise recovery JSON is unavailable") from None


def _safe_relative_path(relative):
    parts = Path(relative).parts
    require(0 < len(relative.encode()) <= 4096 and 0 < len(parts) <= 64 and
            all(0 < len(part.encode()) <= 255 and part not in (".", "..") and
                all(character != "\\" and ord(character) >= 32 and
                    ord(character) != 127 for character in part)
                for part in parts))


def _private_tree(root):
    root = Path(root)
    try:
        metadata = root.lstat()
        require(root.is_absolute() and root.resolve() == root and
                stat.S_ISDIR(metadata.st_mode) and
                metadata.st_uid == os.getuid() and
                stat.S_IMODE(metadata.st_mode) == 0o700)
        records = []
        file_paths = set()
        total = 0
        for directory, subdirectories, filenames in os.walk(root, followlinks=False):
            current = Path(directory)
            before = current.lstat()
            require(stat.S_ISDIR(before.st_mode) and
                    before.st_uid == os.getuid() and
                    stat.S_IMODE(before.st_mode) == 0o700)
            relative = current.relative_to(root).as_posix()
            if relative != ".":
                _safe_relative_path(relative)
                records.append(("directory", relative))
            for name in sorted(filenames):
                path = current / name
                relative = path.relative_to(root).as_posix()
                _safe_relative_path(relative)
                value = _private_file_digest(path, MAX_BYTES - total,
                                             allow_empty=True)
                total += value["bytes"]
                records.append(("file", relative, value["bytes"], value["sha256"]))
                file_paths.add(relative)
                require(len(records) <= MAX_FILES)
            for name in subdirectories:
                child = current / name
                child_metadata = child.lstat()
                require(stat.S_ISDIR(child_metadata.st_mode) and
                        child_metadata.st_uid == os.getuid() and
                        stat.S_IMODE(child_metadata.st_mode) == 0o700)
            require(_identity(current.lstat()) == _identity(before))
        require(REQUIRED_FILES <= file_paths and
                any(name.startswith("tenant/secrets/") for name in file_paths) and
                any(name.startswith("agent/state/") for name in file_paths) and
                len(records) <= MAX_FILES and total <= MAX_BYTES)
        payload = json.dumps(sorted(records), sort_keys=True,
                             separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()
    except (OSError, UnicodeError, ValueError):
        raise Blocked("Enterprise recovery material is unavailable") from None


def inspect_material(root, config, source_sha, backup_id, watch_receipt):
    """Bind every staged file byte and the namespace/Agent to a watch receipt."""
    require(isinstance(source_sha, str) and SHA.fullmatch(source_sha) and
            isinstance(backup_id, str) and HEX64.fullmatch(backup_id))
    OCE._validate_config(config)
    root = Path(root)
    marker, marker_sha256 = COORDINATOR._private_marker(root / "recovery.json")
    material_sha256 = _private_tree(root)
    agent = _private_json(root / "agent/identity.json")
    tenant = _private_json(root / "tenant/metadata.json")
    try:
        state, _ = OCE.read_journal(root / "journal/journal.json",
                                    config["source"]["revision"],
                                    OCE._identity_hash(config))
    except OCE.Blocked:
        raise Blocked("Enterprise recovery journal is unavailable") from None
    require(marker.get("schemaVersion") == 2 and
            marker.get("sourceSha") == source_sha and
            marker.get("enterpriseSourceSha") == config["source"]["revision"] and
            marker.get("writerStopped") is True and
            marker.get("continuousFenceVerified") is False and
            marker.get("claimUid") == marker.get("agentStateClaimUid") and
            all(marker.get(key) == state.get(key) == agent.get(key)
                for key in ("installationId", "namespaceId", "agentId", "revisionId")) and
            agent.get("gatewayClaimUid") == marker.get("claimUid") and
            tenant.get("namespaceId") == marker.get("namespaceId") and
            tenant.get("agentId") == marker.get("agentId") and
            isinstance(tenant.get("gatewayClaim"), dict) and
            tenant["gatewayClaim"].get("metadata", {}).get("uid") ==
            marker.get("claimUid") and
            isinstance(watch_receipt, dict) and
            watch_receipt.get("scope") == "tenant-pod-watch" and
            watch_receipt.get("publishable") is False and
            watch_receipt.get("sourceSha") == source_sha and
            watch_receipt.get("backupId") == backup_id and
            watch_receipt.get("tenantReaderPodUid") ==
            marker.get("tenantReaderPodUid") and
            watch_receipt.get("observationSha256") ==
            marker.get("observationSha256") and
            watch_receipt.get("markerSha256") == marker_sha256 and
            isinstance(watch_receipt.get("startResourceVersion"), str) and
            RESOURCE_VERSION.fullmatch(watch_receipt["startResourceVersion"]) and
            isinstance(watch_receipt.get("endResourceVersion"), str) and
            RESOURCE_VERSION.fullmatch(watch_receipt["endResourceVersion"]) and
            int(watch_receipt["endResourceVersion"]) >
            int(watch_receipt["startResourceVersion"]))
    require(_private_tree(root) == material_sha256)
    return {"scope": "source-only-material", "publishable": False,
            "sourceSha": source_sha, "backupId": backup_id,
            "materialSha256": material_sha256, "markerSha256": marker_sha256,
            "installationId": state["installationId"],
            "namespaceId": state["namespaceId"], "agentId": state["agentId"],
            "revisionId": state["revisionId"]}


def bind_external_references(material, material_root, ciphertext, publication,
                             restore, capture_watch, final_watch, config):
    """Check exact references; external S3/run/restore truth remains unproved."""
    require(isinstance(material, dict) and
            material.get("scope") == "source-only-material" and
            material.get("publishable") is False and
            isinstance(material.get("sourceSha"), str) and
            SHA.fullmatch(material["sourceSha"]) and
            isinstance(material.get("backupId"), str) and
            HEX64.fullmatch(material["backupId"]) and
            isinstance(material.get("materialSha256"), str) and
            HEX64.fullmatch(material["materialSha256"]))
    require(inspect_material(material_root, config, material["sourceSha"],
                             material["backupId"], capture_watch) == material)
    ciphertext_digest = _private_file_digest(ciphertext, MAX_CIPHERTEXT_BYTES)
    destination = OFFSITE.read_inputs(ROOT / "IaC/application-backup-storage.hcl")
    require(set(destination) == {"account_id", "region", "bucket"} and
            re.fullmatch(r"[0-9]{12}", destination["account_id"]) and
            destination["region"] == "us-east-1" and
            destination["bucket"] ==
            f"homelab-application-backups-{destination['account_id']}-us-east-1")
    key = "openclaw-enterprise/new/" + material["backupId"] + ".tar.age"
    expected = {"sourceSha": material["sourceSha"],
                "backupId": material["backupId"],
                "materialSha256": material["materialSha256"],
                "bucket": destination["bucket"], "key": key,
                "ciphertext": ciphertext_digest}
    for field, prefix in (("installationId", "ins_"),
                          ("namespaceId", "ns_"), ("agentId", "agt_"),
                          ("revisionId", "rev_")):
        require(OCE._valid_resource_id(material.get(field), prefix))
        expected[field] = material[field]
    require(isinstance(publication, dict) and isinstance(restore, dict) and
            isinstance(final_watch, dict) and
            all(publication.get(field) == value and restore.get(field) == value
                for field, value in expected.items()) and
            isinstance(publication.get("versionId"), str) and
            0 < len(publication["versionId"]) <= 1024 and
            all(32 <= ord(character) < 127 for character in publication["versionId"]) and
            publication["versionId"] != "null" and
            restore.get("versionId") == publication["versionId"] and
            publication.get("workflow") == "OpenClaw Enterprise Recovery Publication" and
            restore.get("workflow") == "OpenClaw Enterprise Recovery Restore" and
            type(publication.get("runId")) is int and publication["runId"] > 0 and
            type(restore.get("runId")) is int and restore["runId"] > 0 and
            restore["runId"] != publication["runId"] and
            publication.get("runHeadSha") == material["sourceSha"] and
            restore.get("runHeadSha") == material["sourceSha"] and
            restore.get("isolated") is True and
            restore.get("databaseRestored") is True and
            restore.get("recoveryMaterialRestored") is True and
            final_watch.get("scope") == "tenant-pod-watch" and
            final_watch.get("publishable") is False and
            final_watch.get("sourceSha") == material["sourceSha"] and
            final_watch.get("backupId") == material["backupId"] and
            final_watch.get("markerSha256") == material["markerSha256"] and
            final_watch.get("startResourceVersion") ==
            capture_watch["startResourceVersion"] and
            isinstance(final_watch.get("endResourceVersion"), str) and
            RESOURCE_VERSION.fullmatch(final_watch["endResourceVersion"]) and
            int(final_watch["endResourceVersion"]) >
            int(capture_watch["endResourceVersion"]) and
            final_watch.get("throughPhase") == "after-independent-restore")
    require(_private_tree(material_root) == material["materialSha256"] and
            _private_file_digest(ciphertext, MAX_CIPHERTEXT_BYTES) == ciphertext_digest)
    return {"scope": "source-only-recovery-chain", "publishable": False,
            "sourceSha": material["sourceSha"], "backupId": material["backupId"],
            "materialSha256": material["materialSha256"],
            "installationId": material["installationId"],
            "namespaceId": material["namespaceId"],
            "agentId": material["agentId"],
            "revisionId": material["revisionId"],
            "ciphertextSha256": ciphertext_digest["sha256"],
            "ciphertextBytes": ciphertext_digest["bytes"],
            "bucket": destination["bucket"], "key": key,
            "versionId": publication["versionId"],
            "publisherRunId": publication["runId"],
            "restoreRunId": restore["runId"]}
