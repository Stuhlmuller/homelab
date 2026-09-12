#!/usr/bin/env python3
"""Prove local module shadows cannot execute before privileged CLI guards."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPERS = ("cordium-check.py", "cordium-ci-reconcile.py", "cordium-ci-retire.py", "cordium-ci-acceptance.py")


class Isolation(unittest.TestCase):
    def test_copied_checkout_rejects_module_shadow_before_import_or_retirement(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "checkout"
            subprocess.run(["git", "clone", "--quiet", "--shared", str(ROOT), str(checkout)], check=True)
            # Exercise the working sources even before their repair commit exists.
            for name in (*HELPERS, "octelium-nofx-reconcile.py"):
                shutil.copyfile(ROOT / "scripts" / name, checkout / "scripts" / name)
            marker = Path(temporary) / "untrusted-module-executed"
            (checkout / "scripts/json.py").write_text(f"open({str(marker)!r}, 'w').write('executed')\n")
            for name in HELPERS:
                with self.subTest(helper=name):
                    command = [sys.executable, str(checkout / "scripts" / name), "--help"]
                    blocked = subprocess.run(command, text=True, capture_output=True, timeout=10)
                    self.assertNotEqual(blocked.returncode, 0)
                    self.assertIn("python3 -I", blocked.stderr)
                    self.assertFalse(marker.exists())
                    isolated = subprocess.run([command[0], "-I", *command[1:]],
                                              text=True, capture_output=True, timeout=10)
                    self.assertEqual(isolated.returncode, 0, isolated.stderr)
                    self.assertFalse(marker.exists())
            expected = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            # A dirty removal must fail before yq, native calls, or module shadows.
            (checkout / ".github/workflows/cordium-check.yml").unlink()
            result = subprocess.run([sys.executable, "-I", str(checkout / "scripts/cordium-ci-retire.py"),
                "--homedir", str(Path(temporary) / "unused-login"), "--execute", "--expected-sha", expected],
                text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("clean checkout", result.stderr)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
