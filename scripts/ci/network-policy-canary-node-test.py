#!/usr/bin/env python3
"""Canary admission/release must preserve foreign Node metadata and taints."""

import argparse
import copy
import json
import os
import runpy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUT = runpy.run_path(str(ROOT / "scripts/network-policy-canary-node.py"))
SHA = "a" * 40
CANARY = SUT["CANARY"]
TAINT = SUT["TAINT"]
CONFIG = {"canary": {"node": "zimaboard-1",
                     "taint": f"{CANARY}=true:NoSchedule"}}


def placement():
    return {"format": 1, "verified": True, "sourceSha": SHA,
            "node": "zimaboard-1", "canaryNode": "zimaboard-1", "nodeUid": "uid",
            "bootID": "boot", "measured": True, "isolatedTaint": CONFIG["canary"]["taint"],
            "firewallBaselineEmpty": True,
            "systemDaemonSetPods": [{"namespace": "kube-system", "name": "flannel-1",
                                     "uid": "system-pod-uid"}],
            "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def cleanup():
    return {"format": 1, "stage": "owned-firewall-cleanup", "status": "verified",
            "verified": True, "sourceSha": SHA, "node": "zimaboard-1",
            "nodeUid": "uid", "bootID": "boot", "afterSha256": "b" * 64,
            "completedAt": "2026-10-19T00:00:00Z"}


def node(admitted=False):
    labels = {"foreign.example/owner": "keep"}
    taints = [{"key": "foreign.example/maintenance", "value": "yes", "effect": "NoExecute"}]
    if admitted:
        labels[CANARY] = "true"
        taints.append(copy.deepcopy(TAINT))
    return {"metadata": {"name": "zimaboard-1", "uid": "uid",
                         "resourceVersion": "10", "labels": labels},
            "spec": {"taints": taints, "unschedulable": False},
            "status": {"nodeInfo": {"bootID": "boot"},
                       "conditions": [{"type": "Ready", "status": "True"}]}}


def system_pod():
    return {"metadata": {"namespace": "kube-system", "name": "flannel-1",
                         "uid": "system-pod-uid", "ownerReferences": [
                             {"kind": "DaemonSet", "name": "kube-flannel-ds",
                              "controller": True}]},
            "spec": {"nodeName": "zimaboard-1"}}


def cleanup_pod():
    pod = system_pod()
    pod["metadata"].update({"name": "cleanup-pod", "uid": "cleanup-pod-uid"})
    pod["metadata"]["ownerReferences"][0]["name"] = SUT["CLEANUP"]["CLEANUP"]
    return pod


def apply_patch(state, operations):
    for operation in operations:
        parts = [part.replace("~1", "/").replace("~0", "~")
                 for part in operation["path"].split("/")[1:]]
        target = state
        for part in parts[:-1]:
            target = target[part]
        leaf = parts[-1]
        if operation["op"] == "test":
            assert target[int(leaf) if isinstance(target, list) else leaf] == operation["value"]
        elif isinstance(target, list):
            if operation["op"] == "add":
                assert leaf == "-"
                target.append(operation["value"])
            else:
                target.pop(int(leaf))
        elif operation["op"] == "remove":
            target.pop(leaf)
        else:
            target[leaf] = operation["value"]
    state["metadata"]["resourceVersion"] = str(int(state["metadata"]["resourceVersion"]) + 1)


class CanaryNodeTests(unittest.TestCase):
    def test_dormant_config_rejects_before_cluster_access(self):
        with patch.dict(SUT["PLATFORM"], {
                "validate_config": lambda _: {"canary": {"node": None}}}):
            with self.assertRaisesRegex(ValueError, "no admitted canary"):
                SUT["execute"](argparse.Namespace(action="admit",
                    config=ROOT / "scripts/config/platform-maintenance.json",
                    expected_sha=SHA, receipt_dir=Path("/unused"), output=Path("/unused")))

    def test_private_placement_and_cleanup_must_be_verified_and_bound(self):
        for change in ({"verified": False}, {"sourceSha": "b" * 40},
                       {"nodeUid": ""}, {"firewallBaselineEmpty": False},
                       {"systemDaemonSetPods": None},
                       {"systemDaemonSetPods": [{"namespace": "kube-system",
                                                "name": "flannel-1", "uid": ""}]},
                       {"systemDaemonSetPods": [{"namespace": "default",
                                                "name": "app-1", "uid": "app-uid"}]}):
            with self.subTest(change=change):
                receipt = placement() | change
                with self.assertRaises(ValueError):
                    SUT["validate_placement"](receipt, CONFIG, SHA, True)
        with self.assertRaisesRegex(ValueError, "cleanup receipt"):
            SUT["validate_cleanup"](cleanup() | {"verified": False}, placement(), SHA)

    def test_replaced_or_unready_node_is_rejected(self):
        for field, value in (("uid", "replacement"), ("bootID", "replacement"),
                             ("ready", "False")):
            with self.subTest(field=field):
                candidate = node()
                if field == "uid":
                    candidate["metadata"]["uid"] = value
                elif field == "bootID":
                    candidate["status"]["nodeInfo"]["bootID"] = value
                else:
                    candidate["status"]["conditions"][0]["status"] = value
                with patch.dict(SUT["CLEANUP"], {
                        "kubernetes_json": lambda *args: candidate}):
                    with self.assertRaisesRegex(ValueError, "identity, readiness"):
                        SUT["node_state"](CONFIG, placement())

    def test_default_namespace_daemonset_cannot_be_receipt_bound(self):
        app_pod = system_pod()
        app_pod["metadata"].update({"namespace": "default", "name": "app-1",
                                    "uid": "app-uid"})
        receipt = placement()
        receipt["systemDaemonSetPods"] = [{"namespace": "default", "name": "app-1",
                                           "uid": "app-uid"}]
        with self.assertRaisesRegex(ValueError, "system DaemonSet"):
            SUT["validate_placement"](receipt, CONFIG, SHA, True)
        with patch.dict(SUT["CLEANUP"], {"kubernetes_json": lambda *args:
                         {"items": [app_pod]}}):
            with self.assertRaisesRegex(ValueError, "foreign"):
                SUT["verify_live_pods"](CONFIG, receipt)

    def test_ztunnel_platform_daemonset_can_be_receipt_bound(self):
        ztunnel = system_pod()
        ztunnel["metadata"].update({"namespace": "istio-system", "name": "ztunnel-1",
                                    "uid": "ztunnel-uid"})
        ztunnel["metadata"]["ownerReferences"][0]["name"] = "ztunnel"
        receipt = placement()
        receipt["systemDaemonSetPods"] = [{"namespace": "istio-system",
                                           "name": "ztunnel-1", "uid": "ztunnel-uid"}]
        SUT["validate_placement"](receipt, CONFIG, SHA, True)
        with patch.dict(SUT["CLEANUP"], {"kubernetes_json": lambda *args:
                         {"items": [ztunnel]}}):
            SUT["verify_live_pods"](CONFIG, receipt)

    def test_other_istio_daemonset_is_rejected_even_with_exact_uid(self):
        pod = system_pod()
        pod["metadata"].update({"namespace": "istio-system", "name": "other-1",
                                "uid": "other-uid"})
        receipt = placement()
        receipt["systemDaemonSetPods"] = [{"namespace": "istio-system",
                                           "name": "other-1", "uid": "other-uid"}]
        SUT["validate_placement"](receipt, CONFIG, SHA, True)
        with patch.dict(SUT["CLEANUP"], {"kubernetes_json": lambda *args:
                         {"items": [pod]}}):
            with self.assertRaisesRegex(ValueError, "foreign"):
                SUT["verify_live_pods"](CONFIG, receipt)

    def run_action(self, action, state, remaining=False, pods=None, fail_label_patch=False,
                   cleanup_pods=None, label_inventory=None):
        commands, records, events = [], [], []
        self.last_records = records
        self.last_events = events
        cleanup_inventory = iter(([cleanup_pod()], [])) if cleanup_pods is None else None
        initial_foreign_labels = {"foreign.example/owner": "keep"}
        initial_foreign_taints = [{"key": "foreign.example/maintenance",
                                   "value": "yes", "effect": "NoExecute"}]

        def kube_json(*args):
            if args[:2] == ("get", "node"):
                return copy.deepcopy(state)
            if args[:2] == ("get", "nodes"):
                if label_inventory is not None:
                    return copy.deepcopy(label_inventory() if callable(label_inventory)
                                         else label_inventory)
                selected = [copy.deepcopy(state)] if state["metadata"]["labels"].get(CANARY) \
                    == "true" else []
                return {"items": selected}
            if (action == "release" and args[:4] == ("-n", "kube-system", "get", "pods")
                    and "--chunk-size=0" in args):
                events.append("cleanup-inventory")
                current_pods = (next(cleanup_inventory) if cleanup_inventory is not None
                                else cleanup_pods() if callable(cleanup_pods) else cleanup_pods)
                return {"items": copy.deepcopy(current_pods)}
            if args[:2] == ("get", "pods"):
                events.append("inventory")
                current_pods = pods() if callable(pods) else pods
                return {"items": copy.deepcopy([system_pod()] if current_pods is None
                                               else current_pods)}
            return {"items": []}

        def command(*args):
            if "patch" in args:
                operations = json.loads(args[args.index("-p") + 1])
                self.assertEqual(operations[0]["path"], "/metadata/resourceVersion")
                self.assertEqual(operations[1]["path"], "/metadata/uid")
                commands.append(operations)
                if fail_label_patch and any(item["path"] == SUT["LABEL_PATH"] and
                                            item["op"] == "add" for item in operations):
                    raise ValueError("simulated label patch failure")
                events.append("unlabel" if any(item["path"] == SUT["LABEL_PATH"] and
                                               item["op"] == "remove" for item in operations)
                              else "label" if any(item["path"] == SUT["LABEL_PATH"] and
                                                  item["op"] == "add" for item in operations)
                              else "taint")
                apply_patch(state, operations)
                return json.dumps(state)
            return ""

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {"GITHUB_RUN_ID": "123"}), patch.dict(SUT["PLATFORM"], {
                    "validate_config": lambda _: CONFIG,
                    "protected_context": lambda _: None,
                    "private_directory": lambda path: path,
                    "private_output": lambda path: path,
                    "read_private_json": lambda path: placement() if path.name ==
                    "placement.json" else cleanup()}), patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": kube_json, "command": command,
                    "inspect_cluster": lambda *_: ("cleanup-pod", "pod-uid"),
                    "snapshot": lambda *_: {"backend": "nft"},
                    "cleanup_plan": lambda *_: ([("iptables-nft", "-D", "owned")] if
                                                 remaining else [], 0, 0),
                    "write_record": lambda _path, record, replace=False:
                    records.append(copy.deepcopy(record))}), patch.object(SUT["time"],
                    "sleep", lambda _: None), patch.dict(
                    SUT["execute"].__globals__, {"require_current_main": lambda _: None}):
            args = argparse.Namespace(action=action,
                                      config=ROOT / "scripts/config/platform-maintenance.json",
                                      expected_sha=SHA, receipt_dir=Path(directory),
                                      output=Path(directory) / "result.json")
            result = SUT["execute"](args)
        self.assertEqual(state["metadata"]["labels"]["foreign.example/owner"],
                         initial_foreign_labels["foreign.example/owner"])
        self.assertEqual(state["spec"]["taints"][0], initial_foreign_taints[0])
        self.assertEqual([item["status"] for item in records], ["started", "verified"])
        self.assertTrue(result["verified"])
        return commands, state

    def test_admit_adds_only_owned_taint_then_label(self):
        commands, state = self.run_action("admit", node())
        self.assertEqual(len(commands), 2)
        self.assertEqual([item["path"] for item in commands[0][2:]],
                         ["/spec/taints/-"])
        self.assertEqual([item["path"] for item in commands[1][2:]],
                         [SUT["LABEL_PATH"]])
        self.assertEqual(self.last_events, ["taint", "inventory", "label", "inventory"])
        self.assertEqual(state["metadata"]["labels"][CANARY], "true")
        self.assertEqual(state["spec"]["taints"][-1], TAINT)

    def test_release_removes_only_owned_label_then_taint(self):
        commands, state = self.run_action("release", node(admitted=True))
        self.assertEqual(len(commands), 2)
        self.assertEqual([(item["op"], item["path"]) for item in commands[0][2:]],
                         [("test", SUT["LABEL_PATH"]), ("test", "/spec/taints/1"),
                          ("remove", SUT["LABEL_PATH"])])
        self.assertEqual([(item["op"], item["path"]) for item in commands[1][2:]],
                         [("test", "/spec/taints/1"), ("remove", "/spec/taints/1")])
        self.assertEqual(self.last_events, ["unlabel", "cleanup-inventory",
                                            "cleanup-inventory", "taint"])
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(len(state["spec"]["taints"]), 1)

    def test_release_retains_taint_while_cleanup_pod_remains(self):
        state = node(admitted=True)
        with patch.object(SUT["time"], "monotonic", side_effect=[0, 121]):
            with self.assertRaisesRegex(ValueError, "cleanup Pod remains"):
                self.run_action("release", state, cleanup_pods=lambda: [cleanup_pod()])
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual(self.last_events, ["unlabel", "cleanup-inventory"])
        self.assertEqual([record["status"] for record in self.last_records],
                         ["started", "interrupted"])

    def test_release_retains_taint_for_cleanup_pod_on_another_node(self):
        state = node(admitted=True)
        replacement = cleanup_pod()
        replacement["metadata"]["name"] = "cleanup-pod-2"
        replacement["spec"]["nodeName"] = "zimaboard-2"
        with patch.object(SUT["time"], "monotonic", side_effect=[0, 121]):
            with self.assertRaisesRegex(ValueError, "cleanup Pod remains"):
                self.run_action("release", state, cleanup_pods=lambda: [replacement])
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual([record["status"] for record in self.last_records],
                         ["started", "interrupted"])

    def test_release_refuses_remaining_firewall(self):
        with self.assertRaisesRegex(ValueError, "owned firewall objects remain"):
            self.run_action("release", node(admitted=True), remaining=True)

    def test_release_refuses_unmarked_node_without_live_firewall_proof(self):
        with self.assertRaisesRegex(ValueError, "live firewall proof unavailable"):
            self.run_action("release", node())

    def test_taint_only_admission_recovers_after_fresh_inventory(self):
        state = node()
        state["spec"]["taints"].append(copy.deepcopy(TAINT))
        commands, state = self.run_action("admit", state)
        self.assertEqual(len(commands), 1)
        self.assertEqual(self.last_events, ["inventory", "label", "inventory"])
        self.assertEqual(state["metadata"]["labels"][CANARY], "true")

    def test_admit_refuses_label_only_or_already_admitted(self):
        for state in (node(admitted=True), node()):
            if CANARY not in state["metadata"]["labels"]:
                state["metadata"]["labels"][CANARY] = "true"
            with self.assertRaisesRegex(ValueError, "already labeled"):
                self.run_action("admit", state)

    def test_admit_refuses_another_labeled_node_before_mutation(self):
        state = node()
        other = {"metadata": {"name": "zimaboard-2", "uid": "other-uid",
                              "labels": {CANARY: "true"}}}
        with self.assertRaisesRegex(ValueError, "another Node"):
            self.run_action("admit", state, label_inventory={"items": [other]})
        self.assertEqual(len(state["spec"]["taints"]), 1)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(self.last_records, [])

    def test_admit_rechecks_other_node_after_taint_before_label(self):
        state = node()
        other = {"metadata": {"name": "zimaboard-2", "uid": "other-uid",
                              "labels": {CANARY: "true"}}}
        inventories = iter(({"items": []}, {"items": [other]}))
        with self.assertRaisesRegex(ValueError, "another Node"):
            self.run_action("admit", state, label_inventory=lambda: next(inventories))
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual([item["status"] for item in self.last_records],
                         ["started", "interrupted"])

    def test_admit_rolls_back_label_if_other_node_appears_after_patch(self):
        state = node()
        other = {"metadata": {"name": "zimaboard-2", "uid": "other-uid",
                              "labels": {CANARY: "true"}}}
        calls = 0

        def inventory():
            nonlocal calls
            calls += 1
            return {"items": [copy.deepcopy(state), other] if calls == 3 else []}

        with self.assertRaisesRegex(ValueError, "another Node"):
            self.run_action("admit", state, label_inventory=inventory)
        self.assertEqual(calls, 3)
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual([item["status"] for item in self.last_records],
                         ["started", "interrupted"])

    def test_label_inventory_is_complete_and_well_formed(self):
        invalid = ({}, {"items": None}, {"items": [], "metadata": {"continue": "next"}},
                   {"items": [{"metadata": {"name": "other", "uid": "uid",
                                            "labels": {CANARY: "false"}}}]},
                   {"items": [{"metadata": {"name": "other", "uid": "",
                                            "labels": {CANARY: "true"}}}]})
        for listing in invalid:
            with self.subTest(listing=listing), patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": lambda *args: listing}):
                with self.assertRaisesRegex(ValueError, "canary label inventory"):
                    SUT["require_exclusive_canary_label"](CONFIG, placement(), False)

    def test_stale_or_foreign_pod_blocks_label_after_taint(self):
        stale = system_pod()
        stale["metadata"]["uid"] = "replacement-uid"
        foreign = system_pod()
        foreign["metadata"].update({"namespace": "default", "name": "unrelated",
                                    "uid": "foreign-uid", "ownerReferences": []})
        cleanup_pod = system_pod()
        cleanup_pod["metadata"]["ownerReferences"][0]["name"] = SUT["CLEANUP"]["CLEANUP"]
        for pods in ([stale], [system_pod(), foreign], [cleanup_pod]):
            with self.subTest(pods=pods):
                state = node()
                with self.assertRaisesRegex(ValueError, "inventory|foreign"):
                    self.run_action("admit", state, pods=pods)
                self.assertNotIn(CANARY, state["metadata"]["labels"])
                self.assertEqual(state["spec"]["taints"][-1], TAINT)
                self.assertEqual([item["status"] for item in self.last_records],
                                 ["started", "interrupted"])

    def test_interrupted_taint_only_state_can_retry(self):
        state = node()
        with self.assertRaisesRegex(ValueError, "simulated label patch failure"):
            self.run_action("admit", state, fail_label_patch=True)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual([item["status"] for item in self.last_records],
                         ["started", "interrupted"])
        self.run_action("admit", state)
        self.assertEqual(self.last_events, ["inventory", "label", "inventory"])

    def test_new_occupant_after_label_removes_label(self):
        state = node()
        foreign = system_pod()
        foreign["metadata"].update({"namespace": "default", "name": "foreign",
                                    "uid": "foreign-uid", "ownerReferences": []})
        inventories = iter(([system_pod()], [system_pod(), foreign]))
        with self.assertRaisesRegex(ValueError, "foreign"):
            self.run_action("admit", state, pods=lambda: next(inventories))
        self.assertEqual(self.last_events,
                         ["taint", "inventory", "label", "inventory", "unlabel"])
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual([item["status"] for item in self.last_records],
                         ["started", "interrupted"])

    def test_partial_release_is_rejected(self):
        state = node(admitted=True)
        state["metadata"]["labels"].pop(CANARY)
        with self.assertRaisesRegex(ValueError, "label and isolation taint differ"):
            self.run_action("release", state)

    def test_rv_test_is_sent_with_owned_patch(self):
        state = node()
        seen = []
        with patch.dict(SUT["CLEANUP"], {"command": lambda *args: seen.append(args)}), \
                patch.dict(SUT["patch"].__globals__, {"require_current_main": lambda _: None}):
            SUT["patch"](state, [{"op": "add", "path": "/spec/taints/-", "value": TAINT}], SHA)
        operations = json.loads(seen[0][seen[0].index("-p") + 1])
        state["metadata"]["resourceVersion"] = "11"
        with self.assertRaises(AssertionError):
            apply_patch(state, operations)


if __name__ == "__main__":
    unittest.main()
