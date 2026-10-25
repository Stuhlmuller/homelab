#!/usr/bin/env python3
"""Check exact npm integrity across supported npm --json result shapes."""

from copy import deepcopy
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

    def test_lock_comparison_ignores_only_generated_root_name(self):
        warm = {"name": "warm-project", "lockfileVersion": 3,
                "packages": {"": {"dependencies": {"@openclaw/discord": "2026.9.5"}},
                             "node_modules/@openclaw/discord": {
                                 "version": "2026.9.5", "integrity": INTEGRITY,
                                 "dependencies": {"example": "1.0.0"}},
                             "node_modules/example": {"version": "1.0.0",
                                                      "integrity": "sha512-example"}}}
        offline = deepcopy(warm)
        offline["name"] = "offline-project"
        self.assertTrue(SUT["dependency_locks_match"](warm, offline))

        for changed in (
            lambda lock: lock["packages"].pop("node_modules/example"),
            lambda lock: lock["packages"]["node_modules/example"].update(version="2.0.0"),
            lambda lock: lock["packages"]["node_modules/example"].update(integrity="changed"),
            lambda lock: lock["packages"]["node_modules/example"].update(resolved="changed"),
            lambda lock: lock["packages"]["node_modules/@openclaw/discord"][
                "dependencies"].update(example="2.0.0"),
            lambda lock: lock["packages"][""]["dependencies"].update({
                "@openclaw/discord": "2026.9.4"}),
            lambda lock: lock.update(lockfileVersion=2),
            lambda lock: lock.update(name=""),
        ):
            with self.subTest(changed=changed):
                differing = deepcopy(offline)
                changed(differing)
                self.assertFalse(SUT["dependency_locks_match"](warm, differing))


if __name__ == "__main__":
    unittest.main()
