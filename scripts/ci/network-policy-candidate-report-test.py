#!/usr/bin/env python3
"""Offline checks for read-only NetworkPolicy canary capacity observations."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest import TestCase, main, mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "candidate_report", ROOT / "scripts/network-policy-candidate-report.py")
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)
MIB = 1024**2


def pod(name, request="50Mi", *, namespace="apps", owner="Deployment",
        phase="Running", node="zimaboard-0", uid=None, init=None, overhead=None):
    result = {
        "metadata": {"namespace": namespace, "name": name, "uid": uid or name,
                     "ownerReferences": [{"kind": owner, "name": name,
                                          "controller": True}]},
        "spec": {"nodeName": node, "containers": [
            {"name": "app", "resources": {"requests": {"memory": request}}}]},
        "status": {"phase": phase},
    }
    if init:
        result["spec"]["initContainers"] = init
    if overhead:
        result["spec"]["overhead"] = {"memory": overhead}
    return result


def fixtures():
    node = {
        "kind": "Node",
        "metadata": {"name": "zimaboard-0", "uid": "node-uid", "resourceVersion": "9"},
        "status": {
            "capacity": {"memory": "8142745600"},
            "allocatable": {"memory": "7635234816"},
            "nodeInfo": {"bootID": "boot-id"},
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }
    # 64 app Pods total 3,920 MiB: 62 x 50 + 180 + Deluge 512+128.
    apps = [pod(f"app-{i}") for i in range(62)]
    apps.append(pod("app-62", "180Mi"))
    apps.append(pod("deluge", "512Mi", namespace="media", init=[
        {"name": "gluetun", "restartPolicy": "Always",
         "resources": {"requests": {"memory": "128Mi"}}}]))
    apps.append(pod("image-rewrite", "48Mi", namespace="kube-system"))
    daemonsets = [
        pod(f"system-{i}", "100Mi" if i < 5 else "39Mi", namespace="kube-system",
            owner="DaemonSet") for i in range(5)
    ]
    daemonsets.append(pod("octelium-gwagent", "39Mi", namespace="octelium",
                          owner="DaemonSet"))
    jobs = [pod(f"job-{i}", "256Mi", namespace="media", owner="Job",
                phase="Succeeded") for i in range(19)]
    pods = {"kind": "PodList", "metadata": {"resourceVersion": "10"},
            "items": [*apps, *daemonsets, *jobs]}
    summary = {"node": {"nodeName": "zimaboard-0",
                        "memory": {"workingSetBytes": 5838 * MIB},
                        "fs": {"availableBytes": 8_700_088_320,
                               "capacityBytes": 16_000_000_000}}}
    return node, pods, summary


class QuantityAndRequests(TestCase):
    def test_memory_quantity_units(self):
        self.assertEqual(REPORT.memory_bytes("1Gi"), 1024**3)
        self.assertEqual(REPORT.memory_bytes("1G"), 1000**3)
        self.assertEqual(REPORT.memory_bytes("1.5Mi"), 1_572_864)
        self.assertEqual(REPORT.memory_bytes("1m"), 1)
        self.assertEqual(REPORT.memory_bytes("129e6"), 129_000_000)
        self.assertEqual(REPORT.memory_bytes("1E"), 10**18)
        self.assertEqual(REPORT.memory_bytes("1Ei"), 1024**6)
        self.assertEqual(REPORT.memory_bytes("1u"), 1)
        with self.assertRaises(ValueError):
            REPORT.memory_bytes("-1Mi")
        with self.assertRaises(ValueError):
            REPORT.memory_bytes("1furlong")

    def test_restartable_init_accumulates_with_app_and_later_init(self):
        item = pod("deluge", "512Mi", init=[
            {"name": "gluetun", "restartPolicy": "Always",
             "resources": {"requests": {"memory": "128Mi"}}},
            {"name": "prepare", "resources": {"requests": {"memory": "900Mi"}}},
        ], overhead="16Mi")
        self.assertEqual(REPORT.pod_memory_request(item), (128 + 900 + 16) * MIB)
        item["spec"]["initContainers"].pop()
        self.assertEqual(REPORT.pod_memory_request(item), (512 + 128 + 16) * MIB)

    def test_pod_level_request_overrides_container_base_before_overhead(self):
        item = pod("pod-level", "512Mi", overhead="32Mi")
        item["spec"]["resources"] = {"requests": {"memory": "256Mi"}}
        self.assertEqual(REPORT.pod_memory_request(item), 288 * MIB)

    def test_resize_drift_fails_closed(self):
        item = pod("resized", "512Mi")
        item["status"]["containerStatuses"] = [{
            "name": "app", "allocatedResources": {"memory": "768Mi"}}]
        with self.assertRaisesRegex(ValueError, "resized"):
            REPORT.pod_memory_request(item)
        item["status"]["containerStatuses"] = []
        item["status"]["resize"] = "InProgress"
        with self.assertRaisesRegex(ValueError, "resized"):
            REPORT.pod_memory_request(item)


class InventoryAndBudgets(TestCase):
    def test_live_shape_reconciles_two_distinct_budgets(self):
        node, pods, summary = fixtures()
        report = REPORT.build_report("zimaboard-0", node, pods, summary,
                                     "2026-11-01T15:08:33+00:00")
        self.assertEqual(report["admission"], "unproven")
        self.assertEqual(len(report["assignedPods"]), 90)
        self.assertEqual(len(report["foreignPods"]), 85)
        self.assertIn("octelium-gwagent", {row["name"] for row in report["foreignPods"]})
        self.assertEqual(report["node"]["scheduledPodRequestsBytes"], 4507 * MIB)
        self.assertEqual(report["node"]["requestHeadroomBytes"],
                         7_635_234_816 - 4507 * MIB)
        self.assertEqual(report["node"]["physicalHeadroomBytes"],
                         8_142_745_600 - 5838 * MIB)
        self.assertEqual(report["node"]["filesystemAvailableBytes"], 8_700_088_320)
        self.assertEqual(sum(row["scheduledRequestBytes"] for row in
                             report["assignedPods"] if row["name"].startswith("job-")), 0)
        self.assertEqual(next(row["effectiveRequestBytes"] for row in
                              report["assignedPods"] if row["name"] == "deluge"), 640 * MIB)

    def test_incomplete_or_wrong_node_inventory_fails_closed(self):
        node, pods, summary = fixtures()
        pods["metadata"]["continue"] = "next-page"
        with self.assertRaisesRegex(ValueError, "incomplete"):
            REPORT.build_report("zimaboard-0", node, pods, summary, "now")
        del pods["metadata"]["continue"]
        pods["items"][0]["spec"]["nodeName"] = "zimaboard-1"
        with self.assertRaisesRegex(ValueError, "differs"):
            REPORT.build_report("zimaboard-0", node, pods, summary, "now")
        pods["items"][0]["spec"]["nodeName"] = "zimaboard-0"
        pods["items"].append(pods["items"][0])
        with self.assertRaisesRegex(ValueError, "differs"):
            REPORT.build_report("zimaboard-0", node, pods, summary, "now")

    def test_invalid_summary_or_node_identity_fails_closed(self):
        node, pods, summary = fixtures()
        summary["node"]["nodeName"] = "zimaboard-1"
        with self.assertRaisesRegex(ValueError, "identity differs"):
            REPORT.build_report("zimaboard-0", node, pods, summary, "now")
        summary["node"]["nodeName"] = "zimaboard-0"
        node["metadata"]["uid"] = ""
        with self.assertRaisesRegex(ValueError, "Node identity"):
            REPORT.build_report("zimaboard-0", node, pods, summary, "now")

    def test_missing_metrics_or_list_version_fails_closed(self):
        node, pods, summary = fixtures()
        del summary["node"]["memory"]["workingSetBytes"]
        with self.assertRaisesRegex(ValueError, "node working set"):
            REPORT.build_report("zimaboard-0", node, pods, summary, "now")
        summary["node"]["memory"]["workingSetBytes"] = 5838 * MIB
        del summary["node"]["fs"]["availableBytes"]
        with self.assertRaisesRegex(ValueError, "filesystem available"):
            REPORT.build_report("zimaboard-0", node, pods, summary, "now")
        summary["node"]["fs"]["availableBytes"] = 8_700_088_320
        pods["metadata"]["resourceVersion"] = ""
        with self.assertRaisesRegex(ValueError, "incomplete"):
            REPORT.build_report("zimaboard-0", node, pods, summary, "now")

    def test_cli_uses_only_fixed_read_only_kubectl_calls(self):
        node, pods, summary = fixtures()
        responses = [REPORT.API_SERVER, json.dumps(node), json.dumps(pods),
                     json.dumps(summary)]
        with mock.patch.object(REPORT, "kubectl", side_effect=responses) as call:
            with mock.patch.object(sys, "argv", ["candidate", "--node", "zimaboard-0"]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(REPORT.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["admission"], "unproven")
        self.assertEqual([args.args for args in call.call_args_list], [
            ("config", "view", "--minify", "-o",
             "jsonpath={.clusters[0].cluster.server}"),
            ("get", "node", "zimaboard-0", "-o", "json"),
            ("get", "--raw",
             "/api/v1/pods?fieldSelector=spec.nodeName%3Dzimaboard-0&limit=0"),
            ("get", "--raw", "/api/v1/nodes/zimaboard-0/proxy/stats/summary"),
        ])


if __name__ == "__main__":
    main()
