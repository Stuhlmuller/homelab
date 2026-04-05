from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RestorePolicyTests(unittest.TestCase):
    def test_policy_pack_exists(self) -> None:
        policy = ROOT / "policies" / "restore_decryption_policy.json"
        self.assertTrue(policy.exists())

    def test_fixture_runner_passes(self) -> None:
        runner = ROOT / "scripts" / "run_policy_fixtures.py"
        result = subprocess.run(
            ["python3", str(runner)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"fixture runner failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()
