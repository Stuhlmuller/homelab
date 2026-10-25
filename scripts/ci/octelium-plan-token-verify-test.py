#!/usr/bin/env python3
"""Exercise the new Octelium plan token verifier without live requests."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/octelium-plan-token-verify.sh"
TOKEN = "SYNTHETIC_PLAN_TOKEN_DO_NOT_USE_FOR_AUTHENTICATION_1234567890"

FAKE_CURL = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
token = os.environ["TEST_TOKEN"]
assert args[:3] == ["-q", "--config", "-"]
assert sys.stdin.read() == f'header = "Authorization: Bearer {token}"\n'
assert all(token not in arg for arg in args)
assert args[args.index("--proto") + 1] == "=https"
method = args[args.index("--request") + 1]
url = args[-1]
assert url.startswith("https://kubernetes-api-ci.stinkyboi.com/api/v1/namespaces/default")
body_file = Path(args[args.index("--output") + 1])
patch = args[args.index("--data-binary") + 1] if "--data-binary" in args else None
with (Path(os.environ["TEST_WORK"]) / "calls.jsonl").open("a") as out:
    out.write(json.dumps({"method": method, "url": url, "patch": patch}) + "\n")

if url.endswith("/namespaces/default"):
    code = 403 if os.environ.get("TEST_READ_DENIED") else 200
    body = {"kind": "Namespace", "apiVersion": "v1", "metadata": {"name": "default"}}
elif "/configmaps/" in url:
    assert method == "PATCH"
    assert json.loads(patch) == [{"op": "test", "path": "/metadata/uid", "value": None}]
    name = url.split("/configmaps/", 1)[1].split("?", 1)[0]
    if url.endswith("?dryRun=All"):
        code = 403 if os.environ.get("TEST_DRY_RUN_DENIED") else 404
        body = ({"message": "not a Kubernetes response"}
                if os.environ.get("TEST_PROXY_404") else
                {"kind": "Status", "apiVersion": "v1", "status": "Failure",
                 "reason": "NotFound", "code": 404,
                 "details": {"name": name, "kind": "configmaps"}})
    else:
        code = 200 if os.environ.get("TEST_REAL_WRITE_ALLOWED") else 403
        body = {"kind": "Status"}
elif url.endswith("/log"):
    assert method == "GET"
    code = 404 if os.environ.get("TEST_SUBRESOURCE_ALLOWED") else 403
    body = {"kind": "Status"}
else:
    sys.exit(91)
body_file.write_text(json.dumps(body))
print(code, end="")
'''

FAKE_HELPER_TOOL = r'''
import json
import os
from pathlib import Path
import sys

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
events = Path(os.environ["TEST_WORK"]) / "helper-events.jsonl"

def event(value):
    with events.open("a") as out:
        out.write(json.dumps(value) + "\n")

if tool == "gh":
    if args == ["auth", "status"]:
        pass
    elif args[:2] == ["secret", "set"]:
        sys.stdin.read()
        event("gh.secret." + args[2])
    elif args[:3] == ["api", "--method", "DELETE"]:
        event("gh.preflight-delete")
    else:
        sys.exit(91)
elif tool == "octeliumctl":
    if args[:2] == ["get", "user"]:
        print(json.dumps({"metadata": {"name": "homelab-ci-plan"},
                          "spec": {"type": "WORKLOAD"}}))
    elif args[:2] == ["get", "creds"]:
        print('{"items":[]}')
    elif args[:2] == ["get", "sessions"]:
        print("No Sessions found")
    elif args[:2] == ["create", "cred"]:
        event("octelium.create")
        print(json.dumps({"token": os.environ["TEST_TOKEN"]}))
    else:
        sys.exit(92)
else:
    sys.exit(93)
'''


class PlanTokenVerifierTest(unittest.TestCase):
    def run_verifier(self, token=TOKEN, **flags):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake = root / "curl"
            fake.write_text(f"#!{sys.executable}\n" + FAKE_CURL)
            fake.chmod(0o700)
            environment = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                           "TEST_TOKEN": TOKEN, "TEST_WORK": str(root), **flags}
            result = subprocess.run(["bash", str(SCRIPT)], input=token, text=True,
                                    cwd=ROOT, env=environment, capture_output=True, timeout=10)
            events = root / "calls.jsonl"
            calls = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
            return result, calls

    def test_safe_probes_prove_allowed_and_denied_paths(self):
        result, calls = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call["method"] for call in calls], ["GET", "PATCH", "PATCH", "GET"])
        self.assertTrue(calls[1]["url"].endswith("?dryRun=All"))
        self.assertEqual(calls[1]["patch"], calls[2]["patch"])
        self.assertEqual(json.loads(calls[2]["patch"]),
                         [{"op": "test", "path": "/metadata/uid", "value": None}])
        self.assertTrue(calls[3]["url"].endswith("/log"))
        self.assertNotIn(TOKEN, result.stdout + result.stderr + json.dumps(calls))

    def test_dry_run_must_reach_kubernetes(self):
        for flags in ({"TEST_DRY_RUN_DENIED": "1"}, {"TEST_PROXY_404": "1"}):
            with self.subTest(flags=flags):
                result, calls = self.run_verifier(**flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("dry-run check failed", result.stderr)
                self.assertEqual(len(calls), 2)

    def test_real_write_must_be_denied(self):
        result, calls = self.run_verifier(TEST_REAL_WRITE_ALLOWED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("live-write-denial check failed", result.stderr)
        self.assertEqual(len(calls), 3)

    def test_subresource_must_be_denied(self):
        result, calls = self.run_verifier(TEST_SUBRESOURCE_ALLOWED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("subresource-denial check failed", result.stderr)
        self.assertEqual(len(calls), 4)

    def test_read_must_succeed(self):
        result, calls = self.run_verifier(TEST_READ_DENIED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("read check failed", result.stderr)
        self.assertEqual(len(calls), 1)

    def test_invalid_token_never_reaches_curl(self):
        result, calls = self.run_verifier(token=TOKEN + '\nheader = "Injected: true"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid plan token format", result.stderr)
        self.assertEqual(calls, [])

    def test_failed_verification_cannot_publish_plan_secret(self):
        helper = ROOT / "scripts/octelium-ci-credential.sh"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, source in (("curl", FAKE_CURL), ("gh", FAKE_HELPER_TOOL),
                                 ("octeliumctl", FAKE_HELPER_TOOL)):
                fake = root / name
                fake.write_text(f"#!{sys.executable}\n" + source)
                fake.chmod(0o700)
            environment = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                           "TEST_TOKEN": TOKEN, "TEST_WORK": str(root),
                           "TEST_READ_DENIED": "1"}
            result = subprocess.run(
                ["bash", str(helper), "--skip-catalog", "--credential-name", "homelab-ci-plan",
                 "--user", "homelab-ci-plan", "--policy", "homelab-ci-kubernetes-api-plan-access",
                 "--secret-name", "OCTELIUM_CI_PLAN_AUTH_TOKEN", "--env", "homelab-plan"],
                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=10)
            events = [json.loads(line) for line in
                      (root / "helper-events.jsonl").read_text().splitlines()]
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("plan token read check failed", result.stderr)
            self.assertIn("octelium.create", events)
            self.assertTrue(any(event.startswith("gh.secret.OCTELIUM_CI_PREFLIGHT_")
                                for event in events))
            self.assertNotIn("gh.secret.OCTELIUM_CI_PLAN_AUTH_TOKEN", events)
            self.assertNotIn(TOKEN, result.stdout + result.stderr + json.dumps(events))


if __name__ == "__main__":
    unittest.main()
