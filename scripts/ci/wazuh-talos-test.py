#!/usr/bin/env python3
"""Exercise Wazuh Talos preservation and activation guards without live changes."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("wazuh_talos", ROOT / "scripts/wazuh-talos.py")
operator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operator)
SHA = "a" * 40
BASE = [{"version": "v1alpha1", "machine": {
    "type": "controlplane", "ca": {"key": "private-fixture"},
    "sysctls": {"net.ipv4.ip_forward": "1"},
    "logging": {"destinations": [{"endpoint": "tcp://other-collector:1234", "format": "json_lines"}]}},
    "cluster": {"secret": "private-fixture", "apiServer": {"auditPolicy": {"rules": [{"level": "Metadata"}]}}}},
    {"apiVersion": "v1alpha1", "kind": "UserVolumeConfig", "name": "preserve-volume"}]


class TalosTest(unittest.TestCase):
    def test_talos_normalization_preserves_the_kernel_document(self):
        with tempfile.TemporaryDirectory(prefix="wazuh-talos-test-") as temporary:
            directory = Path(temporary)
            base, candidate, normalized = (directory / name for name in ("base.yaml", "candidate.yaml", "normalized.yaml"))
            operator.run("talosctl", "gen", "config", "test", "https://192.0.2.1:6443",
                         "--output-types", "controlplane", "--output", str(base),
                         "--with-docs=false", "--with-examples=false")
            after = operator.desired(operator.documents(base), "logs", False)
            candidate.write_text("\n---\n".join(json.dumps(item) for item in after))
            operator.normalize(candidate, normalized)
            operator.run("talosctl", "validate", "--config", str(normalized), "--mode", "metal", "--strict")
            self.assertEqual(operator.documents(normalized), after)

    def test_real_patches_preserve_unrelated_state_and_are_idempotent(self):
        before = copy.deepcopy(BASE)
        for phase in ("logs", "indexer"):
            with self.subTest(phase=phase):
                after = operator.desired(before, phase, False)
                self.assertEqual(operator.desired(after, phase, False), after)
                self.assertEqual(before, BASE, "Original private configuration must remain unmodified")
                self.assertIn(BASE[1], after, "Unknown Talos documents must survive")
                self.assertEqual(after[0]["machine"]["ca"], BASE[0]["machine"]["ca"])
                self.assertEqual(after[0]["cluster"], BASE[0]["cluster"])
                self.assertEqual(after[0]["machine"]["sysctls"]["net.ipv4.ip_forward"], "1")
                if phase == "logs":
                    self.assertIn(BASE[0]["machine"]["logging"]["destinations"][0],
                                  after[0]["machine"]["logging"]["destinations"])
                    rolled_back = operator.desired(after, phase, True)
                    self.assertEqual(rolled_back, before)
                    self.assertEqual(operator.desired(rolled_back, phase, True), rolled_back)
                else:
                    self.assertEqual(after[0]["machine"]["sysctls"]["vm.max_map_count"], "262144")
                    self.assertEqual(after[0]["machine"]["logging"], before[0]["machine"]["logging"])
                    self.assertEqual(operator.desired(after, phase, True)[0]["machine"]["sysctls"]["vm.max_map_count"], "65530")

    def test_main_guard_rejects_missing_sha_dirty_checkout_and_stale_main(self):
        for expected, dirty, head, remote in ((None, "", SHA, SHA), ("a" * 7, "", SHA, SHA),
                                             (SHA, " M changed", SHA, SHA),
                                             (SHA, "", "b" * 40, SHA), (SHA, "", SHA, "b" * 40)):
            with self.subTest(expected=expected, dirty=dirty, head=head, remote=remote):
                def run(*command):
                    return dirty if command[1] == "status" else head if command[1] == "rev-parse" else remote
                with patch.object(operator, "run", side_effect=run), self.assertRaises(RuntimeError):
                    operator.verify_main(expected)

    def test_worker_never_receives_indexer_sysctl(self):
        with patch.object(operator, "run") as run, self.assertRaises(RuntimeError):
            operator.reconcile("10.1.0.200", "indexer", True, SHA, False, Path("/unused"))
        run.assert_not_called()

    def test_live_audit_policy_must_not_capture_bodies_or_skip_requests(self):
        good = {"apiVersion": "audit.k8s.io/v1", "kind": "Policy", "rules": [{"level": "Metadata"}]}
        bad = [
            {**good, "rules": [{"level": "RequestResponse"}]},
            {**good, "rules": [{"level": "None"}]},
            {**good, "rules": [{"level": "Metadata", "resources": [{"group": "", "resources": ["pods"]}]}]},
            {**good, "rules": []},
        ]
        for policy in [good, *bad]:
            completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(policy), stderr="")
            with self.subTest(policy=policy), patch.object(operator, "run", return_value="fixture"), \
                    patch.object(operator.subprocess, "run", return_value=completed):
                if policy is good:
                    operator.audit_safe(["talosctl"])
                else:
                    with self.assertRaises(RuntimeError):
                        operator.audit_safe(["talosctl"])

    def test_collector_must_be_available_before_contacting_nodeport(self):
        deployment = {"metadata": {"generation": 2}, "status": {"observedGeneration": 1, "availableReplicas": 1}}
        with patch.object(operator, "run", return_value=json.dumps(deployment)), \
                patch.object(operator.socket, "create_connection") as connection, self.assertRaises(RuntimeError):
            operator.collector_ready()
        connection.assert_not_called()

    def test_indexer_rollback_waits_for_desired_and_actual_zero_replicas(self):
        for desired, actual in ((1, 0), (0, 1), (1, 1)):
            statefulset = {"spec": {"replicas": desired}, "status": {"replicas": actual}}
            with patch.object(operator, "run", return_value=json.dumps(statefulset)), self.assertRaises(RuntimeError):
                operator.rollback_safe()
        with patch.object(operator, "run", return_value=json.dumps({"spec": {"replicas": 0}, "status": {}})):
            operator.rollback_safe()


if __name__ == "__main__":
    unittest.main()
