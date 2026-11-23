"""Offline review packet checks using synthetic plans and disposable keys."""

import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

spec = spec_from_file_location("review_packet", Path(__file__).with_name("review_packet.py"))
review = module_from_spec(spec)
spec.loader.exec_module(review)

MAIN = "a" * 40
PRIMARY = "B" * 40
SIGNER = "C" * 40
STAMP = 1_800_000_000
PLAN = b"disposable encrypted plan fixture"


def gpg_status(primary=PRIMARY, signer=SIGNER, stamp=STAMP + 1, hash_id=8):
    return (f"[GNUPG:] NEWSIG\n"
            f"[GNUPG:] GOODSIG {signer[-16:]} Synthetic Fixture\n"
            f"[GNUPG:] VALIDSIG {signer} 2027-01-01 {stamp} 0 4 0 1 {hash_id} 00 {primary}\n")


class ReviewPacket(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        self.directory = Path(fixture.name)
        self.plan = self.write("plan.out", PLAN)
        self.packet = self.write("review.json", review.canonical_packet(MAIN, hashlib.sha256(PLAN).hexdigest(), STAMP))
        self.signature = self.write("review.sig", b"fake signature")
        self.keyring = self.write("owner.gpg", b"fixture public keyring")

    def write(self, name, data):
        path = self.directory / name
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    def verify(self, **extra):
        arguments = dict(current_main=MAIN, owner_keyring=self.keyring, owner_primary=PRIMARY,
                         owner_signer=SIGNER, now=STAMP + 10)
        arguments.update(extra)
        return review.verified_plan(self.plan, self.packet, self.signature, **arguments)

    def verifier(self, status=None):
        return patch.object(review.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, (gpg_status() if status is None else status).encode(),
        ))

    def test_exact_packet_and_private_plan_copy(self):
        with self.verifier() as run, self.verify() as copy:
            self.assertEqual(copy.read_bytes(), PLAN)
            self.assertEqual(copy.stat().st_mode & 0o777, 0o600)
            self.assertEqual(copy.parent.stat().st_mode & 0o777, 0o700)
            self.assertNotEqual(copy, self.plan)
            self.plan.write_bytes(b"replacement")
            self.assertEqual(copy.read_bytes(), PLAN)
            self.assertEqual(run.call_args.kwargs["input"], self.packet.read_bytes())
            self.assertEqual(run.call_args.args[0][-1], "-")
            self.assertIn(str(self.keyring), run.call_args.args[0])
        self.assertFalse(copy.exists())

    def test_tampered_plan_or_unsafe_file_rejected(self):
        self.plan.write_bytes(b"altered encrypted bytes")
        with self.verifier(), self.assertRaisesRegex(ValueError, "differ"), self.verify():
            self.fail()
        self.plan.unlink()
        self.plan.symlink_to(self.packet)
        with self.verifier(), self.assertRaises(OSError), self.verify():
            self.fail()
        self.packet.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "private regular"), self.verify():
            self.fail()

    def test_wrong_revision_or_stale_packet_rejected_before_signature(self):
        for options in ({"current_main": "b" * 40}, {"now": STAMP + review.MAX_AGE_SECONDS + 1},
                        {"now": STAMP - 1}):
            with self.subTest(options=options), self.verifier() as run, self.assertRaises(ValueError), self.verify(**options):
                self.fail()
            run.assert_not_called()

    def test_wrong_scope_and_noncanonical_packets_rejected(self):
        original = self.packet.read_bytes()
        for field, value in (("repository", "other/repo"), ("unit", "other-unit"),
                             ("backend", "other-bucket"), ("delete_names", ["/homelab/other"])):
            data = {**json.loads(original), field: value}
            self.packet.write_bytes((json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode())
            with self.subTest(field=field), self.assertRaises(ValueError), self.verify():
                self.fail()
        self.packet.write_bytes(original.replace(b'"created_at":', b'"created_at":1800000000,"created_at":', 1))
        with self.assertRaises(ValueError), self.verify():
            self.fail()

    def test_wrong_signer_expired_signature_or_stale_signature_rejected(self):
        for status in (
            gpg_status(primary="D" * 40),
            gpg_status(signer="D" * 40),
            gpg_status(stamp=STAMP - 1),
            gpg_status(stamp=STAMP + 11),
            gpg_status(hash_id=2),
            gpg_status() + "[GNUPG:] REVKEYSIG revoked\n",
            gpg_status() + gpg_status(),
            "[GNUPG:] GOODSIG without-a-validated-signature\n",
        ):
            with self.subTest(status=status), self.verifier(status), self.assertRaises(ValueError), self.verify():
                self.fail()

    def test_gpg_failure_is_never_approval(self):
        with patch.object(review.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "gpgv")), \
             self.assertRaises(subprocess.CalledProcessError), self.verify():
            self.fail()

    @unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "requires GnuPG")
    def test_detached_document_signature_from_disposable_subkey(self):
        keyhome = self.directory / "gpg"
        keyhome.mkdir(mode=0o700)

        def gpg(*args):
            return subprocess.run(
                ["gpg", "--homedir", str(keyhome), "--batch", "--pinentry-mode", "loopback", "--passphrase", "", *args],
                capture_output=True, check=True, timeout=30,
            ).stdout

        def fingerprints():
            return [line.split(":")[9] for line in gpg("--with-colons", "--list-keys").decode().splitlines()
                    if line.startswith("fpr:")]

        gpg("--quick-generate-key", "Retirement Fixture <fixture@example.invalid>", "ed25519", "cert", "1d")
        primary, = fingerprints()
        gpg("--quick-add-key", primary, "ed25519", "sign", "1d")
        primary, signer = fingerprints()
        self.keyring.write_bytes(gpg("--export", primary))
        self.packet.write_bytes(review.canonical_packet(MAIN, hashlib.sha256(PLAN).hexdigest(), int(time.time())))
        self.signature.write_bytes(gpg("--local-user", signer + "!", "--digest-algo", "SHA256",
                                       "--output", "-", "--detach-sign", str(self.packet)))

        def verify():
            return self.verify(owner_primary=primary, owner_signer=signer, now=int(time.time()))

        with verify() as copy:
            self.assertEqual(copy.read_bytes(), PLAN)
        self.plan.write_bytes(b"altered encrypted bytes")
        with self.assertRaisesRegex(ValueError, "differ"), verify():
            self.fail()


if __name__ == "__main__":
    unittest.main()
