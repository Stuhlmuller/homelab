#!/usr/bin/env python3
"""Fail-closed fixtures for read-only canary traffic probes."""

import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/network-policy-qualification.py"


def load_module():
    spec = importlib.util.spec_from_file_location("network_policy_qualification", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CanaryQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_traffic_requires_baseline_and_all_denials(self):
        pods = {name: {"status": {"podIP": f"10.42.0.{index}"}}
                for index, name in enumerate(("npq-client", "npq-allowed", "npq-denied"), 1)}
        expected = [0 if case[-1] else 7 for case in self.module.CASES]
        with patch.object(self.module, "probe", side_effect=expected) as probe:
            self.assertEqual(len(self.module.traffic_matrix(pods)), len(expected))
            self.assertEqual(probe.call_count, len(expected))
        for index in (0, 5, 7):
            wrong = list(expected)
            wrong[index] = 7 if wrong[index] == 0 else 0
            with self.subTest(index=index), patch.object(self.module, "probe", side_effect=wrong):
                with self.assertRaisesRegex(ValueError, "traffic mismatch"):
                    self.module.traffic_matrix(pods)
        with patch.object(self.module, "probe", side_effect=[1] + expected[1:]):
            with self.assertRaisesRegex(ValueError, "traffic mismatch"):
                self.module.traffic_matrix(pods)

    def test_inspection_refuses_foreign_policy_or_untainted_node(self):
        node = {"metadata": {"name": "zimaboard-0", "uid": "node-uid",
                             "labels": {self.module.CANARY_KEY: "true"}},
                "spec": {"taints": [{"key": self.module.CANARY_KEY,
                                     "value": "true", "effect": "NoSchedule",
                                     "timeAdded": "2026-10-18T00:00:00Z"}]},
                "status": {"conditions": [{"type": "Ready", "status": "True"}],
                           "nodeInfo": {"bootID": "boot-id"}}}
        namespace = {"metadata": {"labels": {
            "pod-security.kubernetes.io/enforce": "restricted"}}}
        pods = {}
        for name, role in (("npq-client", "client"), ("npq-allowed", "allowed"),
                           ("npq-denied", "denied")):
            pods[name] = {"metadata": {"uid": f"{name}-uid", "labels": {"role": role}},
                          "spec": {"nodeName": "zimaboard-0",
                                   "containers": [{"image": self.module.IMAGE}]},
                          "status": {"phase": "Running", "podIP": "10.42.0.2",
                                     "conditions": [{"type": "Ready", "status": "True"}]}}
        firewall = {"status": {"desiredNumberScheduled": 1, "numberReady": 1}}
        firewall_pod = {"metadata": {"uid": "firewall-uid"},
                        "spec": {"nodeName": "zimaboard-0",
                                 "containers": [{"image": self.module.FIREWALL_IMAGE}]},
                        "status": {"phase": "Running", "conditions": [
                            {"type": "Ready", "status": "True"}]}}
        policy = json.loads(json.dumps(self.module.EXPECTED_POLICY))
        objects = {
            ("get", "node", "zimaboard-0"): node,
            ("get", "namespace", self.module.NAMESPACE): namespace,
            ("-n", "kube-system", "get", "daemonset", "kube-router-network-policy"): firewall,
            ("-n", "kube-system", "get", "pods", "-l",
             "app.kubernetes.io/name=kube-router-network-policy"): {"items": [firewall_pod]},
            ("-n", self.module.NAMESPACE, "get", "networkpolicies"): {"items": [policy]},
        }
        for name, pod in pods.items():
            objects[("-n", self.module.NAMESPACE, "get", "pod", name)] = pod
        config = {"activationEnabled": True, "canary": {"node": "zimaboard-0"},
                  "nodeOrder": ["zimaboard-0", "acer"]}
        with patch.object(self.module, "kubernetes_json", side_effect=lambda *args: objects[args]):
            self.assertEqual(self.module.inspect(config)[0]["metadata"]["uid"], "node-uid")
            objects[("-n", self.module.NAMESPACE, "get", "networkpolicies")]["items"].append(
                {"kind": "NetworkPolicy", "metadata": {"name": "foreign"}})
            with self.assertRaises(ValueError):
                self.module.inspect(config)
            objects[("-n", self.module.NAMESPACE, "get", "networkpolicies")]["items"].pop()
            node["spec"]["taints"] = []
            with self.assertRaisesRegex(ValueError, "taint"):
                self.module.inspect(config)

    def test_receipt_is_private_exclusive_and_not_a_lifecycle_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.json"
            self.module.private_output(path, {"result": "traffic-probe-passed-lifecycle-unverified"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text())["result"],
                             "traffic-probe-passed-lifecycle-unverified")
            with self.assertRaises(ValueError):
                self.module.private_output(path, {})


if __name__ == "__main__":
    unittest.main()
