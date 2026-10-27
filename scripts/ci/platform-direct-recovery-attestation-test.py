#!/usr/bin/env python3
"""Offline, synthetic signing fixtures for owner-attested Talos candidates."""

import importlib.util
import json
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "platform_direct_recovery_attestation",
    ROOT / "scripts/platform-direct-recovery-attestation.py")
TARGET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TARGET)
SOURCE_SHA = "a" * 40
PUBLICATION_ID = "b" * 32


class OwnerAttestation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="oce-direct-owner-test-", dir="/tmp")
        cls.root = Path(cls.temp.name)
        cls.home = cls.root / "gnupg"
        cls.home.mkdir(mode=0o700)
        cls.gpg("--pinentry-mode", "loopback", "--passphrase", "",
                "--quick-generate-key", "Fixture Owner <owner@example.invalid>",
                "ed25519", "sign", "1d")
        listing = cls.gpg("--with-colons", "--fingerprint", "--list-keys").decode()
        cls.owner = next(line.split(":")[9] for line in listing.splitlines()
                         if line.startswith("fpr:"))
        cls.gpg("--pinentry-mode", "loopback", "--passphrase", "",
                "--quick-generate-key", "Wrong Signer <wrong@example.invalid>",
                "ed25519", "sign", "1d")
        listing = cls.gpg("--with-colons", "--fingerprint", "--list-keys").decode()
        cls.wrong = [line.split(":")[9] for line in listing.splitlines()
                     if line.startswith("fpr:")][1]
        cls.public_key = cls.root / "owner.asc"
        cls.public_key.write_bytes(cls.gpg("--armor", "--export", cls.owner))

    @classmethod
    def gpg(cls, *args):
        return subprocess.run(
            ["gpg", "--homedir", str(cls.home), "--batch", *args],
            capture_output=True, check=True, timeout=30).stdout

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.directory = self.root / f"private-{self._testMethodName}"
        self.directory.mkdir(mode=0o700)
        self.candidate = self.directory / "direct-recovery.json"
        self.attestation = self.directory / "owner-attestation.json"
        self.signature = self.directory / "owner-attestation.sig"
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.record = {
            "sourceSha": SOURCE_SHA,
            "verified": False,
            "candidateVerified": True,
            "capturedAt": (self.now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "publicationId": PUBLICATION_ID,
            "transport": "direct-lan-authenticated-talos",
            "endpoint": "10.1.0.199:50000",
            "nodes": list(TARGET.platform.NODES),
            "talosMtls": True,
            "clientRole": "os:admin",
            "clientCertNotAfter": (self.now + timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "serverVersions": dict.fromkeys(TARGET.platform.NODES, "v1.11.3"),
            "lanSourceAddress": "10.1.0.50",
        }
        self.write_candidate()
        self.source_patch = patch.object(TARGET, "reviewed_source", return_value=None)
        self.public_patch = patch.object(TARGET, "PUBLIC_KEY", self.public_key)
        self.fingerprint_patch = patch.object(TARGET, "OWNER_FINGERPRINT", self.owner)
        self.source_patch.start()
        self.public_patch.start()
        self.fingerprint_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.addCleanup(self.public_patch.stop)
        self.addCleanup(self.fingerprint_patch.stop)

    def write_candidate(self, raw=None):
        self.candidate.write_bytes(raw if raw is not None else TARGET.canonical(self.record))
        self.candidate.chmod(0o600)

    def sign(self, signer=None):
        self.gpg("--local-user", (signer or self.owner) + "!",
                 "--output", str(self.signature), "--detach-sign", str(self.attestation))
        self.signature.chmod(0o600)

    def test_owner_signature_binds_exact_candidate_and_statement(self):
        TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        self.assertEqual(stat.S_IMODE(self.attestation.stat().st_mode), 0o600)
        self.assertIn("I reviewed", json.loads(self.attestation.read_text())["statement"])
        self.sign()
        self.assertEqual(
            TARGET.verify(SOURCE_SHA, self.candidate, self.attestation, self.signature),
            TARGET.attestation_for(self.record, self.candidate.read_bytes())["candidateSha256"])
        self.assertIs(self.record["verified"], False)

    def test_changed_candidate_bytes_fail_even_with_valid_owner_signature(self):
        TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        self.sign()
        self.record["serverVersions"]["acer"] = "v1.12.0"
        self.write_candidate()
        with self.assertRaisesRegex(ValueError, "differs from exact candidate"):
            TARGET.verify(SOURCE_SHA, self.candidate, self.attestation, self.signature)

    def test_wrong_signer_fails(self):
        TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        self.sign(self.wrong)
        with self.assertRaisesRegex(ValueError, "signature is untrusted"):
            TARGET.verify(SOURCE_SHA, self.candidate, self.attestation, self.signature)

    def test_path_swap_cannot_verify_different_attestation_after_byte_check(self):
        TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        original = self.attestation.read_bytes()
        self.sign()
        replacement = json.loads(original)
        replacement["statement"] = "Different statement signed after the first read"
        self.attestation.write_bytes(TARGET.canonical(replacement))
        other_signature = self.directory / "other.sig"
        self.gpg("--local-user", self.owner + "!", "--output", str(other_signature),
                 "--detach-sign", str(self.attestation))
        self.attestation.write_bytes(original)
        original_reader = TARGET.private_file

        def swap_after_checked_bytes(path, limit=1048576):
            if path == self.signature:
                self.attestation.write_bytes(TARGET.canonical(replacement))
                self.signature.write_bytes(other_signature.read_bytes())
            return original_reader(path, limit)

        with patch.object(TARGET, "private_file", side_effect=swap_after_checked_bytes):
            with self.assertRaisesRegex(ValueError, "signature is untrusted"):
                TARGET.verify(SOURCE_SHA, self.candidate, self.attestation, self.signature)

    def test_symlinked_private_file_is_refused(self):
        TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        linked = self.directory / "linked-attestation.json"
        linked.symlink_to(self.attestation)
        with self.assertRaises(OSError):
            TARGET.private_file(linked)

    def test_wrong_public_certificate_fails(self):
        TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        self.sign()
        wrong = self.root / "wrong.asc"
        wrong.write_bytes(self.gpg("--armor", "--export", self.wrong))
        with patch.object(TARGET, "PUBLIC_KEY", wrong):
            with self.assertRaisesRegex(ValueError, "fingerprint differs"):
                TARGET.verify(SOURCE_SHA, self.candidate, self.attestation, self.signature)

    def test_stale_or_verified_candidate_fails_before_attestation(self):
        self.record["capturedAt"] = (self.now - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.write_candidate()
        with self.assertRaisesRegex(ValueError, "stale"):
            TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        self.record["capturedAt"] = self.now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.record["verified"] = True
        self.write_candidate()
        with self.assertRaisesRegex(ValueError, "differs from reviewed probe"):
            TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)

    def test_wrong_node_source_or_sha_fails(self):
        self.record["nodes"] = ["acer"]
        self.write_candidate()
        with self.assertRaises(ValueError):
            TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        self.record["nodes"] = list(TARGET.platform.NODES)
        self.record["lanSourceAddress"] = "192.0.2.4"
        self.write_candidate()
        with self.assertRaises(ValueError):
            TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        self.record["lanSourceAddress"] = "10.1.0.50"
        self.record["sourceSha"] = "c" * 40
        self.write_candidate()
        with self.assertRaises(ValueError):
            TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)

    def test_statement_tamper_and_noncanonical_candidate_fail(self):
        TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        self.sign()
        statement = json.loads(self.attestation.read_text())
        statement["statement"] = "I did not review the local route"
        self.attestation.write_bytes(TARGET.canonical(statement))
        with self.assertRaisesRegex(ValueError, "differs from exact candidate"):
            TARGET.verify(SOURCE_SHA, self.candidate, self.attestation, self.signature)
        self.write_candidate(json.dumps(self.record, indent=2).encode())
        with self.assertRaisesRegex(ValueError, "canonical JSON"):
            TARGET.prepare(SOURCE_SHA, self.candidate, self.directory / "other.json")

    def test_private_files_and_one_time_prepare(self):
        self.candidate.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "private regular file"):
            TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        self.candidate.chmod(0o600)
        TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)
        with self.assertRaises(FileExistsError):
            TARGET.prepare(SOURCE_SHA, self.candidate, self.attestation)


if __name__ == "__main__":
    unittest.main()
