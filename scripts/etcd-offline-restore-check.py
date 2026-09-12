#!/usr/bin/env python3
"""Validate a saved etcd snapshot by restoring a private copy without a server."""

import argparse
import hashlib
import importlib.util
import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


VERSION = "3.6.5"
# Official v3.6.5 SHA256SUMS, also checked against release asset digests.
ARCHIVES = {
    "darwin-amd64": "ab1286184ea8f27a921730d494b7dea4f9a0d3b176e70ab48fcdf77448e1ac57",
    "darwin-arm64": "14d7743f9ed07950a8e85491646e067e394a09e049e42083e2f6473fefa717a8",
    "linux-amd64": "66bad39ed920f6fc15fd74adcb8bfd38ba9a6412f8c7852d09eb11670e88cac3",
    "linux-arm64": "7010161787077b07de29b15b76825ceacbbcedcb77fe2e6832f509be102cab6b",
}
spec = importlib.util.spec_from_file_location(
    "talos_etcd_backup", Path(__file__).with_name("talos-etcd-backup.py")
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def release_archive(archive):
    """Authenticate already downloaded bytes; never download or search PATH."""
    architecture = {"arm64": "arm64", "aarch64": "arm64",
                    "x86_64": "amd64", "AMD64": "amd64"}.get(platform.machine())
    target = f"{platform.system().lower()}-{architecture}"
    if target not in ARCHIVES:
        raise ValueError("supported operator hosts are macOS/Linux amd64 or arm64")
    if not archive.is_absolute() or not archive.is_file():
        raise ValueError("release archive must be an existing absolute file path")
    if archive.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("release archive is larger than the pinned release")
    contents = archive.read_bytes()
    digest = hashlib.sha256(contents).hexdigest()
    if digest != ARCHIVES[target]:
        raise ValueError("release archive does not match the pinned platform SHA-256")
    stem = f"etcd-v{VERSION}-{target}"
    member = f"{stem}/etcdutl"
    if target.startswith("darwin-"):
        with zipfile.ZipFile(io.BytesIO(contents)) as package:
            if package.namelist().count(member) != 1:
                raise ValueError("release must contain exactly one etcdutl binary")
            binary = package.read(member)
        filename = stem + ".zip"
    else:
        with tarfile.open(fileobj=io.BytesIO(contents), mode="r:gz") as package:
            members = [item for item in package.getmembers() if item.name == member]
            if len(members) != 1 or not members[0].isfile():
                raise ValueError("release must contain exactly one regular etcdutl binary")
            binary = package.extractfile(members[0]).read()
        filename = stem + ".tar.gz"
    return binary, {
        "version": VERSION, "platform": target, "archive": filename,
        "archive_sha256": digest,
        "binary_sha256": hashlib.sha256(binary).hexdigest(),
        "source": f"https://github.com/etcd-io/etcd/releases/download/v{VERSION}/{filename}",
    }


def run_tool(tool, arguments, cwd):
    # Client diagnostics can include database keys when parsing corrupt data.
    # Keep them in memory; never print or persist arbitrary stdout/stderr.
    return subprocess.run(
        [str(tool), *arguments], cwd=cwd, env={}, capture_output=True,
        text=True, timeout=300, check=True,
    ).stdout


def snapshot_status(tool, snapshot, cwd):
    value = json.loads(run_tool(tool, ["snapshot", "status", str(snapshot),
                                      "--write-out=json"], cwd))
    if not isinstance(value, dict):
        raise ValueError("unexpected snapshot status format")
    for key in ("hash", "revision", "totalKey", "totalSize"):
        if type(value.get(key)) is not int:
            raise ValueError("snapshot status must contain integer metadata")
    if not 0 <= value["hash"] <= 0xffffffff:
        raise ValueError("invalid snapshot database hash")
    if min(value[key] for key in ("revision", "totalKey", "totalSize")) <= 0:
        raise ValueError("snapshot status reports empty database metadata")
    return {"hash": f"{value['hash']:08x}", "revision": value["revision"],
            "total_keys": value["totalKey"], "total_size": value["totalSize"]}


def restore_check(directory, destination, archive):
    """Restore only a verified working copy into a new invocation-owned tree."""
    directory = backup.private_directory(directory)
    record = backup.verify(directory)
    destination = backup.private_directory(destination)
    if directory == destination or directory in destination.parents:
        raise ValueError("restore destination must be outside the source backup")
    binary, provenance = release_archive(archive)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pending = Path(tempfile.mkdtemp(prefix=f".partial-restore-{timestamp}-", dir=destination))
    completed = pending.with_name(pending.name.removeprefix(".partial-"))
    previous_umask = os.umask(0o077)
    try:
        tool = pending / "etcdutl"
        tool.write_bytes(binary)
        tool.chmod(0o700)
        if run_tool(tool, ["version"], pending).splitlines() != [
                f"etcdutl version: {VERSION}", "API version: 3.6"]:
            raise ValueError("etcdutl version does not match the pinned release")
        snapshot = pending / "snapshot.db"
        shutil.copyfile(directory / backup.SNAPSHOT, snapshot)
        snapshot.chmod(0o600)
        if backup.snapshot_digest(snapshot) != record["integrity"]:
            raise ValueError("working snapshot no longer matches the verified backup")
        before = snapshot_status(tool, snapshot, pending)
        if before != record["metadata"]:
            raise ValueError("parsed snapshot metadata differs from the backup manifest")
        data = pending / "restored"
        # This command writes files only. No server is extracted or started.
        # Keep checksum validation enabled; never use --skip-hash-check.
        run_tool(tool, ["snapshot", "restore", str(snapshot), "--data-dir", str(data),
                        "--name", "offline-validation", "--initial-cluster",
                        "offline-validation=http://127.0.0.1:2380",
                        "--initial-advertise-peer-urls", "http://127.0.0.1:2380",
                        "--initial-cluster-token", "offline-validation"], pending)
        restored = data / "member" / "snap" / "db"
        after = snapshot_status(tool, restored, pending)
        if any(after[key] != before[key] for key in ("revision", "total_keys")):
            raise ValueError("restored revision or key count differs from the snapshot")
        # Restoration rewrites membership metadata, so database hash/size may differ.
        if backup.verify(directory) != record:
            raise ValueError("source backup changed during restore validation")
        if backup.snapshot_digest(snapshot) != record["integrity"]:
            raise ValueError("working snapshot changed during restore validation")
        for path in pending.rglob("*"):
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                path.chmod(0o700)
            elif stat.S_ISREG(mode):
                path.chmod(0o700 if path == tool else 0o600)
            else:
                raise ValueError("unexpected file type in offline restore output")
        receipt = {
            "format": 1, "completed_at": datetime.now(timezone.utc).isoformat(),
            "validation": "offline-database-restore", "control_plane_recovery_tested": False,
            "tool": provenance, "source_integrity": record["integrity"],
            "snapshot_status": before, "restored_status": after,
            "source_unchanged": True, "restore_checksum_enabled": True,
            "server_started": False,
        }
        with (pending / "receipt.json").open("x") as output:
            json.dump(receipt, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        backup.sync_directory(pending)
        pending.rename(completed)
        backup.sync_directory(destination)
        return completed, receipt
    finally:
        os.umask(previous_umask)
        if pending.exists():
            shutil.rmtree(pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-directory", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path,
                        help="existing mode-0700 directory outside Git and the source backup")
    parser.add_argument("--etcd-archive", required=True, type=Path,
                        help="local official etcd3.6.5 archive for this host; no download")
    args = parser.parse_args()
    try:
        directory, receipt = restore_check(args.backup_directory, args.destination,
                                           args.etcd_archive)
        print(f"Offline restore validated: {directory}")
        print(f"Revision {receipt['restored_status']['revision']}; "
              f"keys {receipt['restored_status']['total_keys']}. "
              "Control-plane startup and application recovery were not tested.")
        return 0
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError,
            tarfile.TarError, zipfile.BadZipFile):
        print("Offline restore validation failed; retain the original backup. "
              "Check archive version/checksum, private paths, space, and snapshot integrity. "
              "Raw database diagnostics are withheld.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
