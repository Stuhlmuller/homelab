#!/usr/bin/env python3
"""Keep failed mirror stderr only as ciphertext for the enrolled operator."""

import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

KEY_URL = "https://github.com/rstuhlmuller.gpg"
PRIMARY = "2E0AE9393F24306F26A9AEB5A86F8F76C83C03EC"
RECIPIENT = "4CF2875A21C967B08566F07D686CEA719DC4B96D"


def encrypt(source, destination):
    destination.unlink(missing_ok=True)
    partial = destination.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    try:
        if not 0 < source.stat().st_size <= 1024 * 1024:
            raise ValueError("Diagnostic exceeds bound")
        with urllib.request.urlopen(KEY_URL, timeout=30) as response:
            certificate = response.read(1024 * 1024 + 1)
        if len(certificate) > 1024 * 1024:
            raise ValueError("Certificate exceeds bound")
        with tempfile.TemporaryDirectory(prefix="harbor-diagnostic-") as home:
            def gpg(*args, data=None):
                return subprocess.run(
                    ["gpg", "--homedir", home, "--batch", *args],
                    input=data, capture_output=True, check=True, timeout=60,
                ).stdout

            gpg("--import", data=certificate)
            listing = gpg("--with-colons", "--fingerprint", "--fingerprint", PRIMARY).decode()
            fingerprints = [line.split(":")[9] for line in listing.splitlines()
                            if line.startswith("fpr:")]  # codespell:ignore fpr
            if not fingerprints or fingerprints[0] != PRIMARY or RECIPIENT not in fingerprints[1:]:
                raise ValueError("Recipient fingerprint mismatch")
            # Exact encryption subkey; never silently select a replacement key.
            gpg("--trust-model", "always", "--recipient", RECIPIENT + "!",
                "--output", str(partial), "--encrypt", str(source))
            partial.chmod(0o600)
            partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        encrypt(Path(sys.argv[1]), Path(sys.argv[2]))
    except Exception:
        sys.exit("Encrypted publication diagnostic unavailable; private details withheld.")
