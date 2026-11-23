#!/usr/bin/env python3
"""Exercise the real E2E catalog path and final summary without live probes."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "scripts/octelium-e2e-check.sh").read_text()
# Execute the actual definitions, catalog call site and final summary. Other
# probe blocks are omitted so this fixture cannot access a cluster or network.
DEFINITIONS = SOURCE[SOURCE.index("FAILURES=0"):SOURCE.index("require_command() {")]
START = SOURCE.index('note "Checking Octelium service catalog"')
CATALOG_CHECK = SOURCE[START:SOURCE.index('if [ "${GRPC_READY}" -eq 1 ]; then', START)]
SUMMARY = SOURCE[SOURCE.rindex('if [ "${FAILURES}" -gt 0 ]; then'):]
SENTINEL = "private-fixture-do-not-print"


def policy(name):
    return f"kind: Policy\nmetadata:\n  name: homelab-private-{name}-access\nspec:\n  marker: {SENTINEL}\n"


def catalog(*names):
    return "---\n".join(policy(name) for name in names)


class CatalogTest(unittest.TestCase):
    def run_catalog(self, content, expected_failures=0):
        with tempfile.TemporaryDirectory(prefix="octelium-catalog-test-") as directory:
            root = Path(directory)
            path = root / "catalog.yaml"
            selected = root / "selected"
            if content is not None:
                path.write_text(content)
            harness = ('set -euo pipefail\nCATALOG="$1"\n' + DEFINITIONS +
                       # Stale values must not survive a rejected catalog.
                       'EXPECTED_KUBERNETES_POLICY=stale\nEXPECTED_TALOS_POLICY=stale\n' +
                       CATALOG_CHECK +
                       'printf "%s\\0%s\\0" "$EXPECTED_KUBERNETES_POLICY" "$EXPECTED_TALOS_POLICY" > "$2"\n' +
                       SUMMARY)
            result = subprocess.run(["bash", "-s", "--", str(path), str(selected)],
                                    input=harness, capture_output=True, text=True)
            self.assertEqual(result.returncode, int(expected_failures > 0), result.stderr)
            self.assertNotIn(SENTINEL, result.stdout + result.stderr)
            if expected_failures:
                self.assertEqual(result.stderr.count("FAIL:"), expected_failures, result.stderr)
                self.assertIn(f"Octelium e2e check failed with {expected_failures} failure(s).", result.stderr)
                self.assertNotIn("Octelium e2e check passed.", result.stdout)
            else:
                self.assertIn("Octelium e2e check passed.", result.stdout)
            values = selected.read_bytes().split(b"\0")[:2]
            self.assertNotIn(b"stale", values)
            return [json.loads(value) if value else None for value in values]

    def test_valid_both_policies(self):
        selected = self.run_catalog(catalog("kubernetes", "talos"))
        self.assertEqual([item["metadata"]["name"] for item in selected],
                         ["homelab-private-kubernetes-access", "homelab-private-talos-access"])
        self.assertTrue(all(item["spec"]["marker"] == SENTINEL for item in selected))

    def test_repository_catalog(self):
        selected = self.run_catalog((ROOT / "docs/examples/octelium/homelab-services.yaml").read_text())
        self.assertTrue(all(isinstance(item["spec"], dict) for item in selected))

    def test_missing_file(self):
        self.assertEqual(self.run_catalog(None, 1), [None, None])

    def test_missing_policies(self):
        for names, failures, missing_index in [((), 2, None), (("kubernetes",), 1, 1), (("talos",), 1, 0)]:
            with self.subTest(names=names):
                selected = self.run_catalog(catalog(*names), failures)
                if missing_index is None:
                    self.assertEqual(selected, [None, None])
                else:
                    self.assertIsNone(selected[missing_index])

    def test_duplicate_either_policy(self):
        for name, index in [("kubernetes", 0), ("talos", 1)]:
            with self.subTest(name=name):
                selected = self.run_catalog(catalog("kubernetes", "talos", name), 1)
                self.assertIsNone(selected[index])
                self.assertIsNotNone(selected[1-index])

    def test_malformed_yaml_before_and_after_each_policy(self):
        for name in ("kubernetes", "talos"):
            for content in (f"private: [{SENTINEL}\n---\n" + policy(name),
                            policy(name) + f"---\nprivate: [{SENTINEL}\n"):
                with self.subTest(name=name, content=content[:20]):
                    self.assertEqual(self.run_catalog(content, 1), [None, None])

    def test_unrelated_documents_are_ignored(self):
        selected = self.run_catalog("kind: Service\nmetadata:\n  name: unrelated\n---\n" + catalog("talos", "kubernetes"))
        self.assertTrue(all(item is not None for item in selected))


if __name__ == "__main__":
    unittest.main()
