#!/usr/bin/env python3
"""Offline safety tests for the fixed protected Talos credential publisher."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/platform-maintenance-credentials.sh"
MAIN_SHA = "a" * 40


FAKE_CLI = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
state_path = Path(os.environ["TEST_STATE"])
state = json.loads(state_path.read_text())

def save():
    state_path.write_text(json.dumps(state))

def record(action):
    state.setdefault("actions", []).append(action)
    save()

if name == "git":
    if args == ["rev-parse", "--show-toplevel"]:
        print(os.environ["TEST_ROOT"])
    elif args == ["rev-parse", "HEAD"]:
        print(state.get("head", "a" * 40))
    elif args == ["status", "--porcelain"]:
        print(state.get("status", ""), end="")
    else:
        sys.exit(2)
elif name == "gh":
    if args[:1] == ["api"]:
        print("a" * 40)
    elif args[:2] == ["auth", "status"]:
        pass
    elif args[:2] == ["secret", "list"]:
        print(json.dumps([{"name": n} for n in state.get("secrets", [])]))
    elif args[:2] == ["secret", "set"]:
        value = sys.stdin.buffer.read()
        if len(value) < 40:
            sys.exit(1)
        state.setdefault("secrets", []).append(args[2])
        record({"secret": args[2], "length": len(value)})
    else:
        sys.exit(2)
elif name == "octeliumctl":
    if args[:2] == ["get", "user"]:
        print(json.dumps({"metadata": {"name": "homelab-ci"}, "spec": {"type": "WORKLOAD"}}))
    elif args[:2] == ["get", "policy"]:
        matches = [
            'ctx.user.metadata.name == "homelab-ci"',
            'ctx.user.spec.type == "WORKLOAD"',
            'ctx.session.status.type == "CLIENT"',
            'ctx.service.metadata.name == "talos-api-ci.homelab"',
            'ctx.service.spec.mode == "TCP"',
        ]
        if state.get("policy_drift"):
            matches[-1] = 'ctx.service.spec.mode == "WEB"'
        print(json.dumps({"metadata": {"name": "homelab-platform-talos-ci-access"},
            "spec": {"rules": [{"name": "protected-maintenance-client", "effect": "ALLOW",
                "condition": {"all": {"of": [{"match": m} for m in matches]}}}]}}))
    elif args[:2] == ["get", "service"]:
        print(json.dumps({"metadata": {"name": "talos-api-ci.homelab"},
            "spec": {"isPublic": False, "mode": "TCP", "port": 50000,
                "authorization": {"policies": ["homelab-platform-talos-ci-access"]},
                "config": {"upstream": {"url": "tcp://10.1.0.199:50000"}}}}))
    elif args[:2] == ["get", "creds"]:
        items = []
        if state.get("existing_credential"):
            items.append({"metadata": {"name": "homelab-platform-talos-ci"},
                "spec": {"user": "homelab-ci",
                    "type": "ACCESS_TOKEN" if state.get("wrong_credential_type") else "AUTH_TOKEN",
                    "sessionType": "CLIENT",
                    "authorization": {"policies": ["homelab-platform-talos-ci-access"]}}})
        print(json.dumps({"items": items}))
    elif args[:2] == ["create", "cred"]:
        record({"octelium_create": args})
        print(json.dumps({"authenticationToken": {"authenticationToken": "x" * 64}}))
    else:
        sys.exit(2)
elif name == "talosctl":
    config = args[args.index("--talosconfig") + 1]
    if "config" in args and "info" in args:
        generated = config.endswith("/talosconfig")
        print(json.dumps({"roles": ["os:admin"],
            "endpoints": ["talos-api.homelab.local.stinkyboi.com"] if generated else ["10.1.0.199"],
            "nodes": ["10.1.0.199"], "certNotAfter": "2026-11-19"}))
    elif "config" in args and "new" in args:
        if state.get("issuance_failure"):
            sys.exit(1)
        output = Path(args[args.index("new") + 1])
        cert = "OWNER_CERT" if state.get("same_identity") else "NEW_CERT"
        key = "OWNER_KEY" if state.get("same_identity") else "NEW_KEY"
        output.write_text(json.dumps({"context": "homelab",
            "contexts": {"homelab": {"crt": cert, "key": key}}}))
        record({"talos_new": args})
    elif "config" in args and ("endpoint" in args or "node" in args):
        pass
    elif "version" in args:
        if state.get("client_test_failure") and config.endswith("/talosconfig"):
            sys.exit(1)
        record({"talos_version": args})
        print("Client: Talos v1.11.6\nServer: Talos v1.11.6")
    else:
        sys.exit(2)
else:
    sys.exit(2)
'''


class CredentialPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.bin = self.path / "bin"
        self.bin.mkdir()
        fake = self.bin / "fake-cli"
        fake.write_text(textwrap.dedent(FAKE_CLI))
        fake.chmod(0o755)
        for command in ("git", "gh", "octeliumctl", "talosctl"):
            (self.bin / command).symlink_to(fake)
        self.state_path = self.path / "state.json"
        self.state_path.write_text("{}")
        self.operator = self.path / "operator.json"
        self.operator.write_text(json.dumps({"context": "homelab",
            "contexts": {"homelab": {"crt": "OWNER_CERT", "key": "OWNER_KEY"}}}))

    def state(self):
        return json.loads(self.state_path.read_text())

    def run_mode(self, *args):
        environment = os.environ.copy()
        environment.update({"PATH": f"{self.bin}:{environment['PATH']}",
            "TEST_STATE": str(self.state_path), "TEST_ROOT": str(ROOT)})
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT,
            env=environment, capture_output=True, text=True, timeout=20)

    def test_client_token_is_fixed_and_bound_to_client_policy(self):
        result = self.run_mode("octelium-client")
        self.assertEqual(result.returncode, 0, result.stderr)
        actions = self.state()["actions"]
        create = next(item["octelium_create"] for item in actions if "octelium_create" in item)
        self.assertEqual(create[create.index("--type") + 1], "auth-token")
        self.assertEqual(create[create.index("--session-type") + 1], "client")
        self.assertEqual(create[create.index("--policy") + 1], "homelab-platform-talos-ci-access")
        self.assertEqual([item["secret"] for item in actions if "secret" in item],
            ["OCE_OCTELIUM_CLIENT_AUTH_TOKEN"])
        self.assertNotIn("x" * 64, result.stdout + result.stderr)

    def test_catalog_drift_stops_before_credential_creation(self):
        self.state_path.write_text(json.dumps({"policy_drift": True}))
        result = self.run_mode("octelium-client")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state().get("actions", []), [])

    def test_existing_authentication_credential_rotates_without_session_reset(self):
        self.state_path.write_text(json.dumps({"existing_credential": True}))
        result = self.run_mode("octelium-client")
        self.assertEqual(result.returncode, 0, result.stderr)
        create = next(item["octelium_create"] for item in self.state()["actions"]
            if "octelium_create" in item)
        self.assertIn("--rotate", create)
        self.assertFalse(any("delete" in str(item) for item in self.state()["actions"]))

    def test_existing_bearer_credential_is_never_rotated_as_client_auth(self):
        self.state_path.write_text(json.dumps({"existing_credential": True,
            "wrong_credential_type": True}))
        result = self.run_mode("octelium-client")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state().get("actions", []), [])

    def test_talos_issues_distinct_client_and_checks_it_before_publication(self):
        result = self.run_mode("talos-client", "--operator-talosconfig", str(self.operator))
        self.assertEqual(result.returncode, 0, result.stderr)
        actions = self.state()["actions"]
        self.assertEqual([item["secret"] for item in actions if "secret" in item],
            ["OCE_TALOSCONFIG_B64"])
        self.assertEqual(len([item for item in actions if "talos_version" in item]), 2)
        self.assertLess(next(i for i, item in enumerate(actions) if "talos_new" in item),
            next(i for i, item in enumerate(actions) if "secret" in item))
        self.assertNotIn("OWNER_CERT", result.stdout + result.stderr)

    def test_talos_issuance_failure_never_publishes_owner_identity(self):
        self.state_path.write_text(json.dumps({"issuance_failure": True}))
        result = self.run_mode("talos-client", "--operator-talosconfig", str(self.operator))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("secret" in item for item in self.state().get("actions", [])))

    def test_reused_talos_identity_is_never_published(self):
        self.state_path.write_text(json.dumps({"same_identity": True}))
        result = self.run_mode("talos-client", "--operator-talosconfig", str(self.operator))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("secret" in item for item in self.state().get("actions", [])))

    def test_unusable_new_talos_client_is_never_published(self):
        self.state_path.write_text(json.dumps({"client_test_failure": True}))
        result = self.run_mode("talos-client", "--operator-talosconfig", str(self.operator))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("secret" in item for item in self.state().get("actions", [])))

    def test_stale_main_stops_before_external_mutation(self):
        self.state_path.write_text(json.dumps({"head": "b" * 40}))
        result = self.run_mode("octelium-client")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state().get("actions", []), [])


if __name__ == "__main__":
    unittest.main()
