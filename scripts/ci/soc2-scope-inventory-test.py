#!/usr/bin/env python3
"""Synthetic repository tests for inventory completeness and output minimization."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "soc2-scope-inventory.py"
SPEC = importlib.util.spec_from_file_location("inventory", SCRIPT)
INVENTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVENTORY)


class InventoryTest(unittest.TestCase):
    def test_population_drift_and_value_minimization(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", "-C", directory, *args],
                                               stderr=subprocess.DEVNULL)

            def commit():
                git("add", ".")
                git("-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")

            git("init", "-q")
            (repo / "IaC").mkdir()
            (repo / "IaC/terragrunt.stack.hcl").write_text(
                'path = "live/argocd-apps/example"\n')
            component = repo / "clusters/homelab/apps/example"
            component.mkdir(parents=True)
            source = component / "manifest.yaml"
            source.write_text("synthetic-sensitive-canary: never-emit-this-value\n")
            commit()
            first = INVENTORY.collect(repo, "HEAD")
            self.assertEqual(first["total_entries"], 2)
            self.assertNotIn("never-emit-this-value", json.dumps(first))
            self.assertEqual(first, INVENTORY.collect(repo, "HEAD"))
            baseline = repo / "baseline.json"
            baseline.write_text(json.dumps(first))
            command = ["python3", str(SCRIPT), "--repo", directory,
                       "--revision", "HEAD", "--check", str(baseline)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            for action in ("change", "add", "delete"):
                if action == "change":
                    source.write_text("changed: synthetic\n")
                elif action == "add":
                    (component / "extra.yaml").write_text("kind: ConfigMap\n")
                else:
                    source.unlink()
                commit()
                self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            # Untracked private material is not part of the committed population.
            before = INVENTORY.collect(repo, "HEAD")
            (component / "private-untracked.yaml").write_text("never-emit-this-value")
            self.assertEqual(before, INVENTORY.collect(repo, "HEAD"))

    def test_missing_population_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", "-q", directory], check=True)
            with self.assertRaises(subprocess.CalledProcessError):
                INVENTORY.collect(directory, "not-a-revision")


if __name__ == "__main__":
    unittest.main()
