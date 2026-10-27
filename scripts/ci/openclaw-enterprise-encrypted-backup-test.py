#!/usr/bin/env python3
"""Exercise the dormant Enterprise packager's encrypt-before-offsite boundary."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation/backup.sh"
RESTORE = ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation/restore-drill.yaml"


def command(*args, check=True, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, check=False,
                            timeout=60, **kwargs)
    if check and result.returncode:
        raise AssertionError(f"{args[0]} failed: {result.stderr[-400:]}")
    return result


class EncryptedBackup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-encrypted-backup-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.material = self.root / "material"
        for name in ("postgres-root/tls.crt", "postgres-root/tls.key",
                     "postgres-admin/password", "postgres-migrator/password",
                     "postgres-app/password", "postgres-backup/password",
                     "auth/secret", "gateway/occ", "gateway-ca/tls.crt",
                     "gateway-ca/tls.key", "bootstrap/output.json",
                     "bootstrap/initial-admin-password",
                     "bootstrap/initial-admin-service-key.json",
                     "journal/journal.json", "tenant/metadata.json",
                     "agent/identity.json", "tenant/secrets/key",
                     "agent/state/state.db"):
            path = self.material / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture-private-material-" + name)
        (self.material / "postgres-backup/password").write_text("fixturepassword")
        (self.material / "recovery.json").write_text(
            '{"claimUid":"fixture-uid","writerStopped":true,'
            '"continuousFenceVerified":true}')
        self.offsite = self.root / "offsite"
        self.offsite.mkdir()
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.identity = self.root / "backup-age-key"
        command("age-keygen", "-o", str(self.identity))
        self.identity.chmod(0o600)
        self.recipient = self.root / "recipient.age"
        self.recipient.write_text(command("age-keygen", "-y", str(self.identity)).stdout)
        self.cert = self.root / "ca.crt"
        self.cert.write_text("fixture-ca")
        self.bootstrap = self.root / "bootstrap.sql"
        self.bootstrap.write_text("SELECT 1;\n")
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        (self.fake_bin / "mountpoint").write_text("#!/bin/sh\nexit 0\n")
        (self.fake_bin / "pg_dump").write_text(
            "#!/bin/sh\nfor arg do case \"$arg\" in "
            f"--dbname=*) printf '%s\\n' \"$arg\" > {shlex.quote(str(self.root / 'connection'))};; "
            "--file=*) printf 'fixture-private-dump' > \"${arg#--file=}\";; "
            "esac; done\n")
        (self.fake_bin / "pg_restore").write_text("#!/bin/sh\nexit 0\n")
        for path in self.fake_bin.iterdir():
            path.chmod(0o755)
        source = BACKUP.read_text()
        for before, after in (
            ("/recovery-material", str(self.material)),
            ("/backup/openclaw-enterprise", str(self.offsite / "openclaw-enterprise")),
            ("/scratch/openclaw-enterprise", str(self.scratch / "openclaw-enterprise")),
            ("/run/backup-recipient/age.pub", str(self.recipient)),
            ("/run/secrets/occ-postgres-backup/password",
             str(self.material / "postgres-backup/password")),
            ("/run/postgres-ca/tls.crt", str(self.cert)),
            ("/scripts/database-bootstrap.sql", str(self.bootstrap)),
            ('timestamp="$(date -u +%Y%m%dT%H%M%SZ)"',
             'timestamp="20261027T000000Z"'),
        ):
            source = source.replace(before, after)
        self.script = self.root / "backup.sh"
        self.script.write_text(source)
        self.env = {**os.environ,
                    "PATH": str(self.fake_bin) + os.pathsep + os.environ["PATH"]}

    def invoke(self):
        return command("bash", str(self.script), check=False, env=self.env)

    def restore_candidate(self, encrypted):
        self.restore_attempt = getattr(self, "restore_attempt", 0) + 1
        job = json.loads(command("yq", "-o=json", "-I=0", str(RESTORE)).stdout)
        script = job["spec"]["template"]["spec"]["containers"][0]["command"][2]
        substitutions = (
            ("/backup/openclaw-enterprise", str(self.offsite / "openclaw-enterprise")),
            ("/scratch/restore", str(self.root / f"restore-{self.restore_attempt}")),
            ("/run/restore-identity/identity", str(self.identity)),
            ("/run/restore-receipt/archive", str(self.root / "receipt/archive")),
            ("/run/restore-receipt/sha256", str(self.root / "receipt/sha256")),
            ("/usr/local/libexec/occ-safe-extract.py",
             str(ROOT / "builds/openclaw-enterprise-restore/safe-extract.py")),
        )
        for before, after in substitutions:
            script = script.replace(before, after)
        (self.fake_bin / "initdb").write_text("#!/bin/sh\nexit 9\n")
        (self.fake_bin / "initdb").chmod(0o755)
        return command("bash", "-c", script, check=False, env=self.env)

    def test_only_ciphertext_reaches_offsite_and_decrypts_to_complete_set(self):
        (self.scratch / "openclaw-enterprise").mkdir()
        (self.offsite / "openclaw-enterprise").mkdir()
        (self.scratch / "openclaw-enterprise").chmod(0o755)
        (self.offsite / "openclaw-enterprise").chmod(0o755)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.scratch / "openclaw-enterprise").stat().st_mode & 0o777,
                         0o700)
        self.assertEqual((self.offsite / "openclaw-enterprise").stat().st_mode & 0o777,
                         0o700)
        files = list((self.offsite / "openclaw-enterprise").iterdir())
        self.assertEqual(len(files), 1)
        encrypted = files[0]
        self.assertEqual(encrypted.name, "20261027T000000Z.tar.age")
        self.assertIn("passfile=" + str(self.scratch / "openclaw-enterprise"),
                      (self.root / "connection").read_text())
        self.assertTrue(encrypted.is_file())
        self.assertNotIn(b"fixture-private-material", encrypted.read_bytes())
        self.assertNotIn(b"fixture-private-dump", encrypted.read_bytes())
        self.assertEqual(list((self.scratch / "openclaw-enterprise").iterdir()), [])
        tarball = self.root / "decrypted.tar"
        command("age", "--decrypt", "--identity", str(self.identity),
                "--output", str(tarball), str(encrypted))
        listing = command("tar", "-tf", str(tarball)).stdout
        self.assertNotIn("details.log", listing)
        recovered = self.root / "recovered"
        recovered.mkdir()
        command("tar", "-xf", str(tarball), "-C", str(recovered))
        self.assertEqual((recovered / "database.dump").read_text(),
                         "fixture-private-dump")
        self.assertEqual((recovered / "material/recovery.json").read_text(),
                         '{"claimUid":"fixture-uid","writerStopped":true,'
                         '"continuousFenceVerified":true}')
        self.assertTrue((recovered / "SHA256SUMS").is_file())
        self.assertEqual((recovered / "material/gateway-ca/tls.crt").read_text(),
                         "fixture-private-material-gateway-ca/tls.crt")
        command("sha256sum", "--check", "SHA256SUMS", cwd=recovered)

    def test_missing_gateway_ca_never_publishes_an_archive(self):
        (self.material / "gateway-ca/tls.key").unlink()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.offsite.iterdir()), [])

    def test_missing_bootstrap_credential_never_publishes_an_archive(self):
        (self.material / "bootstrap/initial-admin-service-key.json").unlink()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.offsite.iterdir()), [])

    def test_unverified_fence_never_reaches_offsite(self):
        (self.material / "recovery.json").write_text(
            '{"claimUid":"fixture-uid","writerStopped":true,'
            '"continuousFenceVerified":false}')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.offsite.iterdir()), [])

    def test_nonlocal_scratch_never_reaches_offsite(self):
        real_stat = command("which", "stat").stdout.strip()
        (self.fake_bin / "stat").write_text(
            "#!/bin/sh\n"
            f"case \"$*\" in *{self.scratch}*) printf 'nfs\\n';; "
            f"*) exec {real_stat} \"$@\";; esac\n")
        (self.fake_bin / "stat").chmod(0o755)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backup scratch filesystem is not local", result.stderr)
        self.assertEqual(list(self.offsite.iterdir()), [])

    def test_unreviewed_age_version_never_reaches_offsite(self):
        real_age = command("which", "age").stdout.strip()
        (self.fake_bin / "age").write_text(
            "#!/bin/sh\nif [ \"$1\" = --version ]; then "
            "printf 'v0.0.0\\n'; exit 0; fi\n"
            f"exec {shlex.quote(real_age)} \"$@\"\n")
        (self.fake_bin / "age").chmod(0o755)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.offsite.iterdir()), [])

    def test_projected_recipient_symlink_inside_mount_is_accepted(self):
        projected = self.root / "..2026_10_27"
        projected.mkdir()
        (projected / "age.pub").write_text(self.recipient.read_text())
        self.recipient.unlink()
        self.recipient.symlink_to("..2026_10_27/age.pub")
        self.assertEqual(self.invoke().returncode, 0)
        self.assertEqual(len(list((self.offsite / "openclaw-enterprise").iterdir())), 1)

    def test_recipient_symlink_outside_mount_is_rejected(self):
        outside = tempfile.TemporaryDirectory(prefix="oce-recipient-outside-")
        self.addCleanup(outside.cleanup)
        target = Path(outside.name) / "age.pub"
        target.write_text(self.recipient.read_text())
        self.recipient.unlink()
        self.recipient.symlink_to(target)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(list(self.offsite.iterdir()), [])

    def test_restore_requires_private_receipt_and_matches_ciphertext_before_restore(self):
        self.assertEqual(self.invoke().returncode, 0)
        encrypted = next((self.offsite / "openclaw-enterprise").iterdir())
        missing = self.restore_candidate(encrypted)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(missing.stderr,
                         "OpenClaw Enterprise isolated restore failed at selection\n")
        receipt = self.root / "receipt"
        receipt.mkdir()
        (receipt / "archive").write_text(encrypted.name + "\n")
        (receipt / "sha256").write_text(
            hashlib.sha256(encrypted.read_bytes()).hexdigest() + "\n")
        verified = self.restore_candidate(encrypted)
        self.assertNotEqual(verified.returncode, 0)
        self.assertEqual(verified.stderr,
                         "OpenClaw Enterprise isolated restore failed at isolated-postgres\n")
        with encrypted.open("ab") as output:
            output.write(b"tampered")
        tampered = self.restore_candidate(encrypted)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertEqual(tampered.stderr,
                         "OpenClaw Enterprise isolated restore failed at integrity\n")

    def test_missing_recipient_or_failed_dump_publishes_no_partial(self):
        self.recipient.unlink()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.offsite.iterdir()), [])
        self.recipient.write_text(command("age-keygen", "-y", str(self.identity)).stdout)
        (self.fake_bin / "pg_dump").write_text("#!/bin/sh\nexit 9\n")
        (self.fake_bin / "pg_dump").chmod(0o755)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("encrypted backup failed at database", result.stderr)
        self.assertEqual(list(self.offsite.iterdir()), [])
        self.assertEqual(list((self.scratch / "openclaw-enterprise").iterdir()), [])

    def test_overdeep_material_path_fails_before_ciphertext_write(self):
        path = self.material / "agent/state"
        for _ in range(64):
            path = path / "d"
            path.mkdir()
        (path / "secret").write_text("private")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.offsite.iterdir()), [])
        self.assertEqual(list((self.scratch / "openclaw-enterprise").iterdir()), [])

    def test_archive_bounds_fail_before_ciphertext_write(self):
        for name, marker, bound in (
            ("bytes", "max_unpacked_bytes=34359738368", "10"),
            ("entries", "max_entries=100000", "10"),
            ("names", "max_aggregate_path_bytes=16777216", "100"),
        ):
            with self.subTest(name=name):
                original = self.script.read_text()
                self.script.write_text(original.replace(marker, marker.split("=")[0] + "=" + bound))
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(self.offsite.iterdir()), [])
                self.assertEqual(list((self.scratch / "openclaw-enterprise").iterdir()), [])
                self.script.write_text(original)

    def test_private_copy_failure_does_not_expose_path_in_pod_logs(self):
        sensitive = "CLASSIFIED_TENANT_FILENAME"
        (self.material / "agent/state" / sensitive).write_text("private")
        real_cp = command("which", "cp").stdout.strip()
        (self.fake_bin / "cp").write_text(
            "#!/bin/sh\n"
            f"if [ \"$1\" = -a ]; then printf '%s\\n' '{sensitive}' >&2; exit 9; fi\n"
            f"exec {shlex.quote(real_cp)} \"$@\"\n")
        (self.fake_bin / "cp").chmod(0o755)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(sensitive, result.stdout + result.stderr)
        self.assertIn("encrypted backup failed at copy", result.stderr)
        self.assertEqual(list(self.offsite.iterdir()), [])
        self.assertEqual(list((self.scratch / "openclaw-enterprise").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
