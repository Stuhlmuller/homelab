#!/usr/bin/env python3
"""Exercise the actual cutover and online backup against real SQLite databases."""
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
    source, target, backups = [root / name for name in ('source', 'target', 'backups')]
    for relative in ('state/openclaw.sqlite', 'agents/main/agent/openclaw-agent.sqlite'):
        dbpath = source / relative
        dbpath.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(dbpath) as db:
            db.execute('create table history(id integer primary key, body text)')
            db.execute('insert into history values(1, ?)', ('private canonical history\x00preserved',))
    stale_native = source / 'agents/main/agent/codex-home'
    stale_native.mkdir()
    (stale_native / 'stale-thread').write_text('hidden old NAS cache')
    archive_dir = source / 'agents/main/session-sqlite-import-archive'
    archive_dir.mkdir()
    (archive_dir / 'history.jsonl').write_text('retained NAS history')
    module.migrate(source, target)
    assert (archive_dir / 'history.jsonl').read_text() == 'retained NAS history'
    assert not (target / 'runtime/agents/main/session-sqlite-import-archive').exists()
    runtime = target / 'runtime'
    assert not (runtime / 'agents/main/agent/codex-home').exists()
    assert (stale_native / 'stale-thread').exists()
    live = sqlite3.connect(runtime / 'state/openclaw.sqlite')
    assert live.execute('pragma journal_mode=wal').fetchone()[0] == 'wal'
    live.execute('insert into history values(2, ?)', ('committed live WAL row',))
    live.commit()
    module.migrate(source, target)
    assert live.execute('select count(*) from history').fetchone()[0] == 2
    archive = module.backup(runtime, backups)
    assert (archive / 'manifest.json').is_file()
    with sqlite3.connect(archive / 'state/openclaw.sqlite') as restored:
        assert restored.execute('select body from history order by id').fetchall() == [
            ('private canonical history\x00preserved',), ('committed live WAL row',)]
    assert (archive.stat().st_mode & 0o777) == 0o700
    live.close()
    (source / '.backup-verified-for-2026.9.2').write_text('verified')
    module.migrate(source, target)
    try:
        module.migrate(source, root / 'lost-local-disk')
        raise AssertionError('stale NAS source restored after cutover')
    except RuntimeError:
        assert not (root / 'lost-local-disk/runtime').exists()
    # A partial publication must never overwrite an existing runtime.
    damaged = root / 'damaged'
    (damaged / 'runtime').mkdir(parents=True)
    (damaged / 'runtime/owner-data').write_text('preserve')
    try:
        module.migrate(source, damaged)
        raise AssertionError('unmarked runtime accepted')
    except RuntimeError:
        assert (damaged / 'runtime/owner-data').read_text() == 'preserve'
    # Corrupt source must not publish the migration marker or touch the source.
    corrupt = root / 'corrupt'
    (corrupt / 'state').mkdir(parents=True)
    (corrupt / 'state/openclaw.sqlite').write_bytes(b'broken database')
    try:
        module.migrate(corrupt, root / 'rejected')
        raise AssertionError('corrupt database accepted')
    except (sqlite3.DatabaseError, RuntimeError):
        assert not (root / 'rejected/runtime').exists()
        assert (corrupt / 'state/openclaw.sqlite').read_bytes() == b'broken database'
print('OpenClaw runtime migration and online WAL backup checks passed')
