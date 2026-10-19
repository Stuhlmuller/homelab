#!/usr/bin/env python3
"""Exercise the protected catalog script with offline command fixtures."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("octelium-private-kubernetes-apply.sh")
STUB = r'''
import json
import os
from pathlib import Path
import shutil
import sys

root = Path(os.environ["FIXTURE_ROOT"])
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
assert os.environ.get("GH_TOKEN") == "synthetic" if tool == "gh" else "GH_TOKEN" not in os.environ

def event(name):
    with (root / "calls.jsonl").open("a") as log:
        log.write(json.dumps(name) + "\n")

if tool == "yq":
    print("[]" if "-o=json" in args else "kind: Policy\nmetadata:\n  name: fixture")
elif tool == "jq":
    pass
elif tool == "curl":
    Path(args[args.index("-o") + 1]).touch()
elif tool == "sha256sum":
    assert args == ["--check", "-"]
    sys.stdin.read()
elif tool == "tar":
    destination = Path(args[args.index("-C") + 1]) / "octeliumctl"
    shutil.copyfile(sys.argv[0], destination)
    destination.chmod(0o700)
elif tool == "gh":
    assert args == ["api", "repos/Stuhlmuller/homelab/git/ref/heads/main", "--jq", ".object.sha"]
    event("main.check")
    checks = sum(json.loads(line) == "main.check"
                 for line in (root / "calls.jsonl").read_text().splitlines())
    if os.environ.get("LOOKUP_FAIL") == "true":
        sys.exit(23)
    print("stale" if checks >= int(os.environ.get("STALE_AT", "1000")) else "fixture")
elif tool == "octeliumctl":
    if "login" in args:
        event("catalog.login")
    elif "logout" in args:
        event("catalog.logout")
    elif "apply" in args:
        event("catalog.apply")
        applies = sum(json.loads(line) == "catalog.apply"
                      for line in (root / "calls.jsonl").read_text().splitlines())
        if applies == 2:
            print("No applied changes in Cluster Core resources")
    else:
        sys.exit(99)
else:
    sys.exit(99)
'''


class PrivateKubernetesApplyTest(unittest.TestCase):
    def run_script(self, *, stale_at=None, lookup_fail=False):
        with tempfile.TemporaryDirectory(prefix="private-kubernetes-test-") as tmp:
            root = Path(tmp)
            binaries = root / "bin"
            binaries.mkdir()
            for name in ("yq", "jq", "curl", "sha256sum", "tar", "gh"):
                path = binaries / name
                path.write_text(f"#!{sys.executable}\n" + STUB)
                path.chmod(0o700)
            environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                               FIXTURE_ROOT=str(root), GITHUB_SHA="fixture",
                               GITHUB_REPOSITORY="Stuhlmuller/homelab", GH_TOKEN="synthetic",
                               OCTELIUM_CATALOG_AUTH_TOKEN="synthetic")
            if stale_at is not None:
                environment["STALE_AT"] = str(stale_at)
            if lookup_fail:
                environment["LOOKUP_FAIL"] = "true"
            result = subprocess.run(["bash", str(SCRIPT)], cwd=SCRIPT.parents[2],
                                    env=environment, text=True, capture_output=True,
                                    timeout=10, check=False)
            calls_file = root / "calls.jsonl"
            calls = [json.loads(line) for line in calls_file.read_text().splitlines()] if calls_file.exists() else []
            return result, calls

    def test_checks_main_before_both_catalog_writes(self):
        result, calls = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["catalog.login", "main.check", "catalog.apply",
                                 "main.check", "catalog.apply", "catalog.logout"])

    def test_new_main_blocks_first_or_second_write(self):
        for stale_at, writes in ((1, 0), (2, 1)):
            with self.subTest(stale_at=stale_at):
                result, calls = self.run_script(stale_at=stale_at)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls.count("catalog.apply"), writes)
                self.assertIn("Main advanced after dispatch", result.stderr)

    def test_main_lookup_failure_blocks_write(self):
        result, calls = self.run_script(lookup_fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("catalog.apply", calls)
        self.assertIn("Unable to verify current main", result.stderr)


if __name__ == "__main__":
    unittest.main()
