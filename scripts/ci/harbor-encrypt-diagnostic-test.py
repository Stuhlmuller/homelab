#!/usr/bin/env python3
"""Real encryption round trip and fail-closed recipient checks, offline."""
import gzip
import importlib.util
import io
import os
import shlex
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

    def test_scan_retains_complete_encrypted_report_only_on_failure(self):
        cases = (
            (b"malformed PRIVATE_REPORT\n" * 100000, 7, self.recipient, False, True),
            (os.urandom(1024 * 1024 + 1), 1, self.recipient, False, False),
            (b"PRIVATE_REPORT", 1, "0" * 40, False, False),
            (b"PRIVATE_REPORT", 0, self.recipient, False, False),
            (b"", 1, self.recipient, False, False),
            (b"PRIVATE_REPORT", 1, self.recipient, True, False),
        )
        for payload, audit_status, recipient, gzip_failure, retained in cases:
            with self.subTest(size=len(payload), status=audit_status, recipient=recipient), \
                 tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scripts = root / "scripts/ci"
                scripts.mkdir(parents=True)
                helper = (ROOT / "scripts/ci/harbor-encrypt-diagnostic.py").read_text()
                certificate = root / "fixture-public-key.gpg"
                certificate.write_bytes(self.certificate)
                helper = helper.replace(module.PRIMARY, self.primary).replace(module.RECIPIENT, recipient)
                helper = helper.replace(module.KEY_URL, certificate.as_uri())
                (scripts / "harbor-encrypt-diagnostic.py").write_text(helper)
                (scripts / "harbor-core-scan-check.py").write_text(f"raise SystemExit({audit_status})\n")
                report = root / "fixture-report"
                report.write_bytes(payload)
                binary = root / "bin"
                binary.mkdir()
                grype = root / "scanner/bin"
                grype.mkdir(parents=True)
                (grype / "grype").write_text(
                    "#!/bin/sh\nwhile [ \"$1\" != --file ]; do shift; done\n"
                    f"cp {shlex.quote(str(report))} \"$2\"\n")
                (binary / "nix").write_text(
                    f"#!/bin/sh\nln -s {shlex.quote(str(grype.parent))} \"$3\"\n")
                (binary / "docker").write_text("#!/bin/sh\n[ \"$1\" != image ] || echo sha256:fixture\n")
                (binary / "uname").write_text("#!/bin/sh\necho Linux\n")
                if gzip_failure:
                    (binary / "gzip").write_text("#!/bin/sh\necho partial\nexit 9\n")
                for path in [*binary.iterdir(), grype / "grype"]:
                    path.chmod(0o755)
                destination = root / "report.json.gz.gpg"
                destination.write_bytes(b"stale ciphertext")
                environment = dict(os.environ, GITHUB_ACTIONS="true", RUNNER_TEMP=str(root),
                                   PATH=str(binary) + os.pathsep + os.environ["PATH"])
                result = subprocess.run(
                    ["bash", str(ROOT / "builds/harbor-core/scan.sh"),
                     "--encrypted-report", str(destination)],
                    cwd=root, env=environment, capture_output=True, check=False,
                )
                self.assertEqual(result.returncode, audit_status, result.stderr.decode())
                self.assertNotIn(b"PRIVATE_REPORT", result.stdout + result.stderr)
                self.assertFalse(list(root.glob("harbor-core-scan.*")))
                self.assertEqual(destination.exists(), retained)
                self.assertFalse(destination.with_suffix(".partial").exists())
                if retained:
                    self.assertEqual(gzip.decompress(self.gpg("--decrypt", str(destination))), payload)
                    self.assertNotIn(b"PRIVATE_REPORT", destination.read_bytes())
                    self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_bound(self):
        self.source.write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            self.encrypt()
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
