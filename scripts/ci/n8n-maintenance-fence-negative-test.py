#!/usr/bin/env python3
"""A commented safe line must not hide an active unsafe n8n chart/valueFile."""

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts/ci/n8n-maintenance-fence-check.sh"
STACK = ROOT / "IaC/homelab/us-west-2/apps/n8n/stack.hcl"


class FenceSourceTests(unittest.TestCase):
    def rejects(self, replacement: str, original: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stack = root / "IaC/homelab/us-west-2/apps/n8n/stack.hcl"
            stack.parent.mkdir(parents=True)
            stack.write_text(STACK.read_text().replace(original, replacement, 1))
            self.assertNotEqual(stack.read_text(), STACK.read_text())
            result = subprocess.run(["bash", str(CHECK), "--source-only"], cwd=root,
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)

    def test_current_stack_passes_source_guard(self):
        result = subprocess.run(["bash", str(CHECK), "--source-only"], cwd=ROOT,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_commented_safe_value_file_with_unrelated_active_file(self):
        safe = 'valueFiles  = ["$values/clusters/homelab/apps/n8n/values.yaml"]'
        self.rejects('# ' + safe + '\n          valueFiles = ["$values/clusters/homelab/apps/n8n/other.yaml"]', safe)

    def test_commented_chart_pin_with_changed_active_chart(self):
        safe = 'targetRevision = "4.4.0"'
        self.rejects('# ' + safe + '\n        targetRevision = "4.5.0"', safe)


if __name__ == "__main__":
    unittest.main()
