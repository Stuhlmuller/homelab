#!/usr/bin/env python3
"""Exercise Mastodon's database privilege boundary on a private PostgreSQL instance."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'clusters/homelab/apps/mastodon/initdb-configmap.yaml'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', type=Path)
    options = parser.parse_args()

    def run(program, *arguments, check=True):
        binary = options.pg_bin / program if options.pg_bin else program
        result = subprocess.run([str(binary), *map(str, arguments)], text=True, capture_output=True)
        if check and result.returncode:
            raise AssertionError(f'{program} failed: {result.stderr[-1000:]}')
        return result

    def script(key):
        return subprocess.check_output(['yq', '-r', f'.data."{key}"', str(CONFIG)], text=True)

    with tempfile.TemporaryDirectory(prefix='mastodon-role-', dir='/tmp') as temporary:
        root = Path(temporary)
        data, socket = root / 'data', root / 'socket'
        socket.mkdir()
        credential = root / 'app-password'
        credential.write_text('A1' * 20)
        credential.chmod(0o600)
        passfile = root / 'pgpass'
        passfile.write_text('*:*:*:mastodon_app:' + credential.read_text() + '\n')
        passfile.chmod(0o600)
        sql = root / 'role.sql'
        sql.write_text(script('20-mastodon-app-role.sql'))
        initial = root / 'initial.sql'
        initial.write_text(script('10-mastodon.sql'))
        run('initdb', '-D', data, '-U', 'mastodon', '--auth-local=trust', '--auth-host=reject',
            '--locale=C', '--encoding=UTF8')
        (data / 'pg_hba.conf').write_text(
            'local all mastodon trust\nlocal all mastodon_app scram-sha-256\nlocal all all reject\n')
        run('pg_ctl', '-D', data, '-l', root / 'postgres.log', '-w', '-t', '30', '-o',
            f'-c listen_addresses= -c unix_socket_directories={socket} -c shared_buffers=16MB', 'start')
        try:
            run('createdb', '-h', socket, '-U', 'mastodon', 'mastodon')

            def admin(statement):
                return run('psql', '-X', '-h', socket, '-U', 'mastodon', '-d', 'mastodon',
                           '-At', '-v', 'ON_ERROR_STOP=1', '-c', statement).stdout.strip()

            def reconcile(check=True, database='mastodon'):
                return run('psql', '-X', '-q', '-h', socket, '-U', 'mastodon', '-d', database,
                           '-v', 'ON_ERROR_STOP=1', '-v', f'app_password_file={credential}', '-f', sql, check=check)

            def application(statement, check=True):
                connection = f'host={socket} dbname=mastodon user=mastodon_app passfile={passfile}'
                return run('psql', '-X', '-d', connection, '-At', '-v', 'ON_ERROR_STOP=1',
                           '-c', statement, check=check)

            run('psql', '-X', '-h', socket, '-U', 'mastodon', '-d', 'mastodon', '-v', 'ON_ERROR_STOP=1', '-f', initial)
            if int(admin('SHOW server_version_num')) >= 180000:
                result = run('psql', '-X', '-h', socket, '-U', 'mastodon', '-d', 'mastodon',
                             '-c', 'ALTER ROLE mastodon NOSUPERUSER', check=False)
                assert result.returncode and 'bootstrap superuser' in result.stderr
            reconcile()
            flags = admin("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='mastodon_app'")
            assert flags == 'f|f|f|f|f', flags
            assert admin("SELECT rolsuper AND oid=10 FROM pg_roles WHERE rolname='mastodon'") == 't'
            assert application('SELECT current_user').stdout.strip() == 'mastodon_app'
            assert application('CREATE ROLE forbidden', check=False).returncode
            assert application(f"SELECT pg_read_file('{credential}')", check=False).returncode
            application('CREATE TABLE preserved(id integer PRIMARY KEY); INSERT INTO preserved VALUES (7)')
            reconcile()
            assert application('SELECT id FROM preserved').stdout.strip() == '7'
            dump = root / 'backup.dump'
            run('pg_dump', '-h', socket, '-U', 'mastodon', '-d', 'mastodon', '-Fc', '-f', dump)
            run('createdb', '-h', socket, '-U', 'mastodon', '-O', 'mastodon_app', 'restored')
            run('psql', '-X', '-h', socket, '-U', 'mastodon', '-d', 'restored',
                '-v', 'ON_ERROR_STOP=1', '-f', initial)
            run('psql', '-X', '-h', socket, '-U', 'mastodon', '-d', 'restored',
                '-v', 'ON_ERROR_STOP=1', '-c', 'ALTER SCHEMA public OWNER TO mastodon_app')
            run('pg_restore', '--exit-on-error', '--no-owner', '--no-comments', '--role=mastodon_app',
                '-h', socket, '-U', 'mastodon', '-d', 'restored', dump)
            restored = run('psql', '-X', '-h', socket, '-U', 'mastodon', '-d', 'restored',
                           '-At', '-v', 'ON_ERROR_STOP=1', '-c', 'SELECT id FROM preserved')
            assert restored.stdout.strip() == '7'
            assert admin("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='pg_catalog.pg_class'::regclass") == 'mastodon'
            assert reconcile(check=False, database='postgres').returncode
            admin('CREATE TABLE unexpected_bootstrap_data(id integer); INSERT INTO unexpected_bootstrap_data VALUES (8)')
            result = reconcile(check=False)
            assert result.returncode and 'ownership migration' in result.stderr
            assert admin('SELECT id FROM unexpected_bootstrap_data') == '8'
            admin('DROP TABLE unexpected_bootstrap_data')
            credential.write_text('invalid-value')
            result = reconcile(check=False)
            assert result.returncode and 'invalid-value' not in result.stderr
            assert application('SELECT id FROM preserved').stdout.strip() == '7'
        finally:
            run('pg_ctl', '-D', data, '-w', '-t', '30', '-m', 'immediate', 'stop')
    print('Mastodon database role: password auth, least privilege, bootstrap preservation, repeatability and fail-closed data guards passed')


if __name__ == '__main__':
    main()
