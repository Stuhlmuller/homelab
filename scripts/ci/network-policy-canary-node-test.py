#!/usr/bin/env python3
"""Canary admission/release must preserve foreign Node metadata and taints."""

import argparse
import copy
import json
import os
import runpy
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUT = runpy.run_path(str(ROOT / "scripts/network-policy-canary-node.py"))
SHA = "a" * 40
EVIDENCE_SHA = "b" * 40
CANARY = SUT["CANARY"]
TAINT = SUT["TAINT"]
CONFIG = {"canary": {"node": "zimaboard-1",
                     "taint": f"{CANARY}=true:NoSchedule"}}


def placement(source_sha=SHA):
    return {"format": 1, "verified": True, "sourceSha": source_sha,
            "placementRunId": "456",
            "node": "zimaboard-1", "canaryNode": "zimaboard-1", "nodeUid": "uid",
            "bootID": "boot", "measured": True, "isolatedTaint": CONFIG["canary"]["taint"],
            "firewallBaselineEmpty": True,
            "baselineSourceSha": source_sha, "baselineCaptureVersionId": "version-1",
            "baselineRunId": "123", "baselineCaptureSha256": "a" * 64,
            "baselineCapturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "systemDaemonSetPods": [{"namespace": "kube-system", "name": "flannel-1",
                                     "uid": "system-pod-uid"}],
            "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def cleanup():
    return {"format": 1, "stage": "owned-firewall-cleanup", "status": "verified",
            "verified": True, "sourceSha": SHA, "node": "zimaboard-1",
            "nodeUid": "uid", "bootID": "boot", "captureRunId": "456",
            "beforeSha256": "c" * 64, "afterSha256": "b" * 64,
            "completedAt": "2026-10-19T00:00:00Z"}


def ownership():
    return {"format": 1, "verified": True, "sourceSha": SHA,
            "evidenceSourceSha": EVIDENCE_SHA, "captureRunId": "456",
            "admissionRunId": "123", "placementRunId": "456",
            "placementVersionId": "version-1",
            "node": "zimaboard-1", "nodeUid": "uid", "bootID": "boot",
            "snapshotSha256": "c" * 64, "reviewedAt": "2026-10-19T00:00:00Z"}


def admission_attempt():
    return {"format": 1, "stage": "canary-admit", "status": "attempted",
            "verified": False, "sourceSha": SHA, "runId": "123",
            "node": "zimaboard-1", "nodeUid": "uid", "bootID": "boot",
            "placementRunId": "456", "placementVersionId": "version-1"}


def recovery_proof():
    return {"format": 1, "stage": "firewall-recovery-proof", "status": "verified",
            "verified": True, "sourceSha": SHA, "runId": "789",
            "admissionRunId": "123", "placementRunId": "456",
            "placementVersionId": "version-1", "node": "zimaboard-1",
            "nodeUid": "uid", "bootID": "boot", "firewallBaselineEmpty": True,
            "ownedChains": 0, "ownedSets": 0, "podDeleted": True,
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "snapshotSha256": "d" * 64,
            "captureKey": f"openclaw-enterprise/platform/{SHA}/789/firewall-recovery-capture.json"}


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
    def test_admission_refuses_remaining_or_incomplete_preflight_pod(self):
        for raw, listing in (("{\"kind\":\"Pod\"}", {"metadata": {}, "items": []}),
                             ("", {"metadata": {}, "items": [{"metadata":
                                {"name": "kube-router-firewall-baseline"}}]}),
                             ("", {"items": []})):
            with self.subTest(raw=raw, listing=listing), patch.dict(SUT["CLEANUP"], {
                    "command": lambda *_: raw,
                    "kubernetes_json": lambda *_: listing}):
                with self.assertRaisesRegex(ValueError, "preflight"):
                    SUT["require_runtime_absent"](True)

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
                       {"baselineRunId": ""}, {"baselineCaptureSha256": "bad"},
                       {"baselineSourceSha": "f" * 40},
                       {"baselineCaptureVersionId": ""},
                       {"baselineCapturedAt": "2026-10-01T00:00:00Z"},
                       {"capturedAt": "2026-10-01T00:00:00Z"},
                       {"systemDaemonSetPods": None},
                       {"systemDaemonSetPods": [{"namespace": "kube-system",
                                                "name": "flannel-1", "uid": ""}]},
                       {"systemDaemonSetPods": [{"namespace": "default",
                                                "name": "app-1", "uid": "app-uid"}]}):
            with self.subTest(change=change):
                receipt = placement() | change
                with self.assertRaises(ValueError):
                    SUT["validate_placement"](receipt, CONFIG, SHA, True)
        with patch.dict(SUT["CLEANUP"], {
                "require_firewall_removal_transition": lambda *_: None}):
            with self.assertRaisesRegex(ValueError, "cleanup receipt"):
                SUT["validate_cleanup"](cleanup() | {"verified": False}, ownership(),
                                        placement(EVIDENCE_SHA), CONFIG, SHA)
            for changed in ({"captureRunId": "789"}, {"beforeSha256": "d" * 64}):
                with self.subTest(changed=changed), self.assertRaisesRegex(
                        ValueError, "cleanup receipt"):
                    SUT["validate_cleanup"](cleanup() | changed, ownership(),
                                            placement(EVIDENCE_SHA), CONFIG, SHA)
            for changed in ({"verified": False}, {"sourceSha": "d" * 40},
                            {"nodeUid": "replaced"}, {"snapshotSha256": "d" * 64},
                            {"admissionRunId": ""}, {"placementRunId": "789"},
                            {"placementVersionId": ""}):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    SUT["validate_cleanup"](cleanup(), ownership() | changed,
                                            placement(EVIDENCE_SHA), CONFIG, SHA)

    def test_release_refuses_stale_main_before_private_receipt_or_cluster_access(self):
        with patch.dict(SUT["PLATFORM"], {
                "validate_config": lambda _: CONFIG,
                "protected_context": lambda _: None,
                "private_directory": lambda _: self.fail("receipt read before main check")}), \
                patch.dict(SUT["execute"].__globals__, {
                    "require_current_main": lambda _: (_ for _ in ()).throw(
                        ValueError("source is not exact current main"))}):
            with self.assertRaisesRegex(ValueError, "exact current main"):
                SUT["execute"](argparse.Namespace(
                    action="release", config=ROOT / "scripts/config/platform-maintenance.json",
                    expected_sha=SHA, receipt_dir=Path("/unused"), output=Path("/unused")))

    def test_release_accepts_invariant_history_with_fresh_receipts(self):
        manifest = "clusters/homelab/platform/network-policy/kustomization.yaml"
        application = "IaC/homelab/us-west-2/apps/platform-network-policy/stack.hcl"
        canary_manifest = "clusters/homelab/platform/network-policy/canary/kustomization.yaml"
        canary_application = "IaC/homelab/us-west-2/apps/platform-network-policy-canary/stack.hcl"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (manifest, application, canary_manifest, canary_application):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            dormant = "        enabled = false\n        prune   = false\n"
            active = "        enabled = true\n        prune   = true\n"
            empty_active = ("        enabled    = true\n        prune      = true\n"
                            "        allowEmpty = true\n")
            for name, variants in ((application, (dormant, active, empty_active)),
                                   (canary_application, (dormant, active, empty_active))):
                target = root / name
                source = target.read_text()
                matches = [variant for variant in variants if source.count(variant) == 1]
                self.assertEqual(len(matches), 1, f"unreviewed source state: {name}")
                target.write_text(source.replace(matches[0], dormant))
            (root / manifest).write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
                "resources:\n  - daemonset.yaml\n")
            (root / canary_manifest).write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")

            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      capture_output=True, text=True).stdout.strip()

            def commit(message):
                git("add", "-A")
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-qm", message)
                return git("rev-parse", "HEAD")

            git("init", "-q")
            (root / canary_manifest).write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
                "resources:\n  - fixtures.yaml\n")
            source = (root / application).read_text()
            (root / application).write_text(source.replace(dormant, active))
            source = (root / canary_application).read_text()
            (root / canary_application).write_text(source.replace(
                "        enabled = false\n        prune   = false\n",
                "        enabled = true\n        prune   = true\n"))
            qualify_sha = commit("qualified canary")
            (root / canary_manifest).write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
                "resources: []\n")
            source = (root / canary_application).read_text()
            (root / canary_application).write_text(source.replace(
                "        enabled = true\n        prune   = true\n",
                "        enabled    = true\n        prune      = true\n"
                "        allowEmpty = true\n"))
            commit("pruned fixtures")
            (root / manifest).write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
                "resources: []\n")
            source = (root / application).read_text()
            (root / application).write_text(source.replace(
                "        enabled = true\n        prune   = true\n",
                "        enabled    = true\n        prune      = true\n"
                "        allowEmpty = true\n"))
            removal_sha = commit("pruned firewall")
            evidence = placement(qualify_sha)
            verified_ownership = ownership() | {"sourceSha": removal_sha,
                                                "evidenceSourceSha": qualify_sha}
            verified_cleanup = cleanup() | {"sourceSha": removal_sha}
            transition = SUT["CLEANUP"]["require_firewall_removal_transition"]
            with patch.dict(transition.__globals__, {"ROOT": root}):
                SUT["validate_cleanup"](verified_cleanup, verified_ownership,
                                        evidence, CONFIG, removal_sha)
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "unrelated")
                stale_sha = git("rev-parse", "HEAD")
                with self.assertRaisesRegex(ValueError, "reviewed firewall ownership receipt"):
                    SUT["validate_cleanup"](verified_cleanup, verified_ownership,
                                            evidence, CONFIG, stale_sha)
                SUT["validate_cleanup"](verified_cleanup | {"sourceSha": stale_sha},
                                        verified_ownership | {"sourceSha": stale_sha},
                                        evidence, CONFIG, stale_sha)
                git("reset", "--hard", qualify_sha)
                (root / canary_manifest).write_text(
                    "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
                    "resources: []\n")
                source = (root / canary_application).read_text()
                (root / canary_application).write_text(source.replace(
                    "        enabled = true\n        prune   = true\n",
                    "        enabled    = true\n        prune      = true\n"
                    "        allowEmpty = true\n"))
                (root / "unrelated.txt").write_text("source drift\n")
                commit("fixture prune with source drift")
                (root / manifest).write_text(
                    "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
                    "resources: []\n")
                source = (root / application).read_text()
                (root / application).write_text(source.replace(
                    "        enabled = true\n        prune   = true\n",
                    "        enabled    = true\n        prune      = true\n"
                    "        allowEmpty = true\n"))
                drift_sha = commit("firewall prune after source drift")
                with self.assertRaisesRegex(ValueError, "fixture removal differs"):
                    SUT["validate_cleanup"](verified_cleanup | {"sourceSha": drift_sha},
                                            verified_ownership | {"sourceSha": drift_sha},
                                            evidence, CONFIG, drift_sha)

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
                         {"metadata": {}, "items": [app_pod]}}):
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
                         {"metadata": {}, "items": [ztunnel]}}):
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
                         {"metadata": {}, "items": [pod]}}):
            with self.assertRaisesRegex(ValueError, "foreign"):
                SUT["verify_live_pods"](CONFIG, receipt)

    def test_canary_pod_inventory_rejects_incomplete_or_terminating_entries(self):
        for listing in ({"items": [system_pod()]},
                        {"metadata": {"continue": "next"}, "items": [system_pod()]},
                        {"metadata": {}, "items": [system_pod() | {
                            "metadata": system_pod()["metadata"] | {
                                "deletionTimestamp": "2026-10-20T00:00:00Z"}}]}):
            with self.subTest(listing=listing), patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": lambda *args: listing}):
                with self.assertRaisesRegex(ValueError, "incomplete|foreign"):
                    SUT["verify_live_pods"](CONFIG, placement())

    def run_action(self, action, state, remaining=False, pods=None, fail_label_patch=False,
                   cleanup_pods=None, label_inventory=None, capacity_error=None,
                   selected_run="456", selected_version="version-1", loaded_run=None):
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
            if (args[:4] == ("-n", "kube-system", "get", "pods") and
                    "app.kubernetes.io/name=kube-router-firewall-baseline" in args):
                return {"metadata": {}, "items": []}
            if args[:2] == ("get", "nodes"):
                if label_inventory is not None:
                    return copy.deepcopy(label_inventory() if callable(label_inventory)
                                         else label_inventory)
                selected = [copy.deepcopy(state)] if state["metadata"]["labels"].get(CANARY) \
                    == "true" else []
                return {"metadata": {}, "items": selected}
            if (action == "release" and args[:4] == ("-n", "kube-system", "get", "pods")
                    and "--chunk-size=0" in args and "-l" not in args):
                events.append("cleanup-inventory")
                current_pods = (next(cleanup_inventory) if cleanup_inventory is not None
                                else cleanup_pods() if callable(cleanup_pods) else cleanup_pods)
                return copy.deepcopy(current_pods if isinstance(current_pods, dict)
                                     else {"metadata": {}, "items": current_pods})
            if args[:2] == ("get", "pods"):
                events.append("inventory")
                current_pods = pods() if callable(pods) else pods
                return {"metadata": {}, "items": copy.deepcopy(
                    [system_pod()] if current_pods is None else current_pods)}
            return {"metadata": {}, "items": []}

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

        def capacity_gate(*_):
            if capacity_error:
                raise capacity_error

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {"GITHUB_RUN_ID": "123"}), patch.dict(SUT["PLATFORM"], {
                    "validate_config": lambda _: CONFIG,
                    "protected_context": lambda _: None,
                    "private_directory": lambda path: path,
                    "private_output": lambda path: path,
                    "read_private_json": lambda path: (placement(EVIDENCE_SHA if action ==
                    "release" else SHA) | {"placementRunId": loaded_run or selected_run}
                    if path.name == "placement.json" else
                    ownership() if path.name == "firewall-ownership.json" else cleanup())}), \
                    patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": kube_json, "command": command,
                    "require_firewall_removal_transition": lambda *_: None,
                    "inspect_cluster": lambda *_: ("cleanup-pod", "pod-uid"),
                    "snapshot": lambda *_: {"backend": "nft"},
                    "cleanup_plan": lambda *_: ([("iptables-nft", "-D", "owned")] if
                                                 remaining else [], 0, 0),
                    "write_record": lambda _path, record, replace=False:
                    records.append(copy.deepcopy(record))}), patch.object(SUT["time"],
                    "sleep", lambda _: None), patch.dict(
                    SUT["execute"].__globals__, {
                        "require_current_main": lambda _: None,
                        "require_fresh_capacity": capacity_gate}):
            args = argparse.Namespace(action=action,
                                      config=ROOT / "scripts/config/platform-maintenance.json",
                                      expected_sha=SHA, receipt_dir=Path(directory),
                                      output=Path(directory) / "result.json", bucket="bucket",
                                      placement_run_id=selected_run if action == "admit" else None,
                                      placement_version_id=selected_version if action == "admit" else None)
            if capacity_error:
                with self.assertRaisesRegex(ValueError, "headroom"):
                    SUT["execute"](args)
                self.assertFalse(commands)
                self.assertEqual([item["status"] for item in records],
                                 ["started", "interrupted"])
                return commands, state
            result = SUT["execute"](args)
        self.assertEqual(state["metadata"]["labels"]["foreign.example/owner"],
                         initial_foreign_labels["foreign.example/owner"])
        self.assertEqual(state["spec"]["taints"][0], initial_foreign_taints[0])
        self.assertEqual([item["status"] for item in records], ["started", "verified"])
        self.assertTrue(result["verified"])
        return commands, state

    def run_recovery(self, state, *, selected=None, attempt=None, proof=None,
                     pods=None, expected_error=None):
        selected = selected if selected is not None else placement()
        attempt = attempt if attempt is not None else admission_attempt()
        proof = proof if proof is not None else recovery_proof()
        commands, records = [], []
        self.last_recovery_commands = commands
        self.last_recovery_records = records

        def kube_json(*args):
            if args[:2] == ("get", "node"):
                return copy.deepcopy(state)
            if args[:2] == ("get", "nodes"):
                selected_nodes = [copy.deepcopy(state)] if state["metadata"]["labels"].get(
                    CANARY) == "true" else []
                return {"metadata": {}, "items": selected_nodes}
            if args[:2] == ("get", "pods"):
                current = pods() if callable(pods) else pods
                return {"metadata": {}, "items": copy.deepcopy(
                    [system_pod()] if current is None else current)}
            return {"metadata": {}, "items": []}

        def command(*args):
            if "patch" in args:
                operations = json.loads(args[args.index("-p") + 1])
                commands.append(operations)
                apply_patch(state, operations)
                return json.dumps(state)
            return ""

        with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"GITHUB_RUN_ID": "789"}), patch.dict(SUT["PLATFORM"], {
                    "validate_config": lambda _: CONFIG,
                    "protected_context": lambda _: None,
                    "private_directory": lambda path: path,
                    "private_output": lambda path: path,
                    "fresh_recovery_time": lambda *_: self.fail(
                        "recovery must not require fresh placement"),
                    "read_private_json": lambda path: (selected if path.name ==
                        "placement.json" else attempt if path.name ==
                        "admission-attempt.json" else proof)}), patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": kube_json, "command": command,
                    "write_record": lambda _path, record, replace=False:
                    records.append(copy.deepcopy(record))}), patch.dict(
                    SUT["recover"].__globals__, {
                        "require_current_main": lambda _: None,
                        "require_fresh_capacity": lambda *_: self.fail(
                            "recovery must not refresh capacity")}):
            args = argparse.Namespace(
                action="recover", config=ROOT / "scripts/config/platform-maintenance.json",
                expected_sha=SHA, receipt_dir=Path(directory),
                output=Path(directory) / "result.json", bucket=None,
                admission_run_id="123", placement_run_id="456",
                placement_version_id="version-1")
            if expected_error:
                with self.assertRaisesRegex(ValueError, expected_error):
                    SUT["recover"](args)
                return commands, records, state
            result = SUT["recover"](args)
        self.assertTrue(result["verified"])
        return commands, records, state

    def test_recover_expired_admission_removes_only_owned_label_then_taint(self):
        selected = placement()
        selected["capturedAt"] = "2026-01-01T00:00:00Z"
        selected["baselineCapturedAt"] = "2026-01-01T00:00:00Z"
        commands, records, state = self.run_recovery(node(admitted=True), selected=selected)
        self.assertEqual(len(commands), 2)
        self.assertEqual([operation["path"] for operation in commands[0][:2]],
                         ["/metadata/resourceVersion", "/metadata/uid"])
        self.assertEqual([(operation["op"], operation["path"])
                          for operation in commands[0][2:]],
                         [("test", SUT["LABEL_PATH"]), ("test", "/spec/taints/1"),
                          ("remove", SUT["LABEL_PATH"])])
        self.assertEqual([(operation["op"], operation["path"])
                          for operation in commands[1][2:]],
                         [("test", "/spec/taints/1"), ("remove", "/spec/taints/1")])
        self.assertEqual(state["metadata"]["labels"], {"foreign.example/owner": "keep"})
        self.assertEqual(state["spec"]["taints"], [{"key": "foreign.example/maintenance",
                                                   "value": "yes", "effect": "NoExecute"}])
        self.assertEqual([record["status"] for record in records], ["started", "verified"])
        self.assertEqual(records[-1]["stage"], "canary-admit-recover")
        self.assertEqual(records[-1]["firewallCaptureKey"], recovery_proof()["captureKey"])

    def test_recover_taint_only_or_already_clean_is_idempotent(self):
        taint_only = node()
        taint_only["spec"]["taints"].append(copy.deepcopy(TAINT))
        commands, _, state = self.run_recovery(taint_only)
        self.assertEqual(len(commands), 1)
        self.assertNotIn(TAINT, state["spec"]["taints"])
        commands, _, _ = self.run_recovery(state)
        self.assertEqual(commands, [])

    def test_recover_rejects_forged_selection_or_missing_firewall_proof(self):
        for evidence, changes, error in (
                ("attempt", {"sourceSha": EVIDENCE_SHA}, "admission attempt"),
                ("attempt", {"runId": "124"}, "admission attempt"),
                ("attempt", {"nodeUid": "other"}, "admission attempt"),
                ("attempt", {"placementVersionId": "forged"}, "admission attempt"),
                ("proof", {"runId": "788"}, "same-run empty firewall"),
                ("proof", {"admissionRunId": "124"}, "same-run empty firewall"),
                ("proof", {"placementRunId": "457"}, "same-run empty firewall"),
                ("proof", {"placementVersionId": "forged"}, "same-run empty firewall"),
                ("proof", {"nodeUid": "other"}, "same-run empty firewall"),
                ("proof", {"firewallBaselineEmpty": False}, "same-run empty firewall"),
                ("proof", {"podDeleted": False}, "same-run empty firewall"),
                ("proof", {"completedAt": (datetime.now(timezone.utc) -
                             timedelta(minutes=10)).isoformat()}, "stale"),
                ("proof", {"completedAt": "2026-10-25T00:00:00"}, "invalid completion time"),
                ("proof", {"captureKey": "unrelated"}, "same-run empty firewall")):
            with self.subTest(evidence=evidence, changes=changes):
                kwargs = {evidence: (admission_attempt() if evidence == "attempt" else
                                     recovery_proof()) | changes}
                commands, records, _ = self.run_recovery(
                    node(admitted=True), expected_error=error, **kwargs)
                self.assertEqual((commands, records), ([], []))

    def test_recover_rejects_unrelated_node_or_foreign_pod_before_mutation(self):
        replaced = node(admitted=True)
        replaced["metadata"]["uid"] = "replacement"
        commands, records, _ = self.run_recovery(replaced, expected_error="identity")
        self.assertEqual((commands, records), ([], []))
        unisolated = node(admitted=True)
        unisolated["spec"]["taints"].pop()
        commands, records, _ = self.run_recovery(unisolated,
                                                expected_error="unisolated canary")
        self.assertEqual((commands, records), ([], []))
        foreign = system_pod()
        foreign["metadata"].update({"namespace": "default", "name": "foreign",
                                    "uid": "foreign-uid", "ownerReferences": []})
        commands, records, _ = self.run_recovery(
            node(admitted=True), pods=[system_pod(), foreign], expected_error="foreign")
        self.assertEqual((commands, records), ([], []))

    def test_recover_keeps_taint_if_foreign_pod_arrives_after_unlabel(self):
        inventories = iter(([system_pod()], [system_pod(), system_pod() | {
            "metadata": system_pod()["metadata"] | {
                "namespace": "default", "name": "foreign", "uid": "foreign-uid",
                "ownerReferences": []}}]))
        commands, records, state = self.run_recovery(
            node(admitted=True), pods=lambda: next(inventories), expected_error="foreign")
        self.assertEqual(len(commands), 1)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual([record["status"] for record in records],
                         ["started", "interrupted"])

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
        self.assertEqual(self.last_records[-1]["placementRunId"], "456")
        self.assertEqual(self.last_records[-1]["placementVersionId"], "version-1")

    def test_admit_rejects_capacity_spike_before_node_mutation(self):
        commands, state = self.run_action("admit", node(),
                                          capacity_error=ValueError("memory headroom"))
        self.assertFalse(commands)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertNotIn(TAINT, state["spec"]["taints"])

    def test_admit_rejects_different_loaded_placement_before_mutation(self):
        state = node()
        with self.assertRaisesRegex(ValueError, "selected placement run"):
            self.run_action("admit", state, loaded_run="999")
        self.assertEqual(self.last_records, [])
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertNotIn(TAINT, state["spec"]["taints"])

    def test_admission_check_runs_read_only_placement_mode(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                SUT["subprocess"], "run") as run:
            args = argparse.Namespace(config=ROOT / "scripts/config/platform-maintenance.json",
                                      expected_sha=SHA, bucket="bucket",
                                      placement_run_id="456", placement_version_id="version-1")
            SUT["require_fresh_capacity"](args, Path(directory))
            command = run.call_args.args[0]
            self.assertEqual(command[2], str(ROOT / "scripts/network-policy-placement.py"))
            self.assertEqual(command[-2:], ["--check-placement",
                                           str(Path(directory) / "placement.json")])
            self.assertEqual(run.call_args.kwargs["check"], True)
            self.assertIn("--bucket", command)
            self.assertEqual(command[command.index("--placement-run-id") + 1], "456")
            self.assertEqual(command[command.index("--placement-version-id") + 1],
                             "version-1")

    def test_release_removes_only_owned_label_then_taint(self):
        commands, state = self.run_action("release", node(admitted=True))
        self.assertEqual(len(commands), 2)
        self.assertEqual([(item["op"], item["path"]) for item in commands[0][2:]],
                         [("test", SUT["LABEL_PATH"]), ("test", "/spec/taints/1"),
                          ("remove", SUT["LABEL_PATH"])])
        self.assertEqual([(item["op"], item["path"]) for item in commands[1][2:]],
                         [("test", "/spec/taints/1"), ("remove", "/spec/taints/1")])
        self.assertEqual(self.last_events, ["unlabel", "cleanup-inventory",
                                            "cleanup-inventory", "inventory", "taint"])
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

    def test_release_rejects_foreign_pod_arriving_during_cleanup_wait(self):
        state = node(admitted=True)
        assigned = [system_pod()]
        calls = 0

        def cleanup_inventory():
            nonlocal calls
            calls += 1
            if calls == 1:
                return [cleanup_pod()]
            foreign = system_pod()
            foreign["metadata"].update({"namespace": "default", "name": "foreign",
                                        "uid": "foreign-uid", "ownerReferences": []})
            assigned.append(foreign)
            return []

        with self.assertRaisesRegex(ValueError, "foreign"):
            self.run_action("release", state, pods=lambda: assigned,
                            cleanup_pods=cleanup_inventory)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual(self.last_events, ["unlabel", "cleanup-inventory",
                                            "cleanup-inventory", "inventory"])
        self.assertEqual([record["status"] for record in self.last_records],
                         ["started", "interrupted"])

    def test_release_rejects_incomplete_cleanup_pod_inventory(self):
        state = node(admitted=True)
        with self.assertRaisesRegex(ValueError, "cleanup Pod inventory is incomplete"):
            self.run_action("release", state, cleanup_pods=lambda: {
                "metadata": {"continue": "next"}, "items": []})
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual(self.last_events, ["unlabel", "cleanup-inventory"])

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
            self.run_action("admit", state, label_inventory={"metadata": {}, "items": [other]})
        self.assertEqual(len(state["spec"]["taints"]), 1)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(self.last_records, [])

    def test_admit_rechecks_other_node_after_taint_before_label(self):
        state = node()
        other = {"metadata": {"name": "zimaboard-2", "uid": "other-uid",
                              "labels": {CANARY: "true"}}}
        inventories = iter(({"metadata": {}, "items": []},
                            {"metadata": {}, "items": [other]}))
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
            return {"metadata": {},
                    "items": [copy.deepcopy(state), other] if calls == 3 else []}

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
        self.run_action("admit", state, selected_run="457", selected_version="version-2")
        self.assertEqual(self.last_events, ["inventory", "label", "inventory"])
        self.assertEqual(self.last_records[-1]["placementRunId"], "457")
        self.assertEqual(self.last_records[-1]["placementVersionId"], "version-2")

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
