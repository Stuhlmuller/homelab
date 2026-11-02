#!/usr/bin/env python3
"""Run the static gate with inert tools and inspect every Terragrunt cache."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/static-checks.sh"


class StaticCacheTests(unittest.TestCase):
    def run_gate(self, failure=""):
        with tempfile.TemporaryDirectory(prefix="static-cache-fixture-") as temporary:
            directory = Path(temporary)
            binary = directory / "terragrunt"
            binary.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, signal, sys
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
cache = pathlib.Path(os.environ["TG_DOWNLOAD_DIR"]).resolve()
repo = pathlib.Path(os.environ["CACHE_TEST_REPO"]).resolve()
assert cache != repo and repo not in cache.parents
assert cache.stat().st_mode & 0o777 == 0o700
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"cache": str(cache), "cwd": os.getcwd(), "args": args}) + "\\n")
state = cache / "fixture" / ".terraform" / "terraform.tfstate"
state.parent.mkdir(parents=True, exist_ok=True)
state.write_text("synthetic backend metadata")
mode = os.environ["CACHE_TEST_FAILURE"]
if "init" in args and mode == "init":
    sys.exit(17)
if "init" in args and mode == "term":
    os.kill(os.getppid(), signal.SIGTERM)
if "render" in args:
    config = repo / "IaC/homelab/us-west-2/operator/entra-emergency-global-admin/terragrunt.hcl"
    import re
    enabled = re.search(r"emergency_global_admin_enabled\\s*=\\s*(true|false)", config.read_text())[1] == "true"
    print(json.dumps({"locals": {"emergency_global_admin_enabled": enabled}, "exclude": {"if": not enabled, "actions": ["apply", "destroy"]}}))
''')
            binary.chmod(0o700)
            # Execute the complete real shell flow, including each unit's init,
            # while replacing expensive tests/scanners with inert functions.
            harness = '''
set -euo pipefail
python3() {
  case "$*" in
    *registration-test.py*) command terragrunt render ;;
  esac
}
node() { :; }
bash() { :; }
checkov() { :; }
source "$1" --offline-verified
'''
            result = subprocess.run(
                ["bash", "-c", harness, "fixture", str(SCRIPT)], cwd=ROOT,
                env={**os.environ, "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                     "CACHE_TEST_REPO": str(ROOT), "CACHE_TEST_FAILURE": failure,
                     "TG_DOWNLOAD_DIR": str(ROOT / ".must-not-use-this-cache")},
                text=True, capture_output=True, timeout=30,
            )
            log = directory / "calls.jsonl"
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            self.assertTrue(calls, result.stderr)
            caches = {call["cache"] for call in calls}
            self.assertEqual(len(caches), 1)
            for cache in caches:
                self.assertFalse(Path(cache).exists(), "cache survived exit")
            self.assertFalse((ROOT / ".must-not-use-this-cache").exists())
            return result, calls

    def test_success_covers_each_operator_and_child_invocation(self):
        result, calls = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        initialized = {Path(call["cwd"]).name for call in calls if "init" in call["args"]}
        self.assertEqual(initialized, {
            "github-actions-role-policy", "azuread-ci-identities", "entra-stuhlmuller-domain",
            "entra-stuhlmuller-pilot-user", "entra-emergency-global-admin", "entra-owner-mail",
            "entra-google-workspace-federation", "etcd-backup-storage", "kubernetes-node-labels",
        })
        self.assertGreaterEqual(sum(call["args"] == ["render"] for call in calls), 3)

    def test_init_failure_cleans_private_cache(self):
        result, _ = self.run_gate("init")
        self.assertEqual(result.returncode, 17, result.stderr)

    def test_termination_cleans_private_cache(self):
        result, _ = self.run_gate("term")
        self.assertEqual(result.returncode, 143, result.stderr)


if __name__ == "__main__":
    unittest.main()
