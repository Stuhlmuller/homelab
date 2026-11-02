#!/usr/bin/env python3
"""Exercise kubeconfig parsing with real kubectl and isolated API doubles."""

import base64
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/octelium-ci-kubeconfig-secret.sh"
NAME = "homelab-ci-kubeconfig-20261101t120000z"


class KubeconfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="kubeconfig-fixture-")
        cls.directory = Path(cls.temporary.name)
        cls.kubectl = shutil.which("kubectl")
        if not cls.kubectl:
            raise RuntimeError("kubectl is required")
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=isolated-fixture", "-keyout", str(cls.directory / "key"),
            "-out", str(cls.directory / "ca"),
        ], check=True, capture_output=True)
        cls.ca = base64.b64encode((cls.directory / "ca").read_bytes()).decode()
        cls.key = base64.b64encode((cls.directory / "key").read_bytes()).decode()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(dir=self.directory)
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name)
        self.config = {
            "apiVersion": "v1", "kind": "Config", "current-context": "selected",
            "clusters": [{"name": "selected", "cluster": {
                "server": "https://10.1.0.199:6443", "certificate-authority-data": self.ca}}],
            "contexts": [{"name": "selected", "context": {"cluster": "selected", "user": "selected"}}],
            "users": [{"name": "selected", "user": {"token": "test-token"}}],
        }
        mock = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
state = json.loads((root / "state.json").read_text())
if pathlib.Path(sys.argv[0]).name == "kubectl" and "config" in args:
    sys.exit(subprocess.call([state["real_kubectl"], *args]))
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps([pathlib.Path(sys.argv[0]).name, *args]) + "\\n")
if pathlib.Path(sys.argv[0]).name == "kubectl":
    assert not any(os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"))
    if "whoami" in args:
        print("private-diagnostic", file=sys.stderr)
        sys.exit(state.get("probe_exit", 0))
    request = json.load(sys.stdin)
    assert request["apiVersion"] == "authorization.k8s.io/v1"
    assert request["kind"] == "SelfSubjectAccessReview"
    spec = request["spec"]
    assert spec in ({"resourceAttributes": {"group": "*", "resource": "*", "verb": "*", "namespace": ""}}, {"nonResourceAttributes": {"path": "/*", "verb": "*"}})
    kind = next(iter(spec))
    print(json.dumps({"status": {"allowed": state.get(kind, True)}}))
elif args[:2] == ["create", "secret"]:
    assert "--file" in args
    source = pathlib.Path(args[args.index("--file") + 1])
    assert source.stat().st_mode & 0o777 == 0o600
    (root / "captured.json").write_bytes(source.read_bytes())
    print("private-diagnostic", file=sys.stderr)
    sys.exit(state.get("create_exit", 0))
elif args[:2] == ["get", "secret"]:
    mode = state.get("lookup", "exists")
    if mode == "exists":
        print(json.dumps({"metadata": {"name": args[2]}}))
    elif mode == "absent":
        print("gRPC error NotFound: Secret not found", file=sys.stderr)
        sys.exit(1)
    else:
        print("private-diagnostic", file=sys.stderr)
        sys.exit(1)
else:
    raise AssertionError(args)
'''
        for executable in ("kubectl", "octeliumctl"):
            target = self.path / executable
            target.write_text(mock)
            target.chmod(0o700)

    def run_script(self, config=None, *, state=None, extra=()):
        (self.path / "input.json").write_text(json.dumps(config or self.config))
        (self.path / "state.json").write_text(json.dumps({"real_kubectl": self.kubectl, **(state or {})}))
        (self.path / "calls.jsonl").write_text("")
        result = subprocess.run([
            "bash", str(SCRIPT), "--kubeconfig", str(self.path / "input.json"),
            "--secret-name", NAME, *extra,
        ], capture_output=True, text=True,
            env={**os.environ, "PATH": str(self.path) + os.pathsep + os.environ["PATH"]}, timeout=20)
        self.assertNotIn("private-diagnostic", result.stdout + result.stderr)
        calls = [json.loads(line) for line in (self.path / "calls.jsonl").read_text().splitlines()]
        return result, calls

    def test_valid_token_is_minified_and_never_updates_or_deletes(self):
        config = copy.deepcopy(self.config)
        for key in ("clusters", "contexts", "users"):
            other = copy.deepcopy(config[key][0])
            other["name"] = "ignored"
            config[key].append(other)
        result, calls = self.run_script(config)
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = json.loads((self.path / "captured.json").read_text())
        self.assertEqual(saved, self.config)
        self.assertEqual([c[1:3] for c in calls if c[0] == "octeliumctl"], [["create", "secret"]])

    def test_embedded_certificate_and_key(self):
        self.config["users"][0]["user"] = {"client-certificate-data": self.ca, "client-key-data": self.key}
        result, _ = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_untrusted_configuration_stops_before_any_api(self):
        cluster_changes = [
            {"server": "https://10.1.0.216:6443"}, {"insecure-skip-tls-verify": True},
            {"proxy-url": "http://127.0.0.1:9999"}, {"tls-server-name": "elsewhere"},
            {"certificate-authority": "/tmp/ca"}, {"certificate-authority-data": "broken"},
            {"certificate-authority-data": base64.b64encode((self.directory / "ca").read_bytes() * 2).decode()},
        ]
        user_changes = [
            {"exec": {"command": "false", "apiVersion": "client.authentication.k8s.io/v1"}},
            {"auth-provider": {"name": "gcp"}}, {"tokenFile": "/tmp/token"},
            {"client-certificate": "/tmp/cert", "client-key": "/tmp/key"},
            {"token": ""}, {"username": "foo", "password": "bar"},
            {"client-certificate-data": "broken", "client-key-data": "broken"},
        ]
        for changes in cluster_changes + user_changes:
            with self.subTest(changes=list(changes)):
                config = copy.deepcopy(self.config)
                if changes in cluster_changes:
                    config["clusters"][0]["cluster"].update(changes)
                else:
                    config["users"][0]["user"] = changes
                result, calls = self.run_script(config)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_missing_and_ambiguous_contexts(self):
        for context in ("missing", ""):
            config = copy.deepcopy(self.config)
            config["current-context"] = context
            result, calls = self.run_script(config)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])
        config = copy.deepcopy(self.config)
        config["contexts"].append(copy.deepcopy(config["contexts"][0]))
        result, calls = self.run_script(config)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_probe_or_authorization_failure_prevents_secret_write(self):
        for state in ({"probe_exit": 1}, {"resourceAttributes": False}, {"nonResourceAttributes": False}):
            result, calls = self.run_script(state=state)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(c[0] == "octeliumctl" for c in calls))

    def test_create_failure_is_reconciled_without_overwrite(self):
        for lookup, expected in (("exists", "ambiguous"), ("absent", "confirmed absent"), ("unknown", "unknown")):
            result, calls = self.run_script(state={"create_exit": 1, "lookup": lookup})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected, result.stderr)
            self.assertEqual([c[1:3] for c in calls if c[0] == "octeliumctl"], [["create", "secret"], ["get", "secret"]])

    def test_bad_secret_name_and_missing_option_value(self):
        for extra in (("--secret-name", "arbitrary"), ("--context",), ("--secret-name", NAME.upper())):
            result, calls = self.run_script(extra=extra)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
