#!/usr/bin/env python3
"""Offline failure cases for the focused Octelium plan catalog activation."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/octelium-ci-plan-catalog.sh"

STUB = r'''
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["FIXTURE_ROOT"])
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
events = root / "events.jsonl"

def event(name):
    with events.open("a") as out:
        out.write(json.dumps(name) + "\n")

user = {"kind": "User", "metadata": {"name": "homelab-ci-plan"},
        "spec": {"type": "WORKLOAD"}}
policy = {"kind": "Policy", "metadata": {"name": "homelab-ci-kubernetes-api-plan-access"},
          "spec": {"rules": [{"name": name} for name in (
              "deny-non-dry-run-writes", "deny-subresources", "read-or-dry-run")]}}
service = {"kind": "Service", "metadata": {"name": "kubernetes-api-ci"},
           "spec": {"isPublic": True, "mode": "KUBERNETES", "port": 6443,
                    "authorization": {"policies": ["homelab-ci-kubernetes-api-access",
                                                    "homelab-ci-kubernetes-api-plan-access"]}}}

if tool == "yq":
    if "-o=json" in args:
        selected = [policy, user, service]
        if os.environ.get("FIXTURE_BAD_SELECTION") == "true":
            selected.append({"kind": "User", "metadata": {"name": "unrelated"}})
        print(json.dumps(selected))
    else:
        assert "homelab-ci-plan" in args[1]
        assert "homelab-ci-kubernetes-api-plan-access" in args[1]
        assert "kubernetes-api-ci" in args[1]
        print("kind: Policy\nmetadata:\n  name: fixture")
elif tool == "git":
    if args == ["status", "--porcelain"]:
        print("dirty" if os.environ.get("FIXTURE_DIRTY") == "true" else "", end="")
    elif args == ["rev-parse", "HEAD"]:
        print("a" * 40)
    else:
        sys.exit(90)
elif tool == "gh":
    if args == ["auth", "status"]:
        pass
    elif args == ["api", "repos/Stuhlmuller/homelab/git/ref/heads/main", "--jq", ".object.sha"]:
        event("main.check")
        checks = sum(json.loads(line) == "main.check" for line in events.read_text().splitlines())
        print(("b" if checks >= int(os.environ.get("FIXTURE_STALE_AT", "100")) else "a") * 40)
    else:
        sys.exit(91)
elif tool == "octeliumctl":
    if args[0] == "get":
        kind, name = args[1:3]
        event("get." + kind)
        applies = sum(json.loads(line) == "apply" for line in events.read_text().splitlines())
        if kind == "service":
            assert name == "kubernetes-api-ci.default"
            current = json.loads(json.dumps(service))
            if applies == 0:
                current["spec"]["authorization"]["policies"].pop()
            if os.environ.get("FIXTURE_SERVICE_DRIFT") == "true":
                current["spec"]["port"] = 443
            print(json.dumps(current))
        elif kind in ("user", "policy"):
            if applies == 0 and os.environ.get("FIXTURE_EXISTING_PLAN") != "true":
                if os.environ.get("FIXTURE_MISSING_EXIT_ZERO") == "true":
                    print("Could not get User: NotFound" if kind == "user"
                          else "Could not get Policy: NotFound")
                    sys.exit(0)
                print("not found", file=sys.stderr)
                sys.exit(1)
            current = user if kind == "user" else policy
            if applies == 0 and os.environ.get("FIXTURE_EXISTING_DRIFT") == "true":
                current = json.loads(json.dumps(current))
                current["spec"]["type" if kind == "user" else "rules"] = "unexpected"
            print(json.dumps(current))
        else:
            sys.exit(92)
    elif args[0] == "apply":
        assert args[1:9] == ["--domain", "stinkyboi.com", "--include", "User",
                             "--include", "Policy", "--include", "Service"]
        event("apply")
        applies = sum(json.loads(line) == "apply" for line in events.read_text().splitlines())
        if applies == 2:
            print("No applied changes in Cluster Core resources")
        else:
            print("Applied selected resources")
    else:
        sys.exit(93)
else:
    sys.exit(94)
'''


class PlanCatalogActivationTest(unittest.TestCase):
    def run_script(self, *args: str, **flags: str):
        with tempfile.TemporaryDirectory(prefix="octelium-plan-catalog-test-") as temp:
            root = Path(temp)
            binaries = root / "bin"
            binaries.mkdir()
            for name in ("git", "gh", "yq", "octeliumctl"):
                stub = binaries / name
                stub.write_text(f"#!{sys.executable}\n" + STUB)
                stub.chmod(0o700)
            environment = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}",
                           "FIXTURE_ROOT": str(root), **flags}
            result = subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, env=environment,
                                    capture_output=True, text=True, timeout=10)
            events = root / "events.jsonl"
            calls = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
            return result, calls

    def test_preview_selects_only_three_resources_without_live_access(self):
        result, calls = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Would apply the plan User, Policy", result.stdout)
        self.assertEqual(calls, [])

    def test_exact_main_check_precedes_both_writes_and_second_apply_is_empty(self):
        result, calls = self.run_script("--execute")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.count("apply"), 2)
        self.assertEqual(calls.count("main.check"), 3)
        self.assertLess(calls.index("main.check"), calls.index("apply"))
        self.assertIn("match the reviewed catalog", result.stdout)

    def test_stale_main_blocks_each_write(self):
        for stale_at, writes in ((2, 0), (3, 1)):
            with self.subTest(stale_at=stale_at):
                result, calls = self.run_script("--execute", FIXTURE_STALE_AT=str(stale_at))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls.count("apply"), writes)
                self.assertIn("exact current main", result.stderr)

    def test_unrelated_service_or_identity_drift_blocks_activation(self):
        for flags in ({"FIXTURE_SERVICE_DRIFT": "true"},
                      {"FIXTURE_EXISTING_PLAN": "true", "FIXTURE_EXISTING_DRIFT": "true"}):
            with self.subTest(flags=flags):
                result, calls = self.run_script("--execute", **flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls.count("apply"), 0)

    def test_missing_resource_reported_with_zero_exit_is_classified(self):
        result, calls = self.run_script("--execute", FIXTURE_MISSING_EXIT_ZERO="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.count("apply"), 2)

    def test_unexpected_catalog_resource_and_dirty_checkout_block_activation(self):
        for flags in ({"FIXTURE_BAD_SELECTION": "true"}, {"FIXTURE_DIRTY": "true"}):
            with self.subTest(flags=flags):
                result, calls = self.run_script("--execute", **flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls.count("apply"), 0)


if __name__ == "__main__":
    unittest.main()
