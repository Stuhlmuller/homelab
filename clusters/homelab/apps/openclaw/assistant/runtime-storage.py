#!/usr/bin/env python3
"""Offline NFS cutover and read-only online backups for OpenClaw runtime state.

Migration runs only as an init container behind the single-replica Recreate
Deployment. Never invoke it against a running source Gateway. Workspace and
configuration stay on the retained NAS claim; native Codex caches are rebuilt
on the first cutover and thereafter persist on the local claim.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_database(path):
    if path.is_symlink() or path.stat().st_nlink != 1:
        raise RuntimeError('Refusing aliased SQLite database')
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=10)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError(f'SQLite integrity check failed: {path.name}')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError(f'SQLite foreign key check failed: {path.name}')


def owned_databases(root):
    return sorted([p for p in [root / 'state/openclaw.sqlite',
                              *root.glob('agents/*/agent/openclaw-agent.sqlite')]
                   if p.exists()])


def publish(staging, complete):
    # Persist files and directory entries before publishing a durable completion marker.
    for parent, dirs, files in os.walk(staging, topdown=False, followlinks=False):
        for name in files:
            path = Path(parent) / name
            if not path.is_symlink():
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.rename(staging, complete)
    descriptor = os.open(complete.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def migrate(source, target):
    source, target = source.resolve(), target.resolve()
    runtime = target / 'runtime'
    marker = runtime / '.nfs-migration.json'
    if runtime.exists():
        if not marker.is_file() or json.loads(marker.read_text()).get('version') != 1:
            raise RuntimeError('Existing local runtime has no verified migration marker; preserve it')
        for db in owned_databases(runtime):
            verify_database(db)
        print('Verified existing local runtime; source not recopied', flush=True)
        return
    # Bootstrap writes this retained NAS marker before starting the new Gateway.
    # After that point, an empty local disk needs restore, never the stale source.
    if (source / '.backup-verified-for-2026.9.2').exists():
        raise RuntimeError('Local runtime missing after cutover; restore a verified snapshot, not stale NAS state')
    staging = target / '.runtime-migration.partial'
    if staging.exists():
        shutil.rmtree(staging)  # Only this helper-owned unpublished staging tree.
    source_bytes = 0
    for name in ('state', 'agents/main/agent'):
        for parent, dirs, names in os.walk(source / name, followlinks=False):
            if name.startswith('agents/') and 'codex-home' in dirs:
                dirs.remove('codex-home')
            source_bytes += sum((Path(parent) / item).stat().st_size for item in names
                                if not (Path(parent) / item).is_symlink())
    target.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(target).free < source_bytes * 2 + 2 * 1024**3:
        raise RuntimeError('Local cutover needs two copies of state plus 2 GiB free')
    staging.mkdir(parents=True, mode=0o700)
    files = {}
    try:
        for name in ('state', 'agents/main/agent'):
            src = source / name
            dst = staging / name
            if src.exists():
                # The NAS Codex home is an older hidden cache, not the current emptyDir.
                shutil.copytree(src, dst, symlinks=True,
                                ignore=lambda directory, names: ['codex-home'] if name.startswith('agents/') else [])
            else:
                dst.mkdir(parents=True)
        for path in sorted(staging.rglob('*')):
            if path.is_symlink():
                # SQLite aliases cannot silently keep a database on the NAS.
                if path.name.endswith(('.sqlite', '.sqlite-wal', '.sqlite-shm', '.sqlite-journal')):
                    raise RuntimeError('Refusing aliased SQLite state')
                continue
            if path.is_file():
                relative = str(path.relative_to(staging))
                checksum = digest(path)
                if checksum != digest(source / relative):
                    raise RuntimeError('Migration source changed; preserve source and retry offline')
                files[relative] = checksum
        for db in owned_databases(staging):
            verify_database(db)
        (staging / '.nfs-migration.json').write_text(json.dumps({
            'version': 1, 'createdAt': int(time.time()), 'files': files}, sort_keys=True) + '\n')
        # One directory rename publishes state, agents, and their receipt together.
        publish(staging, runtime)
        print(f'Published verified local runtime ({len(files)} files); NAS source retained', flush=True)
    except BaseException:
        # Keep partial evidence. The next init retry replaces only this unpublished tree.
        raise



def verify_mounts(runtime, mounted):
    # Full-root and direct child mounts must identify the same authoritative files.
    for relative in ('state/openclaw.sqlite', 'agents/main/agent/openclaw-agent.sqlite'):
        source, target = runtime / relative, mounted / relative
        if not source.is_file() or not target.is_file() or not source.samefile(target):
            raise RuntimeError(f'Runtime mount mismatch: {relative}; refusing empty replacement state')
        if target.parent.stat().st_uid != os.getuid():
            raise RuntimeError(f'Runtime directory is not owned by the process: {relative}')
    print('Verified runtime mounts identify the canonical databases', flush=True)


def backup(runtime, destination):
    runtime, destination = runtime.resolve(), destination.resolve()
    if not (runtime / '.nfs-migration.json').is_file():
        raise RuntimeError('Local runtime is not migration-verified')
    timestamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = destination / f'.{timestamp}.partial'
    complete = destination / timestamp
    staging.mkdir(mode=0o700)
    databases = owned_databases(runtime)
    if not databases:
        raise RuntimeError('No authoritative databases found; refusing empty backup')
    manifest = {'version': 1, 'createdAt': int(time.time()), 'databases': {}}
    for source in databases:
        relative = source.relative_to(runtime)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        deadline = time.monotonic() + 120

        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError('SQLite online backup exceeded two minutes')

        # Read only, bounded transactions: committed WAL is captured by SQLite itself.
        with closing(sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True, timeout=10)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst, pages=256, progress=progress, sleep=0.05)
                dst.execute('PRAGMA journal_mode=DELETE')
        os.chmod(target, 0o600)
        verify_database(target)
        manifest['databases'][str(relative)] = {'sha256': digest(target), 'bytes': target.stat().st_size}
    (staging / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True) + '\n')
    os.chmod(staging / 'manifest.json', 0o600)
    publish(staging, complete)
    # Retain seven completed snapshots. Incomplete snapshots are preserved for diagnosis.
    snapshots = sorted(p for p in destination.iterdir()
                       if p.is_dir() and len(p.name) == 16 and (p / 'manifest.json').is_file())
    for old in snapshots[:-7]:
        shutil.rmtree(old)
    print(f'Verified online backup: {timestamp} ({len(databases)} databases)', flush=True)
    return complete


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['migrate', 'backup', 'verify-mounts', 'checkpoint'])
    args = parser.parse_args()
    if args.operation == 'migrate':
        migrate(Path('/legacy/openclaw'), Path('/runtime-volume'))
    elif args.operation == 'verify-mounts':
        verify_mounts(Path('/runtime-volume/runtime'), Path('/data/openclaw'))
    elif args.operation == 'checkpoint':
        backup(Path('/runtime-volume/runtime'), Path('/data/openclaw-backups/pre-2026.9.2-runtime'))
    else:
        backup(Path('/runtime-volume/runtime'), Path('/data/openclaw-runtime-snapshots'))
