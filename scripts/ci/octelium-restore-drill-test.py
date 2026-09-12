#!/usr/bin/env python3
"""Exercise the candidate restore script against disposable PostgreSQL fixtures."""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/octelium-storage"
CANDIDATE = APP / "restore-drill-candidate"
BACKEND = None


def run(*args, **kwargs):
    if BACKEND is not None and args[0] in BACKEND.pg_commands:
        return BACKEND.run(*args, **kwargs)
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=60, **kwargs)


class RestoreDrillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="od-", dir="/tmp")
        cls.root = Path(cls.temp.name)
        cls.socket = cls.root / "socket"
        cls.socket.mkdir()
        cls.source = cls.root / "source"
        if BACKEND is not None:
            BACKEND.start(cls.root)
        # Source metadata must differ from the drill's C-locale bootstrap.
        # Do not skip the regression if the real non-C locale is absent.
        run("initdb", "-D", str(cls.source), "-U", "octelium", "--auth=trust",
            "--encoding=UTF8", "--locale=en_US.UTF-8")
        run("pg_ctl", "-D", str(cls.source), "-l", str(cls.root / "postgres.log"),
            "-o", f"-c listen_addresses= -c unix_socket_directories={cls.socket}", "-w", "start")
        run("createdb", "-h", str(cls.socket), "-U", "octelium", "octelium")

    @classmethod
    def tearDownClass(cls):
        try:
            run("pg_ctl", "-D", str(cls.source), "-m", "immediate", "-w", "stop")
        finally:
            try:
                if BACKEND is not None:
                    BACKEND.close()
            finally:
                cls.temp.cleanup()

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(prefix="case-", dir=self.root))
        self.backups = self.case / "backups"
        self.backups.mkdir()
        self.work = self.case / "work"
        self.work.mkdir()
        self.sql("""
            DROP SCHEMA public CASCADE;
            CREATE SCHEMA public;
            CREATE TABLE octelium_resources (
                id BIGSERIAL PRIMARY KEY, uid TEXT UNIQUE NOT NULL, resource JSONB);
            CREATE TABLE octelium_data_encryption_keys (
                id BIGSERIAL PRIMARY KEY, uid TEXT UNIQUE NOT NULL, ciphertext BYTEA);
            CREATE TABLE octelium_encrypted_resources (
                id BIGSERIAL PRIMARY KEY, uid TEXT UNIQUE NOT NULL, key_uid TEXT, ciphertext BYTEA);
            INSERT INTO octelium_resources (uid, resource)
                VALUES ('fixture-resource', '{"metadata":{"uid":"fixture-resource"}}');
            INSERT INTO octelium_data_encryption_keys (uid, ciphertext)
                VALUES ('fixture-key', decode('0102', 'hex'));
            INSERT INTO octelium_encrypted_resources (uid, key_uid, ciphertext)
                VALUES ('fixture-encrypted', 'fixture-key', decode('0304', 'hex'));
        """)

    def tearDown(self):
        if BACKEND is not None:
            BACKEND.finish_case()

    def sql(self, sql):
        run("psql", "-h", str(self.socket), "-U", "octelium", "-d", "octelium",
            "-X", "-v", "ON_ERROR_STOP=1", "-c", sql)

    def backup(self, hours_old=0):
        instant = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_old)
        target = self.backups / instant.strftime("%Y%m%dT%H%M%SZ")
        target.mkdir()
        globals_sql = run("pg_dumpall", "-h", str(self.socket), "-U", "octelium",
                          "--no-role-passwords", "--globals-only").stdout
        if BACKEND is not None:
            # The real globals-restore psql/server path must also contain SQL
            # program children. This inert probe requires actual syscall EPERM.
            globals_sql += """
\\! /bin/sh /tests/restore-console-probe.sh client
COPY (SELECT 1) TO PROGRAM '/bin/sh /tests/restore-console-probe.sh server';
CREATE TEMP TABLE fixture_program_child (value INTEGER);
COPY fixture_program_child FROM PROGRAM '/tests/probe denied && printf "1\\n"';
DO $fixture$ BEGIN
  IF (SELECT count(*) FROM fixture_program_child WHERE value = 1) <> 1 THEN
    RAISE EXCEPTION 'filtered SQL child probe did not complete';
  END IF;
END; $fixture$;
DROP TABLE fixture_program_child;
"""
        (target / "globals.sql").write_text(globals_sql)
        run("pg_dump", "-h", str(self.socket), "-U", "octelium", "--format=custom",
            "--file", str(target / "octelium.dump"), "octelium")
        self.write_checksums(target)
        return target

    def write_checksums(self, target):
        checksum_lines = [f"{hashlib.sha256((target / name).read_bytes()).hexdigest()}  {name}\n"
                          for name in ("globals.sql", "octelium.dump")]
        (target / "SHA256SUMS").write_text("".join(checksum_lines))

    def drill(self):
        if BACKEND is not None:
            return BACKEND.drill(self.backups, self.work, CANDIDATE / "restore-drill.sh")
        # GNU coreutils/findutils are declared in the Nix development shell.
        return subprocess.run(["sh", str(CANDIDATE / "restore-drill.sh"), str(self.backups), str(self.work)],
                              capture_output=True, text=True, timeout=90)

    def assert_failure(self, result, stage):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertIn(f"failed at {stage};", (self.work / "restore-drill/details.log").read_text())
        self.assertFalse((self.work / "restore-drill/pgdata/postmaster.pid").exists())

    def test_actual_restore_preserves_source_and_withholds_private_output(self):
        target = self.backup()
        before = {p.name: p.read_bytes() for p in target.iterdir()}
        for p in target.iterdir():
            p.chmod(0o400)
        result = self.drill()
        self.assertEqual(result.returncode, 0, result.stderr + "\n" +
                         (self.work / "restore-drill/details.log").read_text())
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertIn("Octelium PostgreSQL restore drill passed\n",
                      (self.work / "restore-drill/details.log").read_text())
        self.assertEqual(before, {p.name: p.read_bytes() for p in target.iterdir()})
        self.assertEqual((self.work / "restore-drill/details.log").stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.work / "restore-drill/pgdata/postmaster.pid").exists())

    def test_globals_shell_cannot_write_inherited_console_descriptors(self):
        target = self.backup()
        marker = "fixture-private-client-output"
        # A real globals file may execute a shell. Update the checksum so this
        # reaches psql, not merely the corrupt-archive rejection path.
        with (target / "globals.sql").open("a") as stream:
            stream.write(
                "\\! printf '%s\\n' " + marker + "; "
                "printf '%s\\n' " + marker + " >&2; "
                "(printf '%s\\n' " + marker + " >&3) 2>/dev/null; "
                "(printf '%s\\n' " + marker + " >&4) 2>/dev/null; "
                "printf executed > client-shell-executed\n")
        self.write_checksums(target)
        result = self.drill()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")
        private = self.work / "restore-drill"
        self.assertEqual((private / "backup/client-shell-executed").read_text(), "executed")
        self.assertIn(marker, (private / "details.log").read_text())


    def test_globals_server_program_cannot_write_inherited_console_descriptors(self):
        target = self.backup()
        marker = "fixture-private-server-output"
        with (target / "globals.sql").open("a") as stream:
            stream.write(
                "COPY (SELECT 1) TO PROGRAM 'cat >/dev/null; "
                "printf " + marker + "; printf " + marker + " >&2; "
                "(printf " + marker + " >&3) 2>/dev/null; "
                "(printf " + marker + " >&4) 2>/dev/null; "
                "printf executed > server-program-executed';\n")
        self.write_checksums(target)
        result = self.drill()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")
        private = self.work / "restore-drill"
        self.assertEqual((private / "pgdata/server-program-executed").read_text(), "executed")
        self.assertIn(marker, (private / "postgres.log").read_text())


    def test_custom_archive_restores_database_locale_encoding_and_owner(self):
        target = self.backup()  # Same pg_dump --format=custom without --create as production.
        listing = run("pg_restore", "--create", "--list", str(target / "octelium.dump")).stdout
        self.assertRegex(listing, r"(?m)^\d+; \d+ \d+ DATABASE - octelium octelium$")
        metadata_sql = """
            SELECT json_build_object('encoding', pg_encoding_to_char(encoding),
                                     'collate', datcollate, 'ctype', datctype,
                                     'owner', pg_get_userbyid(datdba))
            FROM pg_database WHERE datname = 'octelium';
        """
        expected = run("psql", "-h", str(self.socket), "-U", "octelium", "-d", "octelium",
                       "-XAt", "-v", "ON_ERROR_STOP=1", "-c", metadata_sql).stdout
        self.assertEqual(json.loads(expected), {"encoding": "UTF8", "collate": "en_US.UTF-8",
                                              "ctype": "en_US.UTF-8", "owner": "octelium"})
        result = self.drill()
        self.assertEqual(result.returncode, 0, result.stderr)
        restored = self.work / "restore-drill/pgdata"
        socket = self.work / "restore-drill/socket"
        run("pg_ctl", "-D", str(restored), "-l", str(self.work / "inspection.log"),
            "-o", f"-c listen_addresses= -c unix_socket_directories={socket}", "-w", "start")
        try:
            actual = run("psql", "-h", str(socket), "-U", "restore_drill", "-d", "octelium",
                         "-XAt", "-v", "ON_ERROR_STOP=1", "-c", metadata_sql).stdout
            self.assertEqual(json.loads(actual), json.loads(expected))
        finally:
            run("pg_ctl", "-D", str(restored), "-m", "immediate", "-w", "stop")

    def test_corrupt_latest_archive_does_not_fall_back(self):
        self.backup(hours_old=24)
        latest = self.backup()
        with (latest / "octelium.dump").open("ab") as stream:
            stream.write(b"corrupt")
        self.assert_failure(self.drill(), "archive-verification")

    def test_checksum_manifest_cannot_read_outside_recovery_set(self):
        latest = self.backup()
        (latest / "SHA256SUMS").write_text("0" * 64 + "  /etc/passwd\n")
        self.assert_failure(self.drill(), "archive-verification")

    def test_stale_latest_backup_fails_before_restore(self):
        self.backup(hours_old=31)
        self.assert_failure(self.drill(), "backup-selection")

    def test_previous_day_cannot_count_as_current_restore_success(self):
        self.backup(hours_old=24)
        self.assert_failure(self.drill(), "backup-selection")

    def test_restored_encrypted_resource_without_key_fails(self):
        self.backup(hours_old=24)
        self.sql("UPDATE octelium_encrypted_resources SET key_uid='missing-key'")
        self.backup()
        self.assert_failure(self.drill(), "restored-data-invariants")

    def test_empty_required_table_fails(self):
        self.sql("DELETE FROM octelium_resources")
        self.backup()
        self.assert_failure(self.drill(), "restored-data-invariants")

    def test_manifest_declares_storage_credential_and_network_policy_contracts(self):
        # Rendering cannot prove enforcement by the CNI or a process boundary.
        rendered = run("kubectl", "kustomize", str(APP)).stdout
        live = json.loads(run("yq", "ea", "-o=json", "[.]", "-", input=rendered).stdout)
        self.assertFalse(any(o["kind"] in {"CronJob", "ConfigMap", "NetworkPolicy"} and
                             o["metadata"]["name"].startswith("octelium-postgres-restore-drill") for o in live))
        rendered = run("kubectl", "kustomize", str(CANDIDATE)).stdout
        candidate = json.loads(run("yq", "ea", "-o=json", "[.]", "-", input=rendered).stdout)
        self.assertEqual({o["kind"] for o in candidate}, {"CronJob", "ConfigMap", "NetworkPolicy"})
        objects = live + candidate
        job = next(o for o in objects if o["kind"] == "CronJob" and
                   o["metadata"]["name"] == "octelium-postgres-restore-drill")
        backup = next(o for o in objects if o["kind"] == "CronJob" and
                      o["metadata"]["name"] == "octelium-postgres-backup")
        self.assertEqual(backup["spec"]["timeZone"], "Etc/UTC")
        self.assertEqual(job["spec"]["timeZone"], "Etc/UTC")
        self.assertIs(job["spec"]["suspend"], True)
        backup_minute, backup_hour, *backup_days = backup["spec"]["schedule"].split()
        drill_minute, drill_hour, *drill_days = job["spec"]["schedule"].split()
        self.assertEqual(backup_days, ["*", "*", "*"])
        self.assertEqual(drill_days, ["*", "*", "*"])
        latest_backup_finish = (int(backup_hour) * 3600 + int(backup_minute) * 60 +
                                backup["spec"]["startingDeadlineSeconds"] +
                                backup["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"])
        drill_start = int(drill_hour) * 3600 + int(drill_minute) * 60
        self.assertGreaterEqual(drill_start, latest_backup_finish + 15 * 60)
        pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertFalse(pod.get("hostPID", False))
        self.assertFalse(pod.get("shareProcessNamespace", False))
        self.assertNotIn("initContainers", pod)
        self.assertEqual(len(pod["containers"]), 1)
        volumes = {v["name"]: v for v in pod["volumes"]}
        self.assertEqual(set(volumes), {"backup", "scratch", "script"})
        self.assertEqual(volumes["backup"]["persistentVolumeClaim"],
                         {"claimName": "octelium-postgres-backup", "readOnly": True})
        self.assertEqual(volumes["scratch"]["emptyDir"], {"sizeLimit": "2Gi"})
        container = pod["containers"][0]
        self.assertEqual(container["command"], ["/bin/sh", "/scripts/restore-drill.sh",
                                                "/backup/logical-backups", "/work"])
        self.assertEqual(container["terminationMessagePath"], "/root/restore-termination-log")
        self.assertEqual(container["terminationMessagePolicy"], "File")
        self.assertNotIn("env", container)
        self.assertNotIn("envFrom", container)
        self.assertTrue(next(m for m in container["volumeMounts"] if m["name"] == "backup")["readOnly"])
        policies = {o["metadata"]["name"]: o["spec"] for o in objects if o["kind"] == "NetworkPolicy"}
        self.assertEqual(set(policies), {"octelium-storage", "octelium-postgres-backup",
                                         "octelium-postgres-restore-drill", "octelium-storage-default-deny"})
        self.assertEqual(policies["octelium-storage"]["podSelector"], {"matchExpressions": [{
            "key": "app.kubernetes.io/name", "operator": "In",
            "values": ["octelium-postgres", "octelium-redis"]}]})
        self.assertEqual(policies["octelium-postgres-backup"]["podSelector"],
                         {"matchLabels": {"app.kubernetes.io/name": "octelium-postgres"}})
        default = policies["octelium-storage-default-deny"]
        self.assertEqual(default, {"podSelector": {}, "policyTypes": ["Ingress"]})
        server_services = [o for o in objects if o["kind"] == "Service"]
        self.assertEqual({o["spec"]["selector"]["app.kubernetes.io/name"] for o in server_services},
                         {"octelium-postgres", "octelium-redis"})
        deny = policies["octelium-postgres-restore-drill"]
        self.assertEqual(set(deny["policyTypes"]), {"Ingress", "Egress"})
        self.assertEqual(deny.get("ingress", []), [])
        self.assertEqual(deny.get("egress", []), [])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--image-id")
    parser.add_argument("--probe")
    options, remaining = parser.parse_known_args()
    if bool(options.image_id) != bool(options.probe):
        parser.error("--image-id and --probe must be supplied together")
    if options.image_id:
        spec = importlib.util.spec_from_file_location("fixture_docker", ROOT / "scripts/ci/octelium-restore-docker.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        BACKEND = module.DockerFixtures(options.image_id, options.probe)
    try:
        unittest.main(argv=[__file__, *remaining])
    finally:
        if BACKEND is not None:
            BACKEND.close()
