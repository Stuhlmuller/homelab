#!/usr/bin/env python3
"""Real encryption round trip and fail-closed recipient checks, offline."""
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("diagnostic", ROOT / "scripts/ci/harbor-encrypt-diagnostic.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Encryption(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="harbor-crypto-test-")
        cls.root = Path(cls.temp.name)
        cls.home = cls.root / "keys"
        cls.home.mkdir(mode=0o700)
        cls.gpg("--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key",
                "Fixture <fixture@example.invalid>", "rsa2048", "sign", "1d")
        listing = cls.gpg("--with-colons", "--list-keys").decode()
        cls.primary = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))  # codespell:ignore fpr
        cls.gpg("--pinentry-mode", "loopback", "--passphrase", "", "--quick-add-key",
                cls.primary, "rsa2048", "encr", "1d")
        listing = cls.gpg("--with-colons", "--fingerprint", "--fingerprint").decode()
        cls.recipient = [line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")][1]  # codespell:ignore fpr
        cls.certificate = cls.gpg("--export", cls.primary)

    @classmethod
    def gpg(cls, *args):
        return subprocess.run(["gpg", "--homedir", str(cls.home), "--batch", *args],
                              capture_output=True, check=True).stdout

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.source = self.root / "stderr"
        self.destination = self.root / "error.gpg"
        self.source.write_bytes(b"private diagnostic fixture\n")
        self.addCleanup(self.destination.unlink, missing_ok=True)

    def encrypt(self, recipient=None):
        with patch.object(module, "PRIMARY", self.primary), \
             patch.object(module, "RECIPIENT", recipient or self.recipient), \
             patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(self.certificate)):
            module.encrypt(self.source, self.destination)

    def test_round_trip_and_no_plaintext(self):
        self.encrypt()
        self.assertNotIn(self.source.read_bytes(), self.destination.read_bytes())
        self.assertEqual(self.gpg("--decrypt", str(self.destination)), self.source.read_bytes())
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o600)

    def test_wrong_subkey_removes_stale_artifact(self):
        self.destination.write_bytes(b"stale")
        with self.assertRaises(ValueError):
            self.encrypt("0" * 40)
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.destination.with_suffix(".partial").exists())

    def test_encryption_failure_has_no_artifact(self):
        with patch.object(module.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "gpg")):
            with self.assertRaises(subprocess.CalledProcessError):
                self.encrypt()
        self.assertFalse(self.destination.exists())

    def test_bound(self):
        self.source.write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            self.encrypt()
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
