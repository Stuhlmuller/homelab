#!/usr/bin/env python3
"""Check the fixed Talos mirror rollout without credentials or live mutations."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
import urllib.parse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rollout", ROOT / "scripts/talos-harbor-mirrors.py")
rollout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollout)
SHA = "a" * 40
PRIOR_SHA = "b" * 40
MANIFEST = '{"schemaVersion":2}'
DIGEST = hashlib.sha256(MANIFEST.encode()).hexdigest()
MIRRORS = {"docker.io": {"endpoints": ["https://harbor.stinkyboi.com/v2/mirror/docker.io"],
                         "overridePath": True, "skipFallback": True}}
ORIGINAL = [{"version": "v1alpha1", "machine": {"type": "worker"},
             "cluster": {"secret": "PrivateSecret-do-not-log", "controlPlane": {"endpoint": "https://10.1.0.199:6443"}}},
            {"apiVersion": "v1alpha1", "kind": "UserVolumeConfig", "name": "keep-this-volume"}]


class RolloutTest(unittest.TestCase):
    def test_dry_run_execution_and_fail_closed_gates(self):
        for scenario in ("dry", "apply", "rollback", "unready", "wrong-client", "dirty", "workflow",
                         "digest", "scope", "multidoc", "race", "reboot", "readback", "rollback-reboot", "custom-config", "missing-config", "pull-failure", "token-injection",
                         "prior-success", "later-page-success", "bundle-changed", "non-ancestor", "missing-history", "missing-blob",
                         "wrong-branch", "wrong-event", "wrong-status", "wrong-conclusion", "short-sha"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "scripts/config").mkdir(parents=True)
                (root / ".talos/patches").mkdir(parents=True)
                talosconfig = root / ("private-talosconfig" if scenario == "custom-config" else ".talos/talosconfig")
                if scenario != "missing-config":
                    talosconfig.write_text("private test fixture")
                config_argument = talosconfig if scenario == "custom-config" else None
                (root / "scripts/config/harbor-images.json").write_text(json.dumps(
                    {"images": [{"source": f"docker.io/library/alpine:3.22@sha256:{DIGEST}"}]}))
                wanted = copy.deepcopy(MIRRORS)
                if scenario.startswith("rollback"):
                    wanted["docker.io"].update(endpoints=["https://registry-1.docker.io/v2"], skipFallback=False)
                for name in ("harbor-mirrors.yaml", "harbor-mirrors-rollback.yaml"):
                    (root / ".talos/patches" / name).write_text(json.dumps({"machine": {"registries": {"mirrors": wanted}}}))
                current = copy.deepcopy(ORIGINAL)
                calls, captures = [], []
                applied = False

                def run(*command, binary=False):
                    nonlocal current, applied
                    calls.append(command)
                    if command[0] == "talosctl" and any(action in command for action in ("get", "read", "apply-config", "image")):
                        self.assertIn("--talosconfig", command)
                        self.assertEqual(command[command.index("--talosconfig") + 1], str(talosconfig.resolve()))
                    if command[:2] == ("git", "status"):
                        return " M unsafe\n" if scenario == "dirty" else ""
                    if command[:2] in (("git", "rev-parse"), ("git", "ls-remote")):
                        return SHA + "\n"
                    if command[:2] == ("git", "merge-base"):
                        self.assertEqual(command[2], "--is-ancestor")
                        self.assertEqual(command[-1], SHA)
                        if scenario in ("non-ancestor", "missing-history") or command[-2] == "c" * 40:
                            raise subprocess.CalledProcessError(1 if scenario == "non-ancestor" else 128, command)
                        return ""
                    if command[:2] == ("git", "show"):
                        self.assertTrue(binary)
                        revision, path = command[2].split(":", 1)
                        if revision == PRIOR_SHA and path == "flake.lock":
                            if scenario == "missing-blob":
                                raise subprocess.CalledProcessError(128, command)
                            if scenario == "bundle-changed":
                                return b"changed lockfile"
                        return path.encode()
                    if command[0] == "gh":
                        self.assertEqual(command[:4], ("gh", "api", "--paginate", "--slurp"))
                        self.assertEqual(command[-1], "repos/Stuhlmuller/homelab/actions/workflows/harbor-mirror.yml/runs"
                                         "?branch=main&event=workflow_dispatch&status=success&per_page=100")
                        item = {"head_sha": PRIOR_SHA if scenario in ("prior-success", "later-page-success", "bundle-changed", "non-ancestor", "missing-history", "missing-blob") else SHA,
                                "head_branch": "feature" if scenario == "wrong-branch" else "main",
                                "event": "push" if scenario == "wrong-event" else "workflow_dispatch",
                                "status": "in_progress" if scenario == "wrong-status" else "completed",
                                "conclusion": "failure" if scenario == "wrong-conclusion" else "success"}
                        if scenario == "short-sha":
                            item["head_sha"] = SHA[:7]
                        if scenario == "later-page-success":
                            return json.dumps([{"workflow_runs": [{**item, "head_sha": "c" * 40}] * 100},
                                               {"workflow_runs": [item]}])
                        return json.dumps([{"workflow_runs": [] if scenario == "workflow" else [item]}])
                    if command[0] == "curl":
                        self.assertEqual(command[1], "--disable")
                        self.assertIn("--fail", command)
                        self.assertEqual(command[command.index("--max-time") + 1], "30")
                        self.assertEqual(command[command.index("--doh-url") + 1], "https://1.1.1.1/dns-query")
                        self.assertNotIn("--insecure", command)
                        self.assertNotIn("--location", command)
                        self.assertNotIn("test.anonymous-token", " ".join(command))
                        if "/service/token?" in command[-1]:
                            self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(command[-1]).query),
                                             {"service": ["harbor-registry"], "scope": ["repository:mirror/docker.io/library/alpine:pull"]})
                            return json.dumps({"token": "unsafe\r\nInjected: header" if scenario == "token-injection" else "test.anonymous-token"})
                        headers = Path(command[command.index("--header") + 1].removeprefix("@"))
                        self.assertEqual(headers.stat().st_mode & 0o777, 0o600)
                        self.assertEqual(headers.parent.stat().st_mode & 0o777, 0o700)
                        self.assertIn("Authorization: Bearer test.anonymous-token\n", headers.read_text())
                        self.assertIn("application/vnd.oci.image.index.v1+json", headers.read_text())
                        self.assertIn("application/vnd.docker.distribution.manifest.list.v2+json", headers.read_text())
                        self.assertIn(command[-1], (f"https://harbor.stinkyboi.com/v2/mirror/docker.io/library/alpine/manifests/{DIGEST}",
                                                   "https://harbor.stinkyboi.com/v2/mirror/docker.io/library/alpine/manifests/3.22"))
                        self.assertTrue(binary)
                        return b"wrong digest" if scenario == "digest" else MANIFEST.encode()
                    if command[:2] == ("kubectl", "get"):
                        return json.dumps({"metadata": {"name": "zimaboard-2"}, "status": {
                            "addresses": [{"type": "InternalIP", "address": "10.1.0.202"}],
                            "conditions": [{"type": "Ready", "status": "False" if scenario == "unready" else "True"}],
                            "nodeInfo": {"bootID": "different" if applied and scenario == "reboot" else "stable"}}})
                    if command[:2] == ("kubectl", "wait"):
                        return ""
                    if command[0] == "yq":
                        value = json.loads(Path(command[-1]).read_text())
                        return json.dumps(value if isinstance(value, list) else [value])
                    if command == ("talosctl", "version", "--client", "--short"):
                        return "Client:\nTalos v1.13.0\n" if scenario == "wrong-client" else "Client:\nTalos v1.11.3\n"
                    if "read" in command:
                        return "87654321-0000-0000-0000-000000000000" if applied and scenario == "rollback-reboot" else "12345678-0000-0000-0000-000000000000"
                    if "persistent" in command:
                        captures.append(command)
                        if scenario == "race" and len(captures) == 2:
                            current[0]["machine"]["unrelated"] = True
                        return json.dumps({"metadata": {"id": "persistent"}, "spec": json.dumps(current)})
                    if command[:3] == ("talosctl", "machineconfig", "patch"):
                        path = Path(command[3])
                        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                        value = json.loads(path.read_text())
                        if command[5] != "[]":
                            operations = json.loads(command[5])
                            self.assertEqual(operations[-1], {"op": "add", "path": "/machine/registries/mirrors", "value": wanted})
                            value[0]["machine"].setdefault("registries", {})["mirrors"] = operations[-1]["value"]
                            if scenario == "scope":
                                value[0]["cluster"]["secret"] = "changed"
                            if scenario == "multidoc":
                                value.pop()
                        Path(command[-1]).write_text(json.dumps(value))
                        return ""
                    if command[:2] == ("talosctl", "validate"):
                        self.assertEqual(command[-3:], ("--mode", "metal", "--strict"))
                        return ""
                    if "image" in command:
                        self.assertEqual(command[-5:], ("image", "pull", "--namespace", "system", "registry.k8s.io/pause:3.10"))
                        self.assertTrue(applied)
                        self.assertEqual(len(captures), 3, "Pull follows persistent configuration readback")
                        self.assertEqual(calls[-2][:2], ("kubectl", "get"), "Pull follows node health check")
                        if scenario == "pull-failure":
                            raise RuntimeError("Native image pull failed")
                        return ""
                    if "apply-config" in command:
                        self.assertIn("no-reboot", command)
                        applied = True
                        if scenario != "readback":
                            current = json.loads(Path(command[-1]).read_text())
                        return ""
                    raise AssertionError(f"Unexpected command: {command[0]}")

                output = io.StringIO()
                with patch.object(rollout, "ROOT", root), patch.object(rollout, "run", run), \
                        contextlib.redirect_stdout(output):
                    if scenario in ("dry", "apply", "rollback", "custom-config", "prior-success", "later-page-success"):
                        rollout.reconcile("10.1.0.202", scenario != "dry", SHA, scenario.startswith("rollback"), config_argument)
                    else:
                        with self.assertRaises(RuntimeError):
                            rollout.reconcile("10.1.0.202", True, SHA, scenario.startswith("rollback"), config_argument)
                self.assertNotIn("PrivateSecret", output.getvalue())
                if scenario in ("prior-success", "later-page-success"):
                    self.assertEqual({call[2].split(":", 1)[1] for call in calls if call[:2] == ("git", "show")},
                                     {"scripts/config/harbor-images.json", ".github/workflows/harbor-mirror.yml",
                                      "scripts/ci/harbor-publish.sh", "scripts/ci/install-kubeconfig.sh", "flake.nix", "flake.lock"})
                if scenario in ("bundle-changed", "non-ancestor", "missing-history", "missing-blob", "wrong-branch",
                                "wrong-event", "wrong-status", "wrong-conclusion", "short-sha"):
                    self.assertFalse(any(call[0] == "curl" for call in calls))
                if scenario == "missing-config":
                    self.assertEqual(calls, [])
                self.assertEqual(applied, scenario in ("apply", "rollback", "reboot", "readback", "rollback-reboot", "custom-config", "pull-failure", "prior-success", "later-page-success"))
                self.assertEqual(any("image" in call for call in calls), scenario in ("apply", "custom-config", "pull-failure", "prior-success", "later-page-success"))
                if scenario in ("dry", "rollback", "rollback-reboot"):
                    self.assertFalse(any(call[0] in ("gh", "curl") for call in calls))
                if scenario.startswith("rollback"):
                    self.assertFalse(any(call[0] == "kubectl" for call in calls))
                self.assertFalse(any("patch" in call and "machineconfig" not in call for call in calls))
                for call in calls:
                    if call[0] == "curl" and "--header" in call:
                        self.assertFalse(Path(call[call.index("--header") + 1].removeprefix("@")).exists(),
                                         "Private token header must be removed")
                    if call[:3] == ("talosctl", "machineconfig", "patch"):
                        self.assertFalse(Path(call[-1]).exists(), "Private temporary config must be removed")


if __name__ == "__main__":
    unittest.main()
