#!/usr/bin/env python3
"""Exercise canary sequencing and refusal boundaries without live credentials."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("canary", ROOT / "scripts/talos-nri-canary.py")
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
PRIVATE = "Private-canary-secret-never-print"
SHA = "a" * 40
BOOT = "12345678-1234-1234-1234-123456789abc"


class CanaryTests(unittest.TestCase):
    def exercise(self, failure=None, *, execute=True, rollback=False, release=False):
        calls = []
        state = [{"version": "v1alpha1", "machine": {"type": "worker", "files": []},
                  "cluster": {"secret": PRIVATE}}, {"kind": "UserVolumeConfig", "name": "preserve"}]
        if failure == "machine-role":
            state[0]["machine"]["type"] = "controlplane"
        if release:
            state[0]["machine"]["files"] = [{"path": c.nri.NRI_FILE, "disabled": rollback}]
        current_cri = {"version": 3, "disabled": not release or rollback, "unrelated": PRIVATE}
        captures = 0
        applied = False
        restarted = False

        def capture(client, path):
            nonlocal captures
            captures += 1
            value = copy.deepcopy(state)
            if failure == "config-drift" and captures == 2:
                value[1]["name"] = "drift"
            if failure == "apply-readback" and applied:
                value[1]["name"] = "drift"
            path.write_text(json.dumps(value))
            path.chmod(0o600)

        def prepare(source, output, rollback, cli):
            value = json.loads(source.read_text())
            value[0]["machine"]["files"] = [{"path": c.nri.NRI_FILE, "disabled": rollback}]
            output.write_text(json.dumps(value))

        def effective(before, after, rollback):
            wanted = {**before, "disabled": rollback}
            if after != wanted:
                raise ValueError("Private merged configuration withheld")

        def command(*args, **kwargs):
            nonlocal applied, restarted, state, current_cri
            calls.append(args)
            if args[:3] == ("talosctl", "version", "--client"):
                return "Talos v1.13.2" if failure == "cli-version" else "Talos v1.11.3"
            if args[:3] == ("kubectl", "config", "view"):
                return json.dumps({"current-context": "wrong" if failure == "context" else "admin@homelab",
                                   "clusters": [{"cluster": {"server": "https://10.1.0.199:6443"}}]})
            if args[:3] == ("kubectl", "get", "node"):
                return json.dumps({"metadata": {"labels": {"node-role.kubernetes.io/control-plane": ""} if failure == "node-role" else {}}, "status": {"nodeInfo": {"bootID": BOOT}, "addresses": [{"type": "InternalIP", "address": c.NODE}]}})
            if args[:3] == ("kubectl", "get", "nodes"):
                return json.dumps({"items": [{"metadata": {"name": name}, "status": {"conditions": [{"type": "Ready", "status": "False" if failure == "node-ready" else "True"}]}} for name in c.harbor.NODES.values()]})
            if args[:3] == ("kubectl", "get", "pods") and "--field-selector" in args:
                return json.dumps({"items": [{"metadata": {"ownerReferences": [{"kind": "DaemonSet", "name": owner}]}, "status": {"conditions": [{"type": "Ready", "status": "False" if failure == "dataplane" else "True"}]}} for owner in ("kube-flannel", "istio-cni-node", "ztunnel")]})
            if args[:3] in (("kubectl", "get", "pods"), ("kubectl", "get", "daemonsets")):
                blocked = failure == ("engine-pod" if args[2] == "pods" else "engine-daemonset") or (applied and failure == "engine-after-apply")
                return json.dumps({"items": [{"spec": {"containers": [{"image": "harbor.example/kube-network-policies@sha256:fixture"}]}}] if blocked else []})
            if args[:2] == ("kubectl", "drain"):
                self.assertNotIn("--force", args)
                self.assertNotIn("--delete-emptydir-data", args)
                self.assertNotIn("--disable-eviction", args)
                if failure == "drain":
                    raise RuntimeError("PDB refused drain")
                return ""
            if args[:2] == ("kubectl", "uncordon"):
                return ""
            if "apply-config" in args:
                self.assertIn("no-reboot", args)
                state = json.loads(Path(args[-1]).read_text())
                current_cri = {**current_cri, "disabled": rollback}
                if failure == "merged-drift":
                    current_cri["unrelated"] = "drift"
                applied = True
                return ""
            if "restart" in args:
                if failure == "restart":
                    raise RuntimeError("restart failed")
                restarted = True
                return ""
            if "service" in args and "get" in args:
                healthy = (failure != "cri-health" or (rollback and restarted)) and not (restarted and failure == "post-health")
                return json.dumps({"spec": {"running": True, "healthy": healthy, "unknown": False}})
            if "read" in args:
                value = copy.deepcopy(current_cri)
                if failure == "cri-drift" and captures >= 2:
                    value["unrelated"] = "drift"
                return json.dumps(value)
            raise AssertionError(args)

        def main(sha):
            calls.append(("verify-main", sha))
            if failure == "main":
                raise ValueError("not current main")

        def copies(sha):
            if failure == "publication":
                raise ValueError("publication missing")

        def wait(check):
            if not check():
                raise ValueError("convergence failed")

        with tempfile.TemporaryDirectory() as directory:
            client = Path(directory) / "client"
            client.write_text(PRIVATE)
            with patch.object(c.harbor, "run", command), patch.object(c.harbor, "verify_main", main), \
                    patch.object(c.harbor, "verify_copies", copies), patch.object(c.harbor, "capture", capture), \
                    patch.object(c.harbor, "ready", return_value=BOOT), \
                    patch.object(c.harbor, "talos_boot", side_effect=lambda _: "changed" if failure == "boot" or (applied and failure == "post-boot") else BOOT), \
                    patch.object(c.nri, "prepare", prepare), patch.object(c.nri, "documents", side_effect=lambda p: json.loads(p.read_text())), \
                    patch.object(c.effective, "verify", effective), patch.object(c, "merged", side_effect=lambda client: json.loads(command(*client, "read", c.CRI))), \
                    patch.object(c, "wait", wait), contextlib.redirect_stdout(io.StringIO()) as output:
                if failure and not (rollback and failure in ("cri-health", "publication")):
                    with self.assertRaises((ValueError, RuntimeError)):
                        c.reconcile(client, "talosctl", execute, SHA, rollback, release)
                else:
                    c.reconcile(client, "talosctl", execute, SHA, rollback, release)
                self.assertNotIn(PRIVATE, output.getvalue())
        return calls

    def test_enable_rollback_and_scheduling_release(self):
        for rollback in (False, True):
            calls = self.exercise(rollback=rollback)
            drain = next(i for i, a in enumerate(calls) if a[:2] == ("kubectl", "drain"))
            apply = next(i for i, a in enumerate(calls) if "apply-config" in a)
            restart = next(i for i, a in enumerate(calls) if "restart" in a)
            self.assertLess(drain, apply)
            self.assertLess(apply, restart)
            self.assertFalse(any(a[:2] == ("kubectl", "uncordon") for a in calls))
            release = self.exercise(rollback=rollback, release=True)
            self.assertTrue(any(a[:2] == ("kubectl", "uncordon") for a in release))
            self.assertFalse(any("apply-config" in a or "restart" in a or "drain" in a for a in release))

    def test_rollback_can_recover_unhealthy_cri(self):
        calls = self.exercise("cri-health", rollback=True)
        self.assertTrue(any("apply-config" in a for a in calls))

    def test_rollback_does_not_depend_on_publication(self):
        calls = self.exercise("publication", rollback=True)
        self.assertTrue(any("apply-config" in a for a in calls))

    def test_preflight_is_read_only(self):
        calls = self.exercise(execute=False)
        self.assertFalse(any("apply-config" in a or "restart" in a or "drain" in a or "uncordon" in a for a in calls))

    def test_pre_mutation_refusals(self):
        for failure in ("cli-version", "context", "node-role", "node-ready", "machine-role", "boot", "engine-pod", "engine-daemonset", "cri-health", "config-drift", "cri-drift", "main", "publication", "drain"):
            with self.subTest(failure=failure):
                calls = self.exercise(failure)
                self.assertFalse(any("apply-config" in a or "restart" in a or "uncordon" in a for a in calls))

    def test_failed_apply_or_restart_never_releases_scheduling(self):
        for failure in ("apply-readback", "merged-drift", "post-boot", "restart", "post-health", "dataplane", "engine-after-apply"):
            with self.subTest(failure=failure):
                calls = self.exercise(failure)
                self.assertFalse(any("uncordon" in a for a in calls))
                if failure in ("apply-readback", "merged-drift", "post-boot", "engine-after-apply"):
                    self.assertFalse(any("restart" in a for a in calls))

    def test_release_requires_ready_dataplane(self):
        calls = self.exercise("dataplane", release=True)
        self.assertFalse(any("uncordon" in a for a in calls))

    def test_release_cannot_implicitly_execute(self):
        self.exercise("release-without-execute", execute=False, release=True)


if __name__ == "__main__":
    unittest.main()
