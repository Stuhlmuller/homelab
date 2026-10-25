#!/usr/bin/env python3
"""Fail-closed checks for protected canary placement evidence."""

import argparse
import copy
import hashlib
import json
import os
import runpy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SUT = runpy.run_path(str(ROOT / "scripts/network-policy-placement.py"))
SHA = "a" * 40
NODE = SUT["NODE"]
SYSTEM = [{"namespace": "kube-system", "name": "flannel-1", "uid": "pod-uid"}]


def now():
    return datetime.now(timezone.utc).isoformat()


def baseline():
    snapshot = {"backend": "nft", "nft": "", "legacy": "", "ip6nft": "",
                "ip6legacy": "", "ipset": ""}
    return {"format": 1, "stage": "firewall-baseline", "status": "verified",
            "verified": True, "sourceSha": SHA, "runId": "123", "node": NODE,
            "nodeUid": "node-uid", "bootID": "boot-id", "firewallBaselineEmpty": True,
            "podDeleted": True, "ownedChains": 0, "ownedSets": 0,
            "snapshot": snapshot, "backend": "nft", "snapshotSha256": "0" * 64,
            "systemDaemonSetPods": SYSTEM, "completedAt": now()}


def pod():
    return {"metadata": {"namespace": "kube-system", "name": "flannel-1",
                         "uid": "pod-uid"},
            "spec": {"nodeName": NODE, "containers": [{"resources": {
                "requests": {"memory": "100Mi", "cpu": "100m"}}}]},
            "status": {"phase": "Running", "conditions": [
                {"type": "Ready", "status": "True"}]}}


class PlacementTests(unittest.TestCase):
    def test_quantity_and_pod_request_budget(self):
        self.assertEqual(SUT["quantity"]("1339500Ki"), 1339500 * 1024)
        self.assertEqual(SUT["quantity"]("250m", True), 250)
        self.assertEqual(SUT["pod_requests"](pod()), [100 * SUT["MIB"], 100])
        candidate = pod()
        candidate["spec"]["initContainers"] = [{"resources": {
            "requests": {"memory": "200Mi", "cpu": "500m"}}}]
        self.assertEqual(SUT["pod_requests"](candidate), [200 * SUT["MIB"], 500])
        candidate["spec"]["resources"] = {"requests": {"memory": "1Gi"}}
        with self.assertRaisesRegex(ValueError, "Pod-level"):
            SUT["pod_requests"](candidate)
        with self.assertRaisesRegex(ValueError, "quantity"):
            SUT["quantity"]("1.5Pirate")

    def test_baseline_requires_unique_verified_current_empty_capture(self):
        record = baseline()

        class Store:
            def __init__(self, item):
                self.item = item

            def read(self, key, limit):
                self.key = key
                self.limit = limit
                return json.dumps(self.item).encode()

            def version(self, _key, required):
                self.assert_required = required
                return "version-1"

        with patch.dict(SUT["CLEANUP"], {
                "snapshot_sha256": lambda *_: "0" * 64,
                "cleanup_plan": lambda *_: ([], set(), set())}):
            store = Store(record)
            capture, digest, version = SUT["read_baseline"](store, SHA, "123")
            self.assertEqual(capture, record)
            self.assertEqual(digest, hashlib.sha256(json.dumps(record).encode()).hexdigest())
            self.assertEqual(version, "version-1")
            self.assertIn(f"/{SHA}/123/firewall-baseline-capture.json", store.key)
            for update in ({"verified": False}, {"sourceSha": "b" * 40},
                           {"podDeleted": False}, {"ownedSets": 1},
                           {"snapshotSha256": "f" * 64},
                           {"completedAt": (datetime.now(timezone.utc) -
                                            timedelta(hours=2)).isoformat()}):
                with self.subTest(update=update), self.assertRaises(ValueError):
                    SUT["read_baseline"](Store(record | update), SHA, "123")
            with patch.dict(SUT["CLEANUP"], {
                    "cleanup_plan": lambda *_: (["owned"], set(), set())}):
                with self.assertRaises(ValueError):
                    SUT["read_baseline"](Store(record), SHA, "123")

    def test_capacity_requires_fresh_metrics_nodefs_and_peak_margin(self):
        allocatable = {"metadata": {"name": NODE},
                       "status": {"allocatable": {"memory": "1308Mi", "cpu": "1950m"}}}
        listing = {"metadata": {}, "items": [pod()]}
        metrics = {"kind": "NodeMetrics", "metadata": {"name": NODE},
                   "timestamp": now(), "usage": {"memory": "400Mi", "cpu": "150m"}}
        summary = {"node": {"nodeName": NODE, "fs": {"time": now(),
                   "availableBytes": 8 * 1024**3, "capacityBytes": 16 * 1024**3}}}

        def run(node, pod_list, metric, fs):
            def kube_json(*args):
                return node if args[:2] == ("get", "node") else pod_list

            def command(*args):
                return json.dumps(metric if "metrics.k8s.io" in args[-1] else fs)

            with patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": kube_json, "complete_items": lambda value, _: value["items"],
                    "command": command, "ready": lambda item: True}):
                return SUT["capacity"](baseline())

        receipt = run(allocatable, listing, metrics, summary)
        self.assertEqual(receipt["requestedMemoryBytes"], 100 * SUT["MIB"])
        for value in ("600Mi", "1000Mi"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "headroom"):
                run(allocatable, listing, metrics | {"usage": {
                    "memory": value, "cpu": "150m"}}, summary)
        with self.assertRaisesRegex(ValueError, "filesystem"):
            changed = copy.deepcopy(summary)
            changed["node"]["fs"]["availableBytes"] = 4 * 1024**3
            run(allocatable, listing, metrics, changed)
        with self.assertRaisesRegex(ValueError, "stale"):
            changed = metrics | {"timestamp": (datetime.now(timezone.utc) -
                                  timedelta(minutes=10)).isoformat()}
            run(allocatable, listing, changed, summary)
        with self.assertRaisesRegex(ValueError, "assigned Pods"):
            run(allocatable, {"metadata": {}, "items": []}, metrics, summary)

    def test_admitted_enforcer_capacity_preserves_full_peak_budget(self):
        enforcer = pod()
        enforcer["metadata"].update(name="kube-router-network-policy-abc", uid="enforcer-uid")
        enforcer["spec"]["containers"][0]["resources"] = {
            "requests": {"memory": "250Mi", "cpu": "250m"},
            "limits": {"memory": "512Mi"}}
        node = {"status": {"allocatable": {"memory": "1308Mi", "cpu": "1950m"}}}
        listing = {"metadata": {}, "items": [pod(), enforcer]}
        metrics = {"kind": "NodeMetrics", "metadata": {"name": NODE},
                   "timestamp": now(), "usage": {"memory": "500Mi", "cpu": "300m"}}
        summary = {"node": {"nodeName": NODE,
                   "memory": {"time": now(), "workingSetBytes": 500 * SUT["MIB"]},
                   "cpu": {"time": now(), "usageNanoCores": 300000000},
                   "fs": {"time": now(), "availableBytes": 8 * 1024**3,
                          "capacityBytes": 16 * 1024**3}},
                   "pods": [{"podRef": {"namespace": "kube-system",
                                        "name": "kube-router-network-policy-abc",
                                        "uid": "enforcer-uid"},
                             "memory": {"time": now(), "workingSetBytes": 100 * SUT["MIB"]},
                             "cpu": {"time": now(), "usageNanoCores": 100000000}}]}

        def run(fs=summary, metric=metrics, candidate=enforcer):
            with patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": lambda *args: node if args[:2] == ("get", "node") else listing,
                    "complete_items": lambda value, _: value["items"],
                    "command": lambda *args: json.dumps(
                        metric if "metrics.k8s.io" in args[-1] else fs),
                    "ready": lambda *_: True}):
                return SUT["capacity"](baseline(), candidate)

        receipt = run()
        self.assertEqual(receipt["observedMemoryBytes"], 400 * SUT["MIB"])
        self.assertEqual(receipt["plannedMemoryLimitBytes"], 704 * SUT["MIB"])
        self.assertTrue(receipt["enforcerAlreadyPresent"])
        changed = copy.deepcopy(summary)
        changed["node"]["memory"]["workingSetBytes"] = 600 * SUT["MIB"]
        with self.assertRaisesRegex(ValueError, "headroom"):
            run(changed, metrics | {"usage": {"memory": "600Mi", "cpu": "300m"}})
        for mutation in (lambda value: value["pods"].clear(),
                         lambda value: value["pods"][0]["podRef"].update(uid="wrong"),
                         lambda value: value["pods"][0]["memory"].update(
                             time=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()),
                         lambda value: value["node"]["memory"].update(
                             workingSetBytes=450 * SUT["MIB"])):
            changed = copy.deepcopy(summary)
            mutation(changed)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                run(changed)

    def test_no_receipt_before_exact_source_and_live_recheck(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "placement.json"
            config = json.loads(SUT["CONFIG"].read_text())
            events = []

            class Store:
                def __init__(self, _bucket):
                    self.store = self

                def check(self):
                    events.append("check")

                def write_once(self, key, record, _limit):
                    events.append("write")
                    self.key, self.record = key, record

            store = Store("bucket")
            identities = iter((("node-uid", "boot-id"),) * 4)
            with patch.dict(SUT["PLATFORM"], {
                    "require_reviewed_execution_config": lambda *_: None,
                    "validate_config": lambda *_: config,
                    "protected_context": lambda *_: None,
                    "private_output": lambda *_: output}), \
                    patch.dict(SUT["CLEANUP"], {
                        "require_current_main": lambda *_: events.append("main"),
                        "write_record": lambda path, record: path.write_text(json.dumps(record))}), \
                    patch.dict(SUT["OWNERSHIP"], {"PrivateStore": lambda *_: store}), \
                    patch.dict(SUT["BASELINE"], {
                        "node_identity": lambda: next(identities),
                        "system_pods": lambda: SYSTEM}), \
                    patch.dict(SUT["CANARY"], {
                        "require_runtime_absent": lambda *_: None,
                        "require_exclusive_canary_label": lambda *_: None,
                        "validate_placement": lambda *_: None}), \
                    patch.dict(SUT["execute"].__globals__, {
                        "pinned_manifests": lambda *_: None,
                        "read_baseline": lambda *_: (baseline(), "0" * 64, "version-1"),
                        "capacity": lambda *_: {"measured": True}}), \
                    patch.dict(os.environ, {"GITHUB_RUN_ID": "456"}):
                args = argparse.Namespace(config=SUT["CONFIG"], expected_sha=SHA,
                                          baseline_source_sha=SHA, baseline_run_id="123",
                                          bucket="bucket", output=output)
                SUT["execute"](args)
                self.assertEqual(events[-1], "write")
                self.assertEqual(store.record["sourceSha"], SHA)
                self.assertEqual(store.record["placementRunId"], "456")
                self.assertIn(f"/{SHA}/placement/456.json", store.key)
                self.assertEqual(store.record["baselineCaptureSha256"], "0" * 64)
                self.assertTrue(output.exists())
                output.unlink()
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "457"}):
                    SUT["execute"](args)
                self.assertIn(f"/{SHA}/placement/457.json", store.key)
                self.assertEqual(events.count("write"), 2)
                output.unlink()
                args.baseline_source_sha = "b" * 40
                with self.assertRaisesRegex(ValueError, "exact current main"):
                    SUT["execute"](args)
                self.assertEqual(events.count("write"), 2)

    def test_admission_remeasures_spike_and_binds_original_capture(self):
        capture = baseline()
        config = json.loads(SUT["CONFIG"].read_text())
        timestamp = SUT["fresh"](capture["completedAt"], 3600).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        receipt = {"format": 1, "verified": True, "sourceSha": SHA,
                   "placementRunId": "456",
                   "node": NODE, "canaryNode": NODE, "nodeUid": "node-uid",
                   "bootID": "boot-id", "measured": True,
                   "isolatedTaint": config["canary"]["taint"],
                   "firewallBaselineEmpty": True, "systemDaemonSetPods": SYSTEM,
                   "capturedAt": timestamp, "baselineSourceSha": SHA,
                   "baselineRunId": "123", "baselineCapturedAt": timestamp,
                   "baselineCaptureSha256": "0" * 64,
                   "baselineCaptureVersionId": "version-1"}
        remote = {"receipt": receipt}
        metric = {"kind": "NodeMetrics", "metadata": {"name": NODE},
                  "timestamp": now(), "usage": {"memory": "400Mi", "cpu": "150m"}}
        summary = {"node": {"nodeName": NODE, "fs": {"time": now(),
                   "availableBytes": 8 * 1024**3, "capacityBytes": 16 * 1024**3}}}
        node = {"metadata": {"uid": "node-uid"},
                "status": {"nodeInfo": {"bootID": "boot-id"},
                           "allocatable": {"memory": "1308Mi", "cpu": "1950m"}}}

        class Store:
            def __init__(self, _bucket):
                self.store = self

            def check(self):
                pass

            def version(self, key, required):
                assert required
                return "version-2" if key.endswith("/457.json") else "version-1"

            def read(self, _key, _limit):
                return json.dumps(remote["receipt"]).encode()

            def write_once(self, *_):
                raise AssertionError("read-only admission must not write a placement receipt")

        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(config=SUT["CONFIG"], expected_sha=SHA,
                                      bucket="bucket", placement_run_id="456",
                                      placement_version_id="version-1",
                                      check_placement=Path(directory) / "placement.json")

            def kube_json(*arguments):
                return node if arguments[:2] == ("get", "node") else {
                    "metadata": {}, "items": [pod()]}

            def command(*arguments):
                return json.dumps(metric if "metrics.k8s.io" in arguments[-1] else summary)

            with patch.dict(SUT["PLATFORM"], {
                    "require_reviewed_execution_config": lambda *_: None,
                    "validate_config": lambda *_: config,
                    "protected_context": lambda *_: None,
                    "private_directory": lambda path: path,
                    "read_private_json": lambda *_: receipt}), \
                    patch.dict(SUT["CLEANUP"], {
                        "require_current_main": lambda *_: None,
                        "kubernetes_json": kube_json,
                        "complete_items": lambda value, _: value["items"],
                        "command": command, "ready": lambda *_: True}), \
                    patch.dict(SUT["BASELINE"], {
                        "system_pods": lambda: SYSTEM}), \
                    patch.dict(SUT["CANARY"], {
                        "node_state": lambda *_: (node, False, False),
                        "require_runtime_absent": lambda *_: None,
                        "require_exclusive_canary_label": lambda *_: None}), \
                    patch.dict(SUT["OWNERSHIP"], {"PrivateStore": Store}), \
                    patch.dict(SUT["check"].__globals__, {
                        "pinned_manifests": lambda *_: None,
                        "read_baseline": lambda *_: (capture, "0" * 64, "version-1")}):
                SUT["check"](args)
                self.assertFalse(args.check_placement.exists())
                receipt["capturedAt"] = (datetime.now(timezone.utc) -
                                         timedelta(minutes=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
                receipt["baselineCapturedAt"] = (datetime.now(timezone.utc) -
                                                 timedelta(minutes=40)).strftime(
                                                     "%Y-%m-%dT%H:%M:%SZ")
                with self.assertRaisesRegex(ValueError, "stale"):
                    SUT["check"](args)
                receipt.update(placementRunId="457", capturedAt=timestamp,
                               baselineCapturedAt=timestamp)
                args.placement_run_id = "457"
                args.placement_version_id = "version-2"
                SUT["check"](args)
                remote["receipt"] = receipt | {"nodeUid": "forged"}
                with self.assertRaisesRegex(ValueError, "selected placement"):
                    SUT["check"](args)
                remote["receipt"] = receipt
                args.placement_run_id = "999"
                with self.assertRaisesRegex(ValueError, "selected placement"):
                    SUT["check"](args)
                args.placement_run_id = "457"
                args.placement_version_id = "forged-version"
                with self.assertRaisesRegex(ValueError, "selected placement"):
                    SUT["check"](args)
                args.placement_version_id = "version-2"
                metric["usage"]["memory"] = "600Mi"
                with self.assertRaisesRegex(ValueError, "headroom"):
                    SUT["check"](args)
                for change in ({"nodeUid": "replacement"},
                               {"sourceSha": "b" * 40},
                               {"baselineCaptureVersionId": "version-2"},
                               {"baselineCaptureSha256": "f" * 64},
                               {"systemDaemonSetPods": []}):
                    original = {key: receipt[key] for key in change}
                    receipt.update(change)
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        SUT["check"](args)
                    receipt.update(original)


if __name__ == "__main__":
    unittest.main()
