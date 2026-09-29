#!/usr/bin/env python3
"""Synthetic PostgreSQL + blob recovery through the publication implementation.

Only repo-authored fixtures: no option accepts an archive, credential, host, or PVC.
Two disposable socket-only servers are always stopped before this process exits.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time

SPEC = importlib.util.spec_from_file_location('fixtures', Path(__file__).with_name('application-backup-test.py'))
FIXTURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURES)
APP = FIXTURES.APP


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', type=Path)
    args = parser.parse_args()
    binary = args.pg_bin or Path(shutil.which('pg_ctl') or '/unavailable/pg_ctl').parent
    environment = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    started = []
    begin = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='app-restore-') as directory:
        root = Path(directory)
        def run(tool, *arguments, **kwargs):
            return subprocess.run([str(binary / tool), *map(str, arguments)], env=environment,
                                  check=True, capture_output=True, text=True, timeout=60, **kwargs)
        try:
            for name, owner in [('source', 'octelium'), ('restored', 'restore_fixture')]:
                data, socket = root / name, root / (name + '-socket')
                socket.mkdir()
                run('initdb', '-D', data, '-U', owner, '--auth-local=trust', '--auth-host=reject', '--locale=C', '--encoding=UTF8')
                # Register before start so an interrupted pg_ctl is also stopped.
                started.append(data)
                run('pg_ctl', '-D', data, '-l', root / (name + '.log'), '-w', '-t', '30',
                    '-o', f'-c listen_addresses= -c unix_socket_directories={socket} -c shared_buffers=16MB', 'start')
            source_socket, restore_socket = root / 'source-socket', root / 'restored-socket'
            for app in ('octelium', 'multica'):
                run('createdb', '-h', source_socket, '-U', 'octelium', app)
                sql = '''CREATE TABLE recovery_records (uid text PRIMARY KEY, payload jsonb, blob_sha256 text);
                    INSERT INTO recovery_records VALUES ('fixture-resource', '{"metadata":{"uid":"fixture-resource"}}', '%s');
                    CREATE TABLE recovery_keys (uid text PRIMARY KEY, ciphertext bytea);
                    INSERT INTO recovery_keys VALUES ('fixture-key', decode('0102', 'hex'));''' % hashlib.sha256(b'synthetic upload').hexdigest()
                run('psql', '-X', '-h', source_socket, '-U', 'octelium', '-d', app, '-v', 'ON_ERROR_STOP=1', '-c', sql)
                workspace = root / (app + '-private')
                workspace.mkdir(mode=0o700)
                backup_root = root / (app + '-source')
                backup_root.mkdir()
                source = backup_root / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                source.mkdir()
                (source / 'globals.sql').write_text(run('pg_dumpall', '-h', source_socket, '-U', 'octelium', '--no-role-passwords', '--globals-only').stdout)
                run('pg_dump', '-h', source_socket, '-U', 'octelium', '--format=custom', '--file', source / (app + '.dump'), app)
                if app == 'multica':
                    with tarfile.open(source / 'uploads.tar', 'w') as archive:
                        entry = tarfile.TarInfo('fixture-upload.txt')
                        entry.size = len(b'synthetic upload')
                        archive.addfile(entry, io.BytesIO(b'synthetic upload'))
                    (source / 'capture.json').write_text(json.dumps({'captured_at': source.name, 'writers_fenced': True,
                        'approved_fence_reference': 'synthetic fixture; no application writers exist'}))
                (source / 'SHA256SUMS').write_text(''.join(
                    f'{hashlib.sha256((source / name).read_bytes()).hexdigest()}  {name}\n' for name in APP.CONTRACTS[app]))
                prepared = APP.prepare(source, workspace, app)
                aws = FIXTURES.FakeAWS()
                identifier = APP.publish(prepared, workspace, aws)
                restored = APP.retrieve(app, identifier, workspace, aws)
                if app == 'octelium':
                    run('psql', '-X', '-h', restore_socket, '-U', 'restore_fixture', '-d', 'postgres',
                        '-v', 'ON_ERROR_STOP=1', '-f', restored / 'globals.sql')
                run('pg_restore', '-h', restore_socket, '-U', 'restore_fixture', '-d', 'postgres',
                    '--create', '--exit-on-error', restored / (app + '.dump'))
                result = run('psql', '-X', '-h', restore_socket, '-U', 'restore_fixture', '-d', app, '-At', '-c',
                    "SELECT payload->'metadata'->>'uid' FROM recovery_records WHERE uid='fixture-resource'").stdout.strip()
                assert result == 'fixture-resource'
                result = run('psql', '-X', '-h', restore_socket, '-U', 'restore_fixture', '-d', app, '-At', '-c',
                    "SELECT encode(ciphertext,'hex') FROM recovery_keys WHERE uid='fixture-key'").stdout.strip()
                assert result == '0102'
                if app == 'multica':
                    # No generic archive extraction: inspect only the known fixture member.
                    with tarfile.open(restored / 'uploads.tar') as archive:
                        assert archive.getnames() == ['fixture-upload.txt']
                        blob = archive.extractfile('fixture-upload.txt').read()
                    expected = run('psql', '-X', '-h', restore_socket, '-U', 'restore_fixture', '-d', app, '-At', '-c',
                        "SELECT blob_sha256 FROM recovery_records WHERE uid='fixture-resource'").stdout.strip()
                    assert hashlib.sha256(blob).hexdigest() == expected
            print(f'Synthetic PostgreSQL and paired blob recovery passed in {time.monotonic() - begin:.2f}s; S3 mocked; no production access.')
        finally:
            for data in reversed(started):
                run('pg_ctl', '-D', data, '-m', 'immediate', '-w', '-t', '30', 'stop')


if __name__ == '__main__':
    main()
