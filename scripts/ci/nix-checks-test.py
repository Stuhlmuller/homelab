#!/usr/bin/env python3
"""Keep signed Nix checks complete while isolating Conftest from offline fixtures."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/nix-checks.sh"


class NixChecksTests(unittest.TestCase):
    def run_fixture(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_nix = fake_bin / "nix"
            fake_nix.write_text("""#!/bin/sh
if [ "$1" = eval ]; then
  printf 'x86_64-linux'
  exit 0
fi
printf '%s\\n' "$*" >> "$NIX_CHECK_TRACE"
case "$NIX_CHECK_MODE:$*" in
  manifest:*manifest-policy*) echo 'manifest failed' >&2; exit 41 ;;
  offline:*offline-tests*) echo 'offline failed' >&2; exit 42 ;;
  trust:*manifest-policy*) echo 'ignoring untrusted substituter' >&2 ;;
esac
printf '/nix/store/fixture-check\\n'
""")
            fake_nix.chmod(0o700)
            policy = root / "policy.json"
            policy.write_text(json.dumps({"url": "https://cache.example.invalid",
                                          "publicKey": "cache-test-1:fixture"}))
            trace = root / "calls"
            result = subprocess.run(
                ["bash", str(SCRIPT), "--policy", str(policy)],
                cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
                               "NIX_CHECK_TRACE": str(trace), "NIX_CHECK_MODE": mode},
                capture_output=True, text=True, check=False, timeout=15,
            )
            return result, trace.read_text().splitlines()

    def test_all_three_checks_are_run_with_signed_cache_policy(self):
        result, calls = self.run_fixture("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertIn(".#checks.x86_64-linux.manifest-policy", calls[0])
        self.assertNotIn(".#checks.x86_64-linux.offline-tests", calls[0])
        self.assertIn(".#checks.x86_64-linux.offline-tests", calls[1])
        self.assertIn(".#checks.x86_64-linux.openwiki-setup", calls[1])
        self.assertNotIn(".#checks.x86_64-linux.manifest-policy", calls[1])
        for call in calls:
            self.assertIn("--option sandbox true", call)
            self.assertIn("--option require-sigs true", call)
            self.assertIn("--option extra-substituters https://cache.example.invalid", call)
            self.assertIn("--option extra-trusted-public-keys cache-test-1:fixture", call)
            self.assertIn("--option narinfo-cache-negative-ttl 0", call)

    def test_failed_check_stops_without_reporting_success(self):
        for mode, expected, count in (("manifest", 41, 1), ("offline", 42, 2)):
            with self.subTest(mode=mode):
                result, calls = self.run_fixture(mode)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(len(calls), count)

    def test_untrusted_cache_rejection_still_fails(self):
        result, calls = self.run_fixture("trust")
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Nix daemon rejected cache/sandbox policy", result.stderr)


if __name__ == "__main__":
    unittest.main()
