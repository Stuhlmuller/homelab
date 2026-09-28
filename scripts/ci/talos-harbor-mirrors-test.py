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
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rollout", ROOT / "scripts/talos-harbor-mirrors.py")
rollout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollout)
SHA = "a" * 40
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
                         "digest", "scope", "multidoc", "race", "reboot", "readback", "rollback-reboot"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "scripts/config").mkdir(parents=True)
                (root / ".talos/patches").mkdir(parents=True)
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
                    if command[:2] == ("git", "status"):
                        return " M unsafe\n" if scenario == "dirty" else ""
                    if command[:2] in (("git", "rev-parse"), ("git", "ls-remote")):
                        return SHA + "\n"
                    if command[0] == "gh":
                        return json.dumps([] if scenario == "workflow" else
                                          [{"headSha": SHA, "status": "completed", "conclusion": "success"}])
                    if command[0] == "skopeo":
                        self.assertIn("--no-creds", command)
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
                    if scenario in ("dry", "apply", "rollback"):
                        rollout.reconcile("10.1.0.202", scenario != "dry", SHA, scenario.startswith("rollback"))
                    else:
                        with self.assertRaises(RuntimeError):
                            rollout.reconcile("10.1.0.202", True, SHA, scenario.startswith("rollback"))
                self.assertNotIn("PrivateSecret", output.getvalue())
                self.assertEqual(applied, scenario in ("apply", "rollback", "reboot", "readback", "rollback-reboot"))
                if scenario in ("dry", "rollback", "rollback-reboot"):
                    self.assertFalse(any(call[0] in ("gh", "skopeo") for call in calls))
                if scenario.startswith("rollback"):
                    self.assertFalse(any(call[0] == "kubectl" for call in calls))
                self.assertFalse(any("patch" in call and "machineconfig" not in call for call in calls))
                for call in calls:
                    if call[:3] == ("talosctl", "machineconfig", "patch"):
                        self.assertFalse(Path(call[-1]).exists(), "Private temporary config must be removed")


if __name__ == "__main__":
    unittest.main()
