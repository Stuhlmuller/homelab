#!/usr/bin/env python3
"""Verify local OpenClaw runtime state and publish online SQLite backups."""
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


def verify_runtime(target):
    runtime = target.resolve() / 'runtime'
    required = [runtime / 'state/openclaw.sqlite',
                runtime / 'agents/main/agent/openclaw-agent.sqlite']
    if not all(path.is_file() for path in required):
        raise RuntimeError('Local runtime is missing; restore a verified snapshot before startup')
    for database in owned_databases(runtime):
        verify_database(database)
    print('Verified authoritative local runtime databases', flush=True)


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
    if not all((runtime / relative).is_file() for relative in (
            'state/openclaw.sqlite', 'agents/main/agent/openclaw-agent.sqlite')):
        raise RuntimeError('Authoritative runtime database missing; refusing incomplete backup')
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
    parser.add_argument('operation', choices=['verify', 'backup', 'verify-mounts'])
    args = parser.parse_args()
    if args.operation == 'verify':
        verify_runtime(Path('/runtime-volume'))
    elif args.operation == 'verify-mounts':
        verify_mounts(Path('/runtime-volume/runtime'), Path('/data/openclaw'))
    else:
        backup(Path('/runtime-volume/runtime'), Path('/data/openclaw-runtime-snapshots'))
