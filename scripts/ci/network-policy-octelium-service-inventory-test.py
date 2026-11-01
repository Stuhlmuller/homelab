#!/usr/bin/env python3
"""Offline Service, EndpointSlice, and fallback-source join fixtures."""

import copy
import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "octelium_service_inventory",
    ROOT / "scripts/network-policy-octelium-service-inventory.py")
INVENTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVENTORY)


def listing(kind, items, version):
    return {"kind": kind, "metadata": {"resourceVersion": version}, "items": items}


def service(name, role, *, uid=None, selector=None):
    return {"metadata": {"namespace": "octelium", "name": name,
                         "uid": uid or name + "-uid"},
            "spec": {"selector": selector or {"role": role}}}


def pod(name, role, node, *, labels=None):
    return {"metadata": {"namespace": "octelium", "name": name,
                         "uid": name + "-uid", "labels": {"role": role, **(labels or {})}},
            "spec": {"nodeName": node}, "status": {"phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}]}}


def endpoint_slice(name, pods):
    return {"metadata": {"namespace": "octelium", "name": name + "-slice",
                         "labels": {"kubernetes.io/service-name": name},
                         "ownerReferences": [{"kind": "Service", "name": name,
                                             "uid": name + "-uid"}]},
            "endpoints": [{"addresses": ["10.99.0.1"],
                           "conditions": {"ready": True, "serving": True,
                                          "terminating": False},
                           "nodeName": item["spec"]["nodeName"],
                           "targetRef": {"kind": "Pod", "namespace": "octelium",
                                         "name": item["metadata"]["name"],
                                         "uid": item["metadata"]["uid"]}}
                          for item in pods]}


def source(name, role, marker, *, extra_labels=None):
    labels = {"role": role,
              "homelab.rst.io/emergency-dataplane": marker,
              **(extra_labels or {})}
    return {"kind": "Deployment",
            "metadata": {"namespace": "octelium",
                         "name": "emergency-octelium-" + name},
            "spec": {"replicas": 1, "selector": {"matchLabels": labels.copy()},
                     "template": {"metadata": {"labels": labels.copy()},
                                  "spec": {"nodeSelector": {
                                      "kubernetes.io/hostname": "acer"}}}}}


def fixtures():
    services = [service("ingress", "ingress"),
                service("proxy", "proxy", selector={
                    "role": "proxy", "octelium.com/svc-uid": "logical-uid"}),
                service("operator", "operator"), service("store", "store")]
    pods = [pod("ingress-native", "ingress", "zimaboard-0"),
            pod("ingress-fallback", "ingress", "acer", labels={
                "homelab.rst.io/emergency-dataplane": "ingress"}),
            pod("proxy-native", "proxy", "zimaboard-0", labels={
                "octelium.com/svc-uid": "logical-uid"}),
            pod("proxy-fallback", "proxy", "acer", labels={
                "homelab.rst.io/emergency-dataplane": "proxy",
                "octelium.com/svc-uid": "logical-uid"}),
            pod("operator-native", "operator", "zimaboard-0"),
            pod("store-pod", "store", "zimaboard-1")]
    slices = [endpoint_slice("ingress", pods[:2]),
              endpoint_slice("proxy", pods[2:4]),
              endpoint_slice("operator", pods[4:5]),
              endpoint_slice("store", pods[5:])]
    manifests = [source("ingress", "ingress", "ingress"),
                 source("proxy", "proxy", "proxy", extra_labels={
                     "octelium.com/svc-uid": "logical-uid"})]
    return (listing("ServiceList", services, "10"),
            listing("PodList", pods, "20"),
            listing("EndpointSliceList", slices, "30"), manifests)


def observe(values):
    with patch.object(INVENTORY, "EXPECTED_FALLBACK_DEPLOYMENTS", 2), patch.object(
            INVENTORY, "REQUIRED_FALLBACKS",
            {"ingress": "emergency-octelium-ingress"}):
        return INVENTORY.service_inventory(*values, "zimaboard-0",
                                           "2026-11-01T15:34:00+00:00")


class ServiceInventoryTests(unittest.TestCase):
    def test_native_node_typo_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be zimaboard-0"):
            INVENTORY.service_inventory(*fixtures(), "zimaboard-O",
                                        "2026-11-01T15:34:00+00:00")

    @unittest.skipUnless(shutil.which("yq"), "Nix-provided yq is unavailable")
    def test_reviewed_manifest_has_25_fallbacks_and_critical_components(self):
        result = subprocess.run(
            ["yq", "ea", "-o=json", "-I=0", "[.]", str(INVENTORY.FALLBACK_SOURCE)],
            check=True, capture_output=True, text=True)
        definitions = INVENTORY.fallback_sources(json.loads(result.stdout))
        self.assertEqual(len(definitions), 25)
        for marker, name in INVENTORY.REQUIRED_FALLBACKS.items():
            self.assertEqual(definitions[marker]["deployment"], name)

    def test_source_fallback_count_is_pinned(self):
        with self.assertRaisesRegex(ValueError, "count differs"):
            INVENTORY.fallback_sources(fixtures()[3])

    def test_critical_source_cannot_disappear_at_same_count(self):
        with patch.object(INVENTORY, "EXPECTED_FALLBACK_DEPLOYMENTS", 2):
            with self.assertRaisesRegex(ValueError, "critical emergency"):
                INVENTORY.fallback_sources(fixtures()[3])

    def test_join_includes_non_proxy_fallback_and_native_only(self):
        report = observe(fixtures())
        self.assertEqual(report["admission"], "unproven")
        self.assertFalse(report["baselineQualified"])
        self.assertEqual(report["counts"], {"fallback-ready": 2,
            "fallback-unready": 0, "native-only": 1,
            "not-native-dependent": 1, "unresolved": 0})
        self.assertEqual(report["nativeOnlyServices"], ["octelium/operator"])
        self.assertEqual(len(report["sourceFallbackDeployments"]), 2)
        self.assertEqual(report["unmappedFallbackDeployments"], [])
        self.assertEqual(len(report["services"]), 4)
        store = next(item for item in report["services"] if
                     item["id"] == "octelium/store")
        self.assertEqual(store["selectedPodUids"], ["store-pod-uid"])
        self.assertEqual(store["selectedNativePodUids"], [])
        serialized = json.dumps(report)
        for secret_detail in ("10.99.0.1", "addresses", "ports", "url"):
            self.assertNotIn(secret_detail, serialized)

    def test_unready_fallback_is_not_misclassified_as_native_only(self):
        snapshots = list(fixtures())
        snapshots[2]["items"][1]["endpoints"][1]["conditions"]["ready"] = False
        report = observe(snapshots)
        self.assertEqual(report["counts"]["fallback-unready"], 1)
        self.assertEqual(report["nativeOnlyServices"], ["octelium/operator"])

    def test_fallback_stays_ready_after_native_pods_leave(self):
        snapshots = list(fixtures())
        snapshots[1]["items"] = [item for item in snapshots[1]["items"]
                                 if item["metadata"]["name"] not in
                                 {"ingress-native", "proxy-native"}]
        for item in snapshots[2]["items"][:2]:
            item["endpoints"] = [endpoint for endpoint in item["endpoints"]
                                 if endpoint["nodeName"] != "zimaboard-0"]
        report = observe(snapshots)
        self.assertEqual(report["counts"]["fallback-ready"], 2)
        self.assertEqual(next(item for item in report["services"] if
                              item["id"] == "octelium/proxy")["readyNativePodUids"], [])

    def test_service_with_no_ready_endpoints_is_unresolved(self):
        snapshots = list(fixtures())
        snapshots[1]["items"][4]["status"]["phase"] = "Pending"
        snapshots[1]["items"][4]["status"]["conditions"][0]["status"] = "False"
        snapshots[2]["items"][2]["endpoints"][0]["conditions"]["ready"] = False
        report = observe(snapshots)
        self.assertEqual(report["counts"]["unresolved"], 1)
        self.assertEqual(report["nativeOnlyServices"], [])

    def test_selected_non_native_unready_pod_is_unresolved(self):
        snapshots = list(fixtures())
        snapshots[1]["items"][5]["status"]["conditions"][0]["status"] = "False"
        snapshots[2]["items"][3]["endpoints"][0]["conditions"]["ready"] = False
        report = observe(snapshots)
        store = next(item for item in report["services"] if
                     item["id"] == "octelium/store")
        self.assertEqual(store["classification"], "unresolved")
        self.assertEqual(store["selectedPodUids"], ["store-pod-uid"])
        self.assertEqual(store["readyOtherPodUids"], [])

    def test_publish_not_ready_addresses_cannot_fake_pod_readiness(self):
        snapshots = list(fixtures())
        snapshots[1]["items"][3]["status"]["conditions"][0]["status"] = "False"
        snapshots[0]["items"][1]["spec"]["publishNotReadyAddresses"] = True
        with self.assertRaisesRegex(ValueError, "Pod readiness"):
            observe(snapshots)

    def test_nil_endpoint_ready_uses_ready_pod(self):
        snapshots = list(fixtures())
        snapshots[2]["items"][1]["endpoints"][1]["conditions"].pop("ready")
        self.assertEqual(observe(snapshots)["counts"]["fallback-ready"], 2)

    def test_empty_label_value_is_valid_in_service_selector(self):
        snapshots = list(fixtures())
        snapshots[0]["items"][2]["spec"]["selector"]["optional"] = ""
        snapshots[1]["items"][4]["metadata"]["labels"]["optional"] = ""
        self.assertEqual(observe(snapshots)["nativeOnlyServices"],
                         ["octelium/operator"])

    def test_stale_or_orphan_endpoint_slice_is_rejected(self):
        for owners in ([], [{"kind": "Service", "name": "proxy",
                            "uid": "previous-service-uid"}]):
            with self.subTest(owners=owners):
                snapshots = list(fixtures())
                snapshots[2]["items"][1]["metadata"]["ownerReferences"] = owners
                with self.assertRaisesRegex(ValueError, "current Service UID"):
                    observe(snapshots)

    def test_unknown_or_mismatched_ready_target_is_rejected(self):
        for change in ("uid", "selector", "node", "terminating", "serving"):
            with self.subTest(change=change):
                snapshots = list(fixtures())
                item = snapshots[2]["items"][1]["endpoints"][1]
                if change == "uid":
                    item["targetRef"]["uid"] = "unknown-pod"
                elif change == "selector":
                    snapshots[1]["items"][3]["metadata"]["labels"]["role"] = "other"
                elif change == "node":
                    item["nodeName"] = "other-node"
                elif change == "terminating":
                    item["conditions"]["terminating"] = True
                else:
                    item["conditions"]["serving"] = False
                with self.assertRaisesRegex(ValueError, "Ready endpoint identity"):
                    observe(snapshots)

    def test_stale_fallback_service_uid_source_is_rejected(self):
        snapshots = list(fixtures())
        snapshots[3][1]["spec"]["selector"]["matchLabels"][
            "octelium.com/svc-uid"] = "old-logical-uid"
        snapshots[3][1]["spec"]["template"]["metadata"]["labels"][
            "octelium.com/svc-uid"] = "old-logical-uid"
        with self.assertRaisesRegex(ValueError, "Ready fallback endpoint differs"):
            observe(snapshots)

    def test_missing_source_fallback_mapping_is_visible(self):
        snapshots = list(fixtures())
        snapshots[0]["items"] = [item for item in snapshots[0]["items"]
                                  if item["metadata"]["name"] != "proxy"]
        snapshots[2]["items"] = [item for item in snapshots[2]["items"]
                                  if item["metadata"]["name"] != "proxy-slice"]
        report = observe(snapshots)
        self.assertEqual(report["unmappedFallbackDeployments"],
                         ["emergency-octelium-proxy"])
        self.assertEqual(report["counts"]["fallback-ready"], 1)

    def test_missing_native_only_service_changes_identity_hash(self):
        expected = observe(fixtures())["serviceIdentitySha256"]
        snapshots = list(fixtures())
        snapshots[0]["items"] = [item for item in snapshots[0]["items"]
                                  if item["metadata"]["name"] != "operator"]
        snapshots[2]["items"] = [item for item in snapshots[2]["items"]
                                  if item["metadata"]["name"] != "operator-slice"]
        report = observe(snapshots)
        self.assertNotEqual(report["serviceIdentitySha256"], expected)
        self.assertFalse(report["baselineQualified"])

    def test_new_unresolved_service_cannot_look_qualified(self):
        snapshots = list(fixtures())
        snapshots[0]["items"].append(service("new-service", "new-role"))
        report = observe(snapshots)
        self.assertEqual(report["counts"]["unresolved"], 1)
        self.assertFalse(report["baselineQualified"])
        self.assertEqual(report["admission"], "unproven")
        self.assertNotEqual(report["serviceIdentitySha256"],
                            observe(fixtures())["serviceIdentitySha256"])

    def test_incomplete_or_duplicate_lists_are_rejected(self):
        snapshots = list(fixtures())
        snapshots[0]["metadata"]["continue"] = "another-page"
        with self.assertRaisesRegex(ValueError, "incomplete"):
            observe(snapshots)
        snapshots = list(fixtures())
        snapshots[0]["items"].append(copy.deepcopy(snapshots[0]["items"][0]))
        with self.assertRaisesRegex(ValueError, "Service identity"):
            observe(snapshots)


if __name__ == "__main__":
    unittest.main()
