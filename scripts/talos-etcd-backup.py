#!/usr/bin/env python3
"""Save and verify a private, off-node Talos etcd snapshot without cluster mutation."""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


CONTROL_PLANE = "10.1.0.199"
SNAPSHOT = "etcd.snapshot"
MANIFEST = "manifest.json"
STATUS = re.compile(
    r"^snapshot info: hash ([0-9a-f]{8}), revision (\d+), "
    r"total keys (\d+), total size (\d+)$", re.MULTILINE
)


def private_directory(path):
    """Require an existing private destination outside any Git checkout."""
    if not path.is_absolute():
        raise ValueError("destination must be an absolute path")
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("destination must be a directory owned by the current user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("destination must have mode 0700")
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError("backups must be outside Git checkouts")
    return path


def snapshot_digest(path):
    """Check etcd's appended SHA-256 digest without reading keys or values."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("snapshot must be a regular file owned by the current user")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("snapshot must have mode 0600")
    size = info.st_size
    # Talos/etcd stream a database aligned to 512 bytes plus a 32-byte digest.
    if size <= 32 or size % 512 != 32:
        raise ValueError("snapshot is empty, truncated, or lacks its checksum trailer")
    payload_hash = hashlib.sha256()
    with path.open("rb") as source:
        remaining = size - 32
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("snapshot was truncated while verifying")
            payload_hash.update(chunk)
            remaining -= len(chunk)
        trailer = source.read(32)
        if payload_hash.digest() != trailer or source.read(1):
            raise ValueError("snapshot embedded SHA-256 checksum does not match")
    file_hash = payload_hash.copy()
    file_hash.update(trailer)
    return {"bytes": size, "sha256": file_hash.hexdigest(),
            "embedded_sha256": payload_hash.hexdigest()}


def verify(directory):
    directory = private_directory(directory)
    manifest = directory / MANIFEST
    info = manifest.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError("manifest must be a private regular file with mode 0600")
    record = json.loads(manifest.read_text())
    if record.get("format") != 1 or record.get("snapshot") != SNAPSHOT:
        raise ValueError("unsupported backup manifest")
    if record.get("integrity") != snapshot_digest(directory / SNAPSHOT):
        raise ValueError("snapshot no longer matches its backup manifest")
    return record


def sync_directory(path):
    """Persist directory entries on the supported Linux/macOS operator hosts."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup(destination, talosconfig, talosctl="talosctl"):
    destination = private_directory(destination)
    talosconfig = talosconfig.resolve(strict=True)
    if not talosconfig.is_file():
        raise ValueError("talosconfig must be an existing file")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pending = Path(tempfile.mkdtemp(prefix=f".partial-etcd-{timestamp}-", dir=destination))
    completed = pending.with_name(pending.name.removeprefix(".partial-"))
    try:
        # Explicit config, endpoint and single node prevent ambient CLI defaults
        # from choosing another cluster. Only the snapshot RPC is requested.
        result = subprocess.run(
            [talosctl, "--talosconfig", str(talosconfig),
             "--endpoints", CONTROL_PLANE, "--nodes", CONTROL_PLANE,
             "etcd", "snapshot", str(pending / SNAPSHOT)],
            capture_output=True, text=True, timeout=300, check=True,
        )
        matches = STATUS.findall(result.stdout)
        if len(matches) != 1:
            raise ValueError("talosctl did not report exactly one snapshot metadata record")
        db_hash, revision, keys, db_size = matches[0]
        if min(int(revision), int(keys), int(db_size)) <= 0:
            raise ValueError("talosctl reported empty snapshot metadata")
        record = {
            "format": 1, "snapshot": SNAPSHOT,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_node": CONTROL_PLANE,
            "metadata": {"hash": db_hash, "revision": int(revision),
                         "total_keys": int(keys), "total_size": int(db_size)},
            "integrity": snapshot_digest(pending / SNAPSHOT),
        }
        fd = os.open(pending / MANIFEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(record, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        verify(pending)
        # Talos fsyncs the snapshot itself; persist the manifest and snapshot
        # directory entries before publishing, then persist the final name.
        sync_directory(pending)
        pending.rename(completed)
        sync_directory(destination)
        return completed, record
    finally:
        # Only this invocation's unpublished directory is removed. Never prune
        # existing backups; interrupted runs may leave a hidden .partial-* dir.
        if pending.exists():
            shutil.rmtree(pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("backup", help="download a new authenticated snapshot")
    save.add_argument("--destination", type=Path, required=True,
                      help="existing mode-0700 directory outside all Git checkouts")
    save.add_argument("--talosconfig", type=Path, required=True,
                      help="explicit path to the current private Talos client config")
    save.add_argument("--talosctl", default="talosctl",
                      help="Talos client executable; use an explicit version-matched path")
    check = commands.add_parser("verify", help="recheck a completed backup offline")
    check.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            directory, record = backup(args.destination, args.talosconfig, args.talosctl)
        else:
            directory = args.directory
            record = verify(directory)
        print(f"Verified backup: {directory}")
        print(f"Revision {record['metadata']['revision']}; "
              f"keys {record['metadata']['total_keys']}; "
              f"bytes {record['integrity']['bytes']}; "
              f"SHA-256 {record['integrity']['sha256']}")
        return 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Do not forward arbitrary client errors or authenticated configuration.
        print("Backup failed: talosctl snapshot failed or timed out; check "
              "authenticated Talos connectivity and etcd health.", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Backup verification failed: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
