#!/usr/bin/env python3
"""Capture a private online Multica database backup with stable upload contents.

This reads the existing Pods; it does not fence writers or change cluster state.
The two matching upload inventories detect concurrent file changes but are not
an atomic database/filesystem snapshot or an isolated restore drill.
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

NAMESPACE = "ai"
API_SERVER = "https://10.1.0.199:6443"
ARTIFACTS = ("multica.dump", "uploads.tar")
METADATA_TIMEOUT_SECONDS = 30
ARCHIVE_TIMEOUT_SECONDS = 3600
STATE_QUERY = """
SELECT json_build_object(
  'active_tasks', (SELECT count(*) FROM agent_task_queue
    WHERE status IN ('dispatched', 'running', 'waiting_local_directory')),
  'migration_count', (SELECT count(*) FROM schema_migrations),
  'migration_hash', (SELECT md5(coalesce(string_agg(version::text, E'\\n'
    ORDER BY version), '')) FROM schema_migrations),
  'attachment_count', (SELECT count(*) FROM attachment),
  'attachment_hash', (SELECT md5(coalesce(string_agg(row_to_json(a)::text,
    E'\\n' ORDER BY id), '')) FROM attachment a)
);
"""


def private_directory(path):
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("destination must be an absolute, non-symlink directory")
    path = path.resolve(strict=True)
    info = path.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("destination must be owned by the current user with mode 0700")
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError("backup destination must be outside Git checkouts")
    return path


def private_file(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError("backup files must be owned regular files with mode 0600")
    return info


def integrity(path):
    info = private_file(path)
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {"bytes": info.st_size, "sha256": digest}


def upload_inventory(path):
    """Hash archive files without extracting or trusting archive paths."""
    inventory = {}
    seen = set()
    with tarfile.open(path, mode="r:") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or str(name) in seen:
                raise ValueError("unsafe or duplicate upload archive entry")
            seen.add(str(name))
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("upload archive contains a non-regular file")
            with archive.extractfile(member) as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            inventory[str(name)] = {"bytes": member.size, "sha256": digest}
    return inventory


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Cluster:
    def __init__(self, kubectl, context):
        self.base = [kubectl, "--context", context, "--namespace", NAMESPACE]

    def run(self, args, *, timeout=METADATA_TIMEOUT_SECONDS, **kwargs):
        # Never forward arbitrary authenticated client output or database errors.
        return subprocess.run(self.base + [f"--request-timeout={timeout}s"] + args,
                              stderr=subprocess.DEVNULL, timeout=timeout, check=True, **kwargs)

    def json(self, args):
        return json.loads(self.run(args, stdout=subprocess.PIPE).stdout)

    def sources(self):
        result = {}
        for component in ("postgres", "backend", "runtime"):
            selector = ("app.kubernetes.io/name=multica-runtime" if component == "runtime"
                        else "app.kubernetes.io/name=multica,"
                             f"app.kubernetes.io/component={component}")
            pods = self.json(["get", "pods", "-l",
                              selector, "-o", "json"])
            pods = [pod for pod in pods["items"]
                    if pod.get("status", {}).get("phase") not in ("Succeeded", "Failed")]
            if len(pods) != 1:
                raise ValueError("require exactly one Pod per Multica component")
            pod = pods[0]
            statuses = pod.get("status", {}).get("containerStatuses", [])
            if (pod["metadata"].get("deletionTimestamp")
                    or pod.get("status", {}).get("phase") != "Running"
                    or not statuses or not all(item.get("ready") for item in statuses)):
                raise ValueError("all Multica source Pods must be running and ready")
            result[component] = {
                "name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"],
                "containers": [{key: item.get(key) for key in
                                ("name", "image", "imageID", "containerID", "restartCount")}
                               for item in statuses],
            }
        return result

    def execute(self, pod, container, args, **kwargs):
        return self.run(["exec", "-i", pod, "-c", container, "--", *args], **kwargs)

    def state(self, postgres):
        result = self.execute(postgres, "postgres",
                              ["psql", "-X", "-U", "multica", "-d", "multica",
                               "-Atqc", STATE_QUERY], stdout=subprocess.PIPE)
        record = json.loads(result.stdout)
        if record["active_tasks"] != 0:
            raise ValueError("Multica tasks are claimed or executing; wait for them to finish")
        return record


def capture(cluster, path, pod, container, command):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        cluster.execute(pod, container, command, stdout=output, timeout=ARCHIVE_TIMEOUT_SECONDS)
        output.flush()
        os.fsync(output.fileno())


def verify(directory):
    directory = private_directory(directory)
    private_file(directory / "manifest.json")
    record = json.loads((directory / "manifest.json").read_text())
    if (record.get("format") != 1
            or record.get("consistency") != "online-stable-uploads"
            or set(record["artifacts"]) != set(ARTIFACTS)):
        raise ValueError("unsupported Multica backup manifest")
    for name in ARTIFACTS:
        if record["artifacts"][name] != integrity(directory / name):
            raise ValueError("backup artifact no longer matches its manifest")
    with (directory / "multica.dump").open("rb") as source:
        if source.read(5) != b"PGDMP":
            raise ValueError("database backup is not a PostgreSQL custom archive")
    if upload_inventory(directory / "uploads.tar") != record["uploads"]:
        raise ValueError("upload contents no longer match their inventory")
    if record.get("archive_checked") != "pg_restore-list-and-sql-render":
        raise ValueError("database archive was not validated during capture")
    return record


def backup(destination, kubectl, context):
    destination = private_directory(destination)
    cluster = Cluster(kubectl, context)
    config = cluster.json(["config", "view", "--minify", "-o", "json"])
    if (len(config["clusters"]) != 1
            or config["clusters"][0]["cluster"]["server"] != API_SERVER):
        raise ValueError("selected context does not use the declared homelab API")
    sources = cluster.sources()
    postgres = sources["postgres"]["name"]
    backend = sources["backend"]["name"]
    before = cluster.state(postgres)
    started_at = datetime.now(timezone.utc).isoformat()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    partial = Path(tempfile.mkdtemp(prefix=f".partial-multica-{timestamp}-", dir=destination))
    complete = partial.with_name(partial.name.removeprefix(".partial-"))
    try:
        upload_command = ["tar", "-C", "/app/data/uploads", "-cf", "-", "."]
        capture(cluster, partial / "uploads.tar", backend, "backend", upload_command)
        uploads = upload_inventory(partial / "uploads.tar")
        capture(cluster, partial / "multica.dump", postgres, "postgres",
                ["pg_dump", "-U", "multica", "-d", "multica", "--format=custom",
                 "--no-owner", "--no-acl", "--lock-wait-timeout=30s"])
        capture(cluster, partial / "uploads-after.tar", backend, "backend", upload_command)
        if uploads != upload_inventory(partial / "uploads-after.tar"):
            raise ValueError("uploads changed during backup; no backup published")
        after = cluster.state(postgres)
        if before != after or sources != cluster.sources():
            raise ValueError("tasks, attachments, migrations, or source Pods changed during backup")
        for options in (["--list"], ["--exit-on-error", "--file=/dev/null"]):
            with (partial / "multica.dump").open("rb") as source:
                cluster.execute(postgres, "postgres", ["pg_restore", *options],
                                stdin=source, stdout=subprocess.DEVNULL,
                                timeout=ARCHIVE_TIMEOUT_SECONDS)
        (partial / "uploads-after.tar").unlink()
        record = {
            "format": 1, "started_at": started_at,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "consistency": "online-stable-uploads",
            "limitations": "Writers were not fenced; not an atomic snapshot or restore drill."
                            " Runtime PVC and external secrets are not included.",
            "archive_checked": "pg_restore-list-and-sql-render",
            "context": context, "namespace": NAMESPACE, "sources": sources,
            "database_state": before, "uploads": uploads,
            "artifacts": {name: integrity(partial / name) for name in ARTIFACTS},
        }
        descriptor = os.open(partial / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(record, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        verify(partial)
        sync_directory(partial)
        partial.rename(complete)
        sync_directory(destination)
        return complete, record
    finally:
        if partial.exists():
            shutil.rmtree(partial)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("backup")
    save.add_argument("--destination", type=Path, required=True,
                      help="existing mode-0700 directory outside Git")
    save.add_argument("--context", required=True, help="explicit homelab Kubernetes context")
    save.add_argument("--kubectl", default="kubectl")
    check = commands.add_parser("verify", help="offline integrity check of a captured backup")
    check.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            directory, record = backup(args.destination, args.kubectl, args.context)
        else:
            directory = args.directory
            record = verify(directory)
        print(f"Verified online backup: {directory}")
        print(f"Database archive: {record['artifacts']['multica.dump']['bytes']} bytes; "
              f"uploads: {len(record['uploads'])} files; "
              "writers not fenced; restore not tested.")
        return 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Backup failed: a read-only cluster command failed or timed out; "
              "private command output withheld.", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        print("Backup failed: private destination, source stability, archive, or "
              "integrity check failed; no new completed backup published.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
