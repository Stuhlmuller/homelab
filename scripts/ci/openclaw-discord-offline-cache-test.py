#!/usr/bin/env python3
"""Check exact npm integrity across supported npm --json result shapes."""

import json
from pathlib import Path
import runpy
import unittest


SUT = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                         "scripts/openclaw-discord-offline-cache.py"))
INTEGRITY = SUT["INTEGRITY"]


class RegistryIntegrity(unittest.TestCase):
    def test_exact_scalar_or_singleton_array(self):
        for result in (INTEGRITY, [INTEGRITY]):
            with self.subTest(result=result):
                SUT["check_registry_integrity"](json.dumps(result))

    def test_changed_or_ambiguous_metadata_fails_closed(self):
        for result in ("sha512-wrong", ["sha512-wrong"], [INTEGRITY, INTEGRITY],
                       {"integrity": INTEGRITY}, []):
            with self.subTest(result=result):
                with self.assertRaisesRegex(ValueError, "integrity changed"):
                    SUT["check_registry_integrity"](json.dumps(result))

    def test_lock_difference_paths_omit_values(self):
        warm = {"packages": {"node_modules/example": {
            "version": "1.0.0", "resolved": "https://public.example/a"}}}
        offline = {"packages": {"node_modules/example": {
            "version": "1.0.0", "resolved": "secret-value"}}}
        differences = SUT["lock_difference_paths"](warm, offline)
        self.assertEqual(differences, ["/packages/node_modules/example/resolved"])
        self.assertNotIn("secret-value", str(differences))


if __name__ == "__main__":
    unittest.main()
