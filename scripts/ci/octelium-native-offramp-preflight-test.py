#!/usr/bin/env python3
"""Fixture checks for the fail-closed Octelium emergency off-ramp preflight."""

import copy
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


source = Path(__file__).resolve().parents[1] / "octelium-native-offramp-preflight.py"
spec = importlib.util.spec_from_file_location("offramp", source)
offramp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offramp)

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=2)).isoformat()


def fixture():
    items = []
    for index in range(25):
        uid = f"service-{index}"
        labels = {"octelium.com/component": "svc", "octelium.com/svc-uid": uid}
        items += [
            {"kind": "Deployment", "metadata": {"name": f"emergency-{index}"},
             "spec": {"template": {"metadata": {"labels": dict(labels)}}}},
            {"kind": "Deployment", "metadata": {"name": f"native-{index}", "uid": f"deployment-{index}", "generation": 1},
             "spec": {"replicas": 1, "template": {"metadata": {"labels": dict(labels)}}},
             "status": {"readyReplicas": 1, "observedGeneration": 1}},
            {"kind": "ReplicaSet", "metadata": {"uid": f"rs-{index}",
             "ownerReferences": [{"kind": "Deployment", "uid": f"deployment-{index}", "controller": True}]}},
            {"kind": "Pod", "metadata": {"ownerReferences": [{"kind": "ReplicaSet", "uid": f"rs-{index}", "controller": True}]},
             "spec": {"nodeName": "worker", "containers": [{"resources": {"requests": {"memory": "1Mi"}}}]},
             "status": {"phase": "Running", "podIP": f"10.0.0.{index+1}",
                        "conditions": [{"type": "Ready", "status": "True", "lastTransitionTime": OLD}],
                        "containerStatuses": [{"name": "vigil", "ready": True, "restartCount": 0}]}},
        ]
    workloads = {"items": items}
    nodes = {"items": [{"metadata": {"name": "worker", "labels": {"octelium.com/node-mode-dataplane": ""}},
                        "status": {"allocatable": {"memory": "8192Mi"},
                                   "conditions": [{"type": "Ready", "status": "True", "lastTransitionTime": OLD}]}}]}
    metrics = {"items": [{"metadata": {"name": "worker"}, "timestamp": NOW.isoformat(),
                          "usage": {"memory": "4096Mi"}}]}
    return workloads, nodes, metrics, {"items": [x for x in items if x["kind"] == "Pod"]}


class OfframpPreflightTest(unittest.TestCase):
    def test_healthy_fleet_with_real_headroom_passes_preflight_only(self):
        matched, failures = offramp.evaluate(*fixture(), NOW)
        self.assertEqual((matched, failures), (25, []))

    def test_reused_service_uid_or_restart_blocks(self):
        workloads, nodes, metrics, pods = fixture()
        workloads = copy.deepcopy(workloads)
        workloads["items"][1]["spec"]["template"]["metadata"]["labels"]["octelium.com/svc-uid"] = "wrong"
        workloads["items"][7]["status"]["containerStatuses"][0]["restartCount"] = 1
        _, failures = offramp.evaluate(workloads, nodes, metrics, pods, NOW)
        self.assertTrue(any("missing or ambiguous" in x for x in failures))
        self.assertTrue(any("uninterrupted Ready" in x for x in failures))

    def test_stale_metrics_and_unreserved_memory_block(self):
        workloads, nodes, metrics, pods = fixture()
        metrics["items"][0]["timestamp"] = (NOW - timedelta(minutes=6)).isoformat()
        metrics["items"][0]["usage"]["memory"] = "6000Mi"
        _, failures = offramp.evaluate(workloads, nodes, metrics, pods, NOW)
        self.assertTrue(any("older than five minutes" in x for x in failures))
        self.assertTrue(any("observed memory margin" in x for x in failures))

    def test_recent_worker_recovery_blocks_even_when_pods_are_old(self):
        workloads, nodes, metrics, pods = fixture()
        nodes["items"][0]["status"]["conditions"][0]["lastTransitionTime"] = (NOW - timedelta(hours=1)).isoformat()
        _, failures = offramp.evaluate(workloads, nodes, metrics, pods, NOW)
        self.assertTrue(any("worker has not remained Ready for 24h" in x for x in failures))

    def test_missing_emergency_deployment_blocks(self):
        workloads, nodes, metrics, pods = fixture()
        workloads["items"] = [x for x in workloads["items"] if x["metadata"].get("name") != "emergency-0"]
        _, failures = offramp.evaluate(workloads, nodes, metrics, pods, NOW)
        self.assertTrue(any("expected 25" in x for x in failures))

    def test_restartable_init_sidecar_counts_during_startup_and_steady_state(self):
        pod = {"spec": {"containers": [{"resources": {"requests": {"memory": "368Mi"}}}],
                        "initContainers": [
                            {"resources": {"requests": {"memory": "512Mi"}}},
                            {"restartPolicy": "Always", "resources": {"requests": {"memory": "128Mi"}}},
                            {"resources": {"requests": {"memory": "768Mi"}}},
                        ]}}
        self.assertEqual(offramp.pod_request_bytes(pod), 896 * 1024 * 1024)

    def test_missing_native_node_or_ready_timestamp_blocks(self):
        workloads, nodes, metrics, pods = fixture()
        del workloads["items"][3]["spec"]["nodeName"]
        del nodes["items"][0]["status"]["conditions"][0]["lastTransitionTime"]
        _, failures = offramp.evaluate(workloads, nodes, metrics, pods, NOW)
        self.assertTrue(any("uninterrupted Ready" in x for x in failures))
        self.assertTrue(any("worker has not remained Ready" in x for x in failures))


if __name__ == "__main__":
    unittest.main()
