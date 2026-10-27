#!/usr/bin/env python3
"""Exercise the dormant PostgreSQL roles, TLS boundary and recovery candidate."""

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation"
POSTGRES_ENV = None


def postgres18_environment():
    # PostgreSQL 14 stays first on PATH for the existing Octelium restore gate.
    for directory in os.get_exec_path():
        initdb = Path(directory) / "initdb"
        if not initdb.is_file():
            continue
        version = subprocess.run((str(initdb), "--version"), check=False,
                                 capture_output=True, text=True, timeout=10)
        if version.returncode == 0 and version.stdout.strip().startswith("initdb (PostgreSQL) 18."):
            environment = os.environ.copy()
            environment["PATH"] = f"{directory}{os.pathsep}{environment.get('PATH', '')}"
            return environment
    raise AssertionError("PostgreSQL 18 binaries are required for the Enterprise restore fixture")


def run(*command, check=True, **kwargs):
    if POSTGRES_ENV is not None:
        kwargs.setdefault("env", POSTGRES_ENV)
    result = subprocess.run(command, check=False, capture_output=True, text=True,
                            timeout=90, **kwargs)
    if check and result.returncode:
        raise AssertionError(f"{command[0]} failed: {result.stderr[-900:]}")
    return result


class PostgresFoundation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global POSTGRES_ENV
        POSTGRES_ENV = postgres18_environment()
        for binary in ("initdb", "pg_ctl", "createdb", "psql", "pg_dump", "pg_restore"):
            version = run(binary, "--version").stdout.strip()
            if not version.startswith(f"{binary} (PostgreSQL) 18."):
                raise AssertionError(f"{binary} must be PostgreSQL 18, found {version}")
        cls.temp = tempfile.TemporaryDirectory(prefix="oce-pg-", dir="/tmp")
        cls.root = Path(cls.temp.name)
        cls.data = cls.root / "source"
        cls.socket = cls.root / "socket"
        cls.socket.mkdir()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.cert = cls.root / "tls.crt"
        key = cls.root / "tls.key"
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cls.cert))
        key.chmod(0o600)
        resource = json.loads(run("yq", "ea", "-o=json", "-I=0", "[.]",
                                  str(APP / "postgres.yaml")).stdout)[0]
        hba = resource["data"]["pg_hba.conf"].replace("10.244.0.0/16", "127.0.0.1/32")
        (cls.root / "pg_hba.conf").write_text(hba)
        initialized = run("initdb", "-D", str(cls.data), "-U", "occ_admin",
                          "--auth-local=trust", "--auth-host=scram-sha-256",
                          "--encoding=UTF8", "--locale=C", check=False)
        if initialized.returncode:
            cls.temp.cleanup()
            if (sys.platform == "darwin" and
                    "could not create shared memory segment: Operation not permitted" in initialized.stderr):
                raise unittest.SkipTest("macOS sandbox denies PostgreSQL shared memory")
            raise AssertionError(f"initdb failed: {initialized.stderr[-900:]}")
        options = (f"-c listen_addresses=127.0.0.1 -c port={cls.port} "
                   f"-c unix_socket_directories={cls.socket} -c ssl=on "
                   f"-c ssl_min_protocol_version=TLSv1.3 -c ssl_cert_file={cls.cert} "
                   f"-c ssl_key_file={key} -c hba_file={cls.root / 'pg_hba.conf'}")
        cls.options = options
        run("pg_ctl", "-D", str(cls.data), "-l", str(cls.root / "postgres.log"),
            "-o", options, "-w", "start")
        run("createdb", "-h", str(cls.socket), "-p", str(cls.port),
            "-U", "occ_admin", "openclaw_enterprise")
        server_version = int(run("psql", "-X", "-h", str(cls.socket), "-p", str(cls.port),
                                 "-U", "occ_admin", "-d", "openclaw_enterprise",
                                 "-Atqc", "SHOW server_version_num").stdout.strip())
        if not 180000 <= server_version < 190000:
            raise AssertionError(f"fixture server must be PostgreSQL 18, found {server_version}")
        cls.material = cls.root / "material"
        files = {
            "recovery.json": "{\"claimUid\":\"fixture\",\"writerStopped\":true}",
            "postgres-root/tls.crt": cls.cert.read_text(),
            "postgres-root/tls.key": key.read_text(),
            "postgres-admin/password": "A" * 40,
            "postgres-migrator/password": "M" * 40,
            "postgres-app/password": "P" * 40,
            "postgres-backup/password": "B" * 40,
            "auth/secret": "auth-fixture", "gateway/occ": "gateway-fixture",
            "bootstrap/output.json": "{\"bootstrap\":true}",
            "journal/journal.json": "{\"status\":\"complete\"}",
            "tenant/metadata.json": "{\"tenant\":\"fixture\"}",
            "tenant/secrets/agent-key": "tenant-fixture",
            "agent/identity.json": "{\"agent\":\"fixture\"}",
            "agent/state/state.db": "agent-state-fixture",
        }
        for path, content in files.items():
            target = cls.material / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        cls.restored_secrets = cls.root / "restored-secrets"
        bootstrap = (APP / "database-bootstrap.sql").read_text().replace(
            "/run/secrets", str(cls.restored_secrets))
        for name, source in (("occ-postgres-migrator", "postgres-migrator"),
                             ("occ-postgres-app", "postgres-app"),
                             ("occ-postgres-backup", "postgres-backup")):
            target = cls.restored_secrets / name
            target.mkdir(parents=True)
            (target / "password").write_text((cls.material / source / "password").read_text())
        cls.bootstrap = cls.root / "database-bootstrap.sql"
        cls.bootstrap.write_text(bootstrap)
        run("psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", str(cls.socket), "-p", str(cls.port),
            "-U", "occ_admin", "-d", "openclaw_enterprise", "-f", str(cls.bootstrap))
        # Use an actual migration-created table and its stock DML grants. This
        # self-contained migration is copied from the pinned upstream source;
        # changing that source requires reviewing the fixture again.
        migration = ROOT / "scripts/ci/fixtures/openclaw-enterprise/0008_better_auth_sessions.sql"
        source = json.loads((ROOT / "builds/openclaw-enterprise/source.json").read_text())
        if source["revision"] != "33bb74590a749f37934da4502fca6035cd234a55":
            raise AssertionError("review pinned Enterprise migration fixture for new source")
        if hashlib.sha256(migration.read_bytes()).hexdigest() != (
                "33e942da16000ac073bf052b0a0273b9f8facc6fcfdfb64547add705a51d3b82"):
            raise AssertionError("pinned Enterprise migration fixture changed")
        run("psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", str(cls.socket), "-p", str(cls.port),
            "-U", "occ_migrator", "-d", "openclaw_enterprise", "-f", str(migration))
        run("psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", str(cls.socket), "-p", str(cls.port),
            "-U", "occ_migrator", "-d", "openclaw_enterprise", "-c",
            "CREATE TABLE occ.fixture (id integer primary key, payload text); "
            "INSERT INTO occ.fixture VALUES (1, 'restored'); "
            "ALTER TABLE occ.fixture ENABLE ROW LEVEL SECURITY; "
            "CREATE POLICY app_read ON occ.fixture TO occ_app USING (true); "
            "GRANT SELECT ON occ.fixture TO occ_app")

    @classmethod
    def tearDownClass(cls):
        try:
            run("pg_ctl", "-D", str(cls.data), "-m", "immediate", "-w", "stop")
        finally:
            cls.temp.cleanup()

    def test_interrupted_bootstrap_stays_unready_after_restart(self):
        workload = json.loads(run("yq", "ea", "-o=json", "-I=0", "[.]",
                                  str(APP / "postgres.yaml")).stdout)[2]
        probe = workload["spec"]["template"]["spec"]["containers"][0][
            "readinessProbe"]["exec"]["command"][2]
        self.assertIn("occ-bootstrap-v1", probe)
        probe = probe.replace(
            "sha256sum -c /tmp/occ-postgres-startup-tls.sha256 >/dev/null 2>&1", "true")
        probe = probe.replace("/var/run/postgresql", str(self.socket))
        probe = probe.replace("-d openclaw_enterprise", f"-p {self.port} -d openclaw_enterprise")

        def ready():
            return run("sh", "-ec", probe, check=False).returncode == 0

        self.assertTrue(ready())
        run("psql", "-X", "-h", str(self.socket), "-p", str(self.port),
            "-U", "occ_admin", "-d", "openclaw_enterprise", "-c",
            "COMMENT ON DATABASE openclaw_enterprise IS NULL")
        try:
            self.assertFalse(ready(), "PG_VERSION alone cannot prove role bootstrap")
            run("pg_ctl", "-D", str(self.data), "-m", "immediate", "-w", "stop")
            run("pg_ctl", "-D", str(self.data), "-l", str(self.root / "postgres.log"),
                "-o", self.options, "-w", "start")
            self.assertFalse(ready(), "an initialized PVC must remain unready after restart")
        finally:
            run("psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", str(self.socket),
                "-p", str(self.port), "-U", "occ_admin", "-d", "openclaw_enterprise",
                "-f", str(self.bootstrap))
        self.assertTrue(ready())

    def test_roles_tls_dump_and_isolated_restore(self):
        conn = (f"host=localhost hostaddr=127.0.0.1 port={self.port} "
                f"dbname=openclaw_enterprise user=occ_app sslmode=verify-full "
                f"sslrootcert={self.cert} passfile={self.root / 'app.pgpass'}")
        (self.root / "app.pgpass").write_text(f"localhost:{self.port}:*:occ_app:{'P' * 40}\n")
        (self.root / "app.pgpass").chmod(0o600)
        self.assertEqual(run("psql", conn, "-X", "-Atqc", "SELECT payload FROM occ.fixture").stdout.strip(),
                         "restored")
        denied = run("psql", conn, "-X", "-v", "ON_ERROR_STOP=1", "-c",
                     "CREATE TABLE occ.denied (id integer)", check=False)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("permission denied", denied.stderr)
        plain = run("psql", conn.replace("sslmode=verify-full", "sslmode=disable"),
                    "-X", "-Atqc", "SELECT 1", check=False)
        self.assertNotEqual(plain.returncode, 0)
        admin = run("psql", conn.replace("user=occ_app", "user=occ_admin"),
                    "-X", "-Atqc", "SELECT 1", check=False)
        self.assertNotEqual(admin.returncode, 0)
        (self.root / "backup-role.pgpass").write_text(
            f"localhost:{self.port}:*:occ_backup:{'B' * 40}\n")
        (self.root / "backup-role.pgpass").chmod(0o600)
        backup_conn = conn.replace("user=occ_app", "user=occ_backup").replace(
            "app.pgpass", "backup-role.pgpass")
        denied_write = run("psql", backup_conn, "-X", "-v", "ON_ERROR_STOP=1",
                           "-c", "INSERT INTO occ.fixture VALUES (2, 'denied')", check=False)
        self.assertNotEqual(denied_write.returncode, 0)
        self.assertIn("permission denied", denied_write.stderr)
        self.assertEqual(run("psql", "-h", str(self.socket), "-p", str(self.port), "-U", "occ_admin",
                             "-d", "postgres", "-Atqc",
                             "SELECT rolbypassrls AND NOT rolsuper AND NOT rolcreatedb "
                             "FROM pg_roles WHERE rolname='occ_backup'").stdout.strip(), "t")
        self.assertEqual(run("psql", "-h", str(self.socket), "-p", str(self.port), "-U", "occ_admin",
                             "-d", "openclaw_enterprise", "-Atqc",
                             "SELECT string_agg(nspname || ':' || pg_get_userbyid(nspowner), ',' "
                             "ORDER BY nspname) FROM pg_namespace WHERE nspname IN ('occ', 'drizzle')"
                             ).stdout.strip(), "drizzle:occ_migrator,occ:occ_migrator")

        backups = self.root / "backups"
        script = (APP / "backup.sh").read_text()
        script = script.replace("/recovery-material", str(self.material))
        script = script.replace("/backup/openclaw-enterprise", str(backups))
        script = script.replace("/run/secrets/occ-postgres-backup/password",
                                str(self.material / "postgres-backup/password"))
        script = script.replace("/run/postgres-ca/tls.crt", str(self.cert))
        script = script.replace("/scripts/database-bootstrap.sql", str(self.bootstrap))
        script = script.replace("/tmp/occ-pgpass", str(self.root / "backup.pgpass"))
        script = script.replace("occ-postgres.openclaw-system.svc.cluster.local:5432",
                                f"localhost:{self.port}")
        script = script.replace("host=occ-postgres.openclaw-system.svc.cluster.local port=5432",
                                f"host=localhost hostaddr=127.0.0.1 port={self.port}")
        script = script.replace('timestamp="$(date -u +%Y%m%dT%H%M%SZ)"',
                                'timestamp="20261019T000000Z"')
        candidate = self.root / "backup.sh"
        candidate.write_text(script)
        fake_bin = self.root / "backup-bin"
        fake_bin.mkdir(exist_ok=True)
        mountpoint = fake_bin / "mountpoint"
        mountpoint.write_text("#!/bin/sh\nexit 0\n")
        mountpoint.chmod(0o755)
        backup_env = {**POSTGRES_ENV,
                      "PATH": f"{fake_bin}{os.pathsep}{POSTGRES_ENV['PATH']}"}
        gateway = self.material / "gateway/occ"
        gateway.rename(self.root / "missing-gateway")
        incomplete = run("sh", str(candidate), check=False, env=backup_env)
        self.assertNotEqual(incomplete.returncode, 0)
        self.assertFalse(backups.exists())
        (self.root / "missing-gateway").rename(gateway)
        backup = run("sh", str(candidate), env=backup_env)
        self.assertIn("verified OpenClaw Enterprise recovery set", backup.stdout)
        complete = next(backups.iterdir())
        self.assertTrue((complete / "database.dump").is_file())
        self.assertTrue((complete / "database-bootstrap.sql").is_file())
        checksum = (complete / "SHA256SUMS").read_bytes()
        duplicate = run("sh", str(candidate), check=False, env=backup_env)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("backup destination already exists", duplicate.stderr)
        self.assertEqual(list(backups.iterdir()), [complete])
        self.assertEqual((complete / "SHA256SUMS").read_bytes(), checksum)

        job = json.loads(run("yq", "-o=json", "-I=0", str(APP / "restore-drill.yaml")).stdout)
        self.assertEqual(job["metadata"]["name"], "occ-postgres-restore-drill")
        self.assertEqual(job["spec"]["template"]["spec"]["containers"][0]
                         ["resources"]["requests"]["ephemeral-storage"], "24Gi")
        self.assertTrue(job["spec"]["template"]["spec"]["volumes"][0]
                        ["persistentVolumeClaim"]["readOnly"])
        self.assertTrue(job["spec"]["template"]["spec"]["containers"][0]
                        ["volumeMounts"][0]["readOnly"])
        script = job["spec"]["template"]["spec"]["containers"][0]["command"][2]
        script = script.replace("/backup/openclaw-enterprise", str(backups))
        script = script.replace("/scratch/restore", str(self.root / "drill"))
        script = script.replace("/run/secrets", str(self.restored_secrets))
        self.restored_secrets.rename(self.root / "source-secrets")
        restored = run("sh", "-ec", script, check=False)
        if restored.returncode:
            details = (self.root / "drill/details.log").read_text()
            self.fail(f"isolated restore failed: {details[-1800:]}")
        self.assertEqual(restored.stdout, "")
        self.assertEqual(restored.stderr, "OpenClaw Enterprise isolated restore passed\n")
        self.assertFalse((self.root / "drill/backup").exists(),
                         "the read-only recovery archive must stay off scratch")
        self.assertFalse((self.root / "drill/pgdata/postmaster.pid").exists())
        socket_dir = self.root / "drill/socket"
        run("pg_ctl", "-D", str(self.root / "drill/pgdata"), "-l",
            str(self.root / "drill/recheck.log"), "-o",
            f"-c listen_addresses= -c unix_socket_directories={socket_dir}", "-w", "start")
        try:
            self.assertEqual(run("psql", "-h", str(socket_dir), "-U", "occ_admin",
                                 "-d", "openclaw_enterprise", "-Atqc",
                                 "SELECT payload FROM occ.fixture").stdout.strip(), "restored")
        finally:
            run("pg_ctl", "-D", str(self.root / "drill/pgdata"), "-m", "immediate", "-w", "stop")

        marker = complete / "material/recovery.json"
        original_marker = marker.read_bytes()
        checksums = complete / "SHA256SUMS"
        original_checksums = checksums.read_bytes()
        try:
            for index, invalid in enumerate((
                    {"claimUid": "fixture", "writerStopped": False},
                    {"claimUid": "", "writerStopped": True}), start=1):
                marker.write_text(json.dumps(invalid))
                checksums.write_text(run("sh", "-ec",
                    "find database.dump database-bootstrap.sql material -type f -print0 "
                    "| sort -z | xargs -0 sha256sum", cwd=complete).stdout)
                run("sha256sum", "--check", "SHA256SUMS", cwd=complete)
                invalid_script = script.replace(str(self.root / "drill"),
                                                str(self.root / f"invalid-drill-{index}"))
                invalid_script = invalid_script.replace(str(self.restored_secrets),
                                                        str(self.root / f"invalid-secrets-{index}"))
                result = run("sh", "-ec", invalid_script, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr,
                                 "OpenClaw Enterprise isolated restore failed at recovery-marker\n")
        finally:
            marker.write_bytes(original_marker)
            checksums.write_bytes(original_checksums)

        # An archive changed after the first checksum must fail the final hash
        # check, even when database restore itself succeeds.
        metadata = complete / "material/tenant/metadata.json"
        original_metadata = metadata.read_bytes()
        wrapper_dir = self.root / "wrapper"
        wrapper_dir.mkdir()
        real_pg_restore = Path(POSTGRES_ENV["PATH"].split(os.pathsep)[0]) / "pg_restore"
        wrapper = wrapper_dir / "pg_restore"
        wrapper.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            f"if '--create' in sys.argv[1:]:\n    open({str(metadata)!r}, 'ab').write(b'changed')\n"
            f"os.execv({str(real_pg_restore)!r}, [{str(real_pg_restore)!r}, *sys.argv[1:]])\n"
        )
        wrapper.chmod(0o755)
        changed = script.replace(str(self.root / "drill"), str(self.root / "changed-drill"))
        changed = changed.replace(str(self.restored_secrets), str(self.root / "changed-secrets"))
        changed_env = POSTGRES_ENV.copy()
        changed_env["PATH"] = f"{wrapper_dir}{os.pathsep}{changed_env['PATH']}"
        try:
            result = run("sh", "-ec", changed, check=False, env=changed_env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr,
                             "OpenClaw Enterprise isolated restore failed at archive-stability\n")
        finally:
            metadata.write_bytes(original_metadata)

        (complete / "material/auth/secret").write_text("tampered")
        corrupted = script.replace(str(self.root / "drill"), str(self.root / "corrupt-drill"))
        result = run("sh", "-ec", corrupted, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "OpenClaw Enterprise isolated restore failed at integrity\n")
        self.assertNotIn("tampered", result.stderr)

    def test_stock_migration_app_dml_without_create_or_admin(self):
        passfile = self.root / "app.pgpass"
        passfile.write_text(f"localhost:{self.port}:*:occ_app:{'P' * 40}\n")
        passfile.chmod(0o600)
        conn = (f"host=localhost hostaddr=127.0.0.1 port={self.port} "
                f"dbname=openclaw_enterprise user=occ_app sslmode=verify-full "
                f"sslrootcert={self.cert} passfile={passfile}")
        user = 'occ."user"'
        inserted = run("psql", conn, "-X", "-v", "ON_ERROR_STOP=1", "-Atqc",
                       f"INSERT INTO {user} (id, name, email, created_at, updated_at) "
                       "VALUES ('fixture-auth-user', 'First', 'fixture@example.invalid', now(), now()) "
                       "RETURNING name").stdout.strip()
        self.assertEqual(inserted, "First")
        self.assertEqual(run("psql", conn, "-X", "-v", "ON_ERROR_STOP=1", "-Atqc",
                             f"UPDATE {user} SET name='Second' WHERE id='fixture-auth-user' "
                             "RETURNING name").stdout.strip(), "Second")
        self.assertEqual(run("psql", conn, "-X", "-v", "ON_ERROR_STOP=1", "-Atqc",
                             f"SELECT name FROM {user} WHERE id='fixture-auth-user'"
                             ).stdout.strip(), "Second")
        self.assertEqual(run("psql", conn, "-X", "-v", "ON_ERROR_STOP=1", "-Atqc",
                             f"DELETE FROM {user} WHERE id='fixture-auth-user' RETURNING id"
                             ).stdout.strip(), "fixture-auth-user")
        run("psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", str(self.socket),
            "-p", str(self.port), "-U", "occ_migrator", "-d", "openclaw_enterprise",
            "-c", "CREATE TABLE occ.ungranted_probe (id integer)")
        denied = run("psql", conn, "-X", "-v", "ON_ERROR_STOP=1", "-c",
                     "SELECT * FROM occ.ungranted_probe", check=False)
        self.assertNotEqual(denied.returncode, 0,
                            "bootstrap must not grant broad default table access")
        self.assertIn("permission denied", denied.stderr)
        role = run("psql", "-X", "-h", str(self.socket), "-p", str(self.port),
                   "-U", "occ_admin", "-d", "openclaw_enterprise", "-Atqc",
                   "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit "
                   "FROM pg_roles WHERE rolname='occ_app'").stdout.strip()
        self.assertEqual(role, "f")


if __name__ == "__main__":
    unittest.main()
