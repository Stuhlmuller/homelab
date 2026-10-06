#!/usr/bin/env python3
"""Exercise runtime integrity checks and online backups against real SQLite databases."""
import importlib.util
import sqlite3
import tempfile
from pathlib import Path

path = Path('clusters/homelab/apps/openclaw/assistant/runtime-storage.py')
spec = importlib.util.spec_from_file_location('runtime_storage', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    target, backups = [root / name for name in ('target', 'backups')]
    runtime = target / 'runtime'
    for relative in ('state/openclaw.sqlite', 'agents/main/agent/openclaw-agent.sqlite'):
        dbpath = runtime / relative
        dbpath.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(dbpath) as db:
            db.execute('create table history(id integer primary key, body text)')
            db.execute('insert into history values(1, ?)', ('private canonical history\x00preserved',))
    module.verify_runtime(target)
    live = sqlite3.connect(runtime / 'state/openclaw.sqlite')
    assert live.execute('pragma journal_mode=wal').fetchone()[0] == 'wal'
    live.execute('insert into history values(2, ?)', ('committed live WAL row',))
    live.commit()
    module.verify_runtime(target)
    assert live.execute('select count(*) from history').fetchone()[0] == 2
    archive = module.backup(runtime, backups)
    assert (archive / 'manifest.json').is_file()
    with sqlite3.connect(archive / 'state/openclaw.sqlite') as restored:
        assert restored.execute('select body from history order by id').fetchall() == [
            ('private canonical history\x00preserved',), ('committed live WAL row',)]
    assert (archive.stat().st_mode & 0o777) == 0o700
    live.close()
    try:
        module.verify_runtime(root / 'lost-local-disk')
        raise AssertionError('missing runtime accepted')
    except RuntimeError:
        assert not (root / 'lost-local-disk/runtime').exists()
    # Verification never initializes or replaces owner data.
    damaged = root / 'damaged'
    (damaged / 'runtime').mkdir(parents=True)
    (damaged / 'runtime/owner-data').write_text('preserve')
    try:
        module.verify_runtime(damaged)
        raise AssertionError('incomplete runtime accepted')
    except RuntimeError:
        assert (damaged / 'runtime/owner-data').read_text() == 'preserve'
    try:
        module.backup(damaged / 'runtime', root / 'incomplete-backups')
        raise AssertionError('incomplete backup accepted')
    except RuntimeError:
        assert not (root / 'incomplete-backups').exists()
    corrupt = runtime / 'state/openclaw.sqlite'
    corrupt.write_bytes(b'broken database')
    try:
        module.verify_runtime(target)
        raise AssertionError('corrupt database accepted')
    except (sqlite3.DatabaseError, RuntimeError):
        assert corrupt.read_bytes() == b'broken database'
print('OpenClaw runtime integrity and online WAL backup checks passed')

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    canonical = root / 'canonical'
    wrong = root / 'wrong'
    for relative in ('state/openclaw.sqlite', 'agents/main/agent/openclaw-agent.sqlite'):
        target = canonical / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('canonical fixture')
        target = wrong / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('different mount fixture')
    module.verify_mounts(canonical, canonical)
    for mounted in (wrong, root / 'empty'):
        try:
            module.verify_mounts(canonical, mounted)
            raise AssertionError('incorrect runtime mounts accepted')
        except RuntimeError:
            pass
print('OpenClaw runtime mount guard: canonical identity required; empty and different mounts rejected')
