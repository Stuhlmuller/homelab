#!/usr/bin/env python3
"""Cold monitoring copies only. Never scales workloads, mounts, or deletes data.

The gate executable is a trusted, separately reviewed live fence collector;
its output must be fresh and bound to this exact plan. No collector is selected
in the candidate. See docs/monitoring-reliability.md before production use.
"""

import argparse
import hashlib
import json
import os
import stat
import subprocess
import time
from pathlib import Path


class Refused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Gate:
    def __init__(self, plan, phase):
        self.plan = plan
        self.phase = phase
        self.identity = None

    def __call__(self):
        command = self.plan.get("fence_collector")
        require(
            isinstance(command, list) and command, "live fence collector is required"
        )
        executable = Path(command[0])
        require(executable.is_absolute(), "collector must have an absolute path")
        require(
            digest(executable) == self.plan.get("fence_collector_sha256"),
            "collector revision mismatch",
        )
        # stderr can include sensitive topology/auth diagnostics: never relay it.
        result = subprocess.run(
            command + [self.phase, canonical(self.plan)],
            check=False,
            capture_output=True,
            timeout=20,
        )
        require(result.returncode == 0, "live fence collector refused")
        receipt = json.loads(result.stdout)
        self.validate(receipt)

    def validate(self, receipt):
        require(receipt.get("plan_sha256") == canonical(self.plan), "wrong fence plan")
        require(receipt.get("phase") == self.phase, "wrong fence phase")
        require(0 <= time.time() - receipt["observed_at"] <= 30, "stale fence")
        require(
            receipt.get("all_consumers_accounted") is True, "unknown prior consumer"
        )
        require(receipt.get("controllers_zero") is True, "writer controller active")
        require(receipt.get("writer_pods_absent") is True, "writer Pod still exists")
        nodes = receipt.get("nodes", [])
        expected = self.plan.get("writer_nodes", [])
        require(
            expected and {n["name"] for n in nodes} == set(expected),
            "incomplete node fence",
        )
        require(len(nodes) == len(expected), "duplicate node evidence")
        for node in nodes:
            require(bool(node.get("boot_id")), "missing boot identity")
            require(
                node.get("healthy") is True,
                "unhealthy node requires a separately reviewed held fence",
            )
            require(node.get("writers_absent") is True, "node writer remains")
            require(
                node.get("writable_mounts_absent") is True,
                "node writable mount remains",
            )
        identity = sorted((n["name"], n["boot_id"]) for n in nodes)
        if self.identity is not None:
            require(identity == self.identity, "node restarted during operation")
        self.identity = identity


def inventory(root, gate):
    require(root.is_dir() and not root.is_symlink(), "invalid source directory")
    entries = {}
    for path in sorted(root.rglob("*")):
        gate()
        info = path.lstat()
        key = path.relative_to(root).as_posix()
        require(
            stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),
            "links and special files are forbidden",
        )
        require(
            not stat.S_ISREG(info.st_mode) or info.st_nlink == 1,
            "hard links are forbidden",
        )
        entries[key] = {"kind": "directory" if path.is_dir() else "file"}
        if path.is_file():
            entries[key].update(size=info.st_size, sha256=digest(path))
    require(any(v["kind"] == "file" for v in entries.values()), "empty checkpoint")
    return entries


def write_json(path, data):
    with path.open("x", encoding="utf-8") as output:
        json.dump(data, output, sort_keys=True, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_tree(source, destination, entries, gate):
    destination.mkdir(mode=0o700)
    for name, entry in entries.items():
        gate()
        target = destination / name
        if entry["kind"] == "directory":
            target.mkdir(mode=0o700)
        else:
            # O_NOFOLLOW + nlink validation rejects last-component substitution.
            fd = os.open(source / name, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as src, target.open("xb") as dst:
                info = os.fstat(src.fileno())
                require(
                    stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    "source identity changed",
                )
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    gate()
                    dst.write(block)
                dst.flush()
                os.fsync(dst.fileno())
    require(inventory(destination, gate) == entries, "copy checksum mismatch")
    for path in sorted(destination.rglob("*"), reverse=True):
        if path.is_dir():
            sync_dir(path)
    sync_dir(destination)


def validate_plan(plan):
    require(plan.get("workload") in {"prometheus", "alertmanager"}, "unknown workload")
    for field in (
        "source_pvc_uid",
        "source_pv",
        "target_pvc_uid",
        "target_pv",
        "migration_id",
    ):
        require(
            isinstance(plan.get(field), str) and plan[field],
            "incomplete claim identity",
        )
    require(
        plan["source_pvc_uid"] != plan["target_pvc_uid"],
        "source and target claims must differ",
    )
    require(
        plan["source_pv"] != plan["target_pv"], "source and target volumes must differ"
    )


def isolated_paths(source, destination):
    require(
        source.is_absolute() and destination.is_absolute(),
        "absolute private paths required",
    )
    require(source == source.resolve(), "source may not traverse symlinks")
    require(
        destination.parent == destination.parent.resolve(),
        "destination may not traverse symlinks",
    )
    require(
        not destination.exists() and not destination.is_symlink(),
        "destination already exists",
    )
    require(
        source != destination
        and source not in destination.parents
        and destination not in source.parents,
        "overlapping source and target",
    )
    require(destination.parent.is_dir(), "destination parent must already exist")


def checkpoint(plan, source, destination, gate):
    validate_plan(plan)
    isolated_paths(source, destination)
    gate()
    entries = inventory(source, gate)
    # Never replace an existing partial or complete copy, including after failure.
    partial = destination.with_name(destination.name + ".partial")
    partial.mkdir(mode=0o700)
    copy_tree(source, partial / "data", entries, gate)
    require(inventory(source, gate) == entries, "source changed during checkpoint")
    manifest = {
        "schema": 1,
        "plan_sha256": canonical(plan),
        "workload": plan["workload"],
        "source_pvc_uid": plan["source_pvc_uid"],
        "created_at": time.time(),
        "entries": entries,
    }
    write_json(partial / "manifest.json", manifest)
    gate()
    sync_dir(partial)
    # Exclusive lock serializes cooperating invocations and prevents replace races.
    require(not destination.exists(), "destination appeared during checkpoint")
    partial.rename(destination)
    sync_dir(destination.parent)
    return digest(destination / "manifest.json")


def restore(plan, checkpoint_dir, destination, proof, gate):
    validate_plan(plan)
    isolated_paths(checkpoint_dir, destination)
    gate()
    manifest_path = checkpoint_dir / "manifest.json"
    require(not manifest_path.is_symlink(), "manifest link forbidden")
    manifest_digest = digest(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    require(
        manifest["plan_sha256"] == canonical(plan), "checkpoint belongs to another plan"
    )
    require(proof.get("manifest_sha256") == manifest_digest, "restore proof mismatch")
    require(
        proof.get("isolated_application_restore_passed") is True,
        "application restore unproven",
    )
    require(
        proof.get("independent_backup_retrieved") is True,
        "off-domain retrieval unproven",
    )
    require(
        bool(proof.get("application_image_digest")),
        "missing tested application identity",
    )
    require(
        proof.get("application_image_digest") == plan.get("application_image_digest"),
        "application version mismatch",
    )
    entries = inventory(checkpoint_dir / "data", gate)
    require(entries == manifest["entries"], "checkpoint checksum mismatch")
    partial = destination.with_name(destination.name + ".partial")
    copy_tree(checkpoint_dir / "data", partial, entries, gate)
    gate()
    write_json(
        partial / "restore-receipt.json",
        {
            "manifest_sha256": manifest_digest,
            "plan_sha256": canonical(plan),
            "target_pvc_uid": plan["target_pvc_uid"],
            "created_at": time.time(),
            "startup_authorized": False,
        },
    )
    sync_dir(partial)
    require(not destination.exists(), "destination appeared during restore")
    partial.rename(destination)
    sync_dir(destination.parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["checkpoint", "restore"])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--proof", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        plan = json.loads(args.plan.read_text())
        gate = Gate(plan, args.phase)
        # Lock is deliberately retained on failure/success: reusing this target
        # requires a new reviewed operation ID/path, never automatic cleanup.
        gate()
        lock = args.destination.with_name(args.destination.name + ".lock")
        with lock.open("x"):
            if args.phase == "checkpoint":
                checkpoint(plan, args.source, args.destination, gate)
            else:
                require(args.proof is not None, "restore proof is required")
                restore(
                    plan,
                    args.source,
                    args.destination,
                    json.loads(args.proof.read_text()),
                    gate,
                )
        print("Verified cold copy complete; startup remains gated.")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # No archive paths, file names, contents, or tool diagnostics in logs.
        parser.exit(
            1,
            "Monitoring copy refused; preserve partial data and review private evidence.\n",
        )


if __name__ == "__main__":
    main()
