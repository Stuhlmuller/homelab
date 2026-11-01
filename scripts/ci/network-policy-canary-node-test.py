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
CONFIG = {"canary": {"node": "zimaboard-2",
                     "taint": f"{CANARY}=true:NoSchedule"}}


def placement(source_sha=SHA):
    return {"format": 1, "verified": True, "sourceSha": source_sha,
            "placementRunId": "456",
            "node": "zimaboard-2", "canaryNode": "zimaboard-2", "nodeUid": "uid",
            "bootID": "boot", "measured": True, "isolatedTaint": CONFIG["canary"]["taint"],
            "fixtureNode": SUT["FIXTURE_NODE"], "fixtureNodeUid": "fixture-uid",
            "fixtureBootID": "fixture-boot",
            "fixtureCapacity": {"fixtureImageCached": False},
            "firewallBaselineEmpty": True,
            "baselineSourceSha": source_sha, "baselineCaptureVersionId": "version-1",
            "baselineRunId": "123", "baselineCaptureSha256": "a" * 64,
            "baselineCapturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "systemDaemonSetPods": [{"namespace": "kube-system", "name": "flannel-1",
                                     "uid": "system-pod-uid"}],
            "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def cleanup():
    return {"format": 1, "stage": "owned-firewall-cleanup", "status": "verified",
            "verified": True, "sourceSha": SHA, "node": "zimaboard-2",
            "nodeUid": "uid", "bootID": "boot", "captureRunId": "456",
            "cleanupPodUid": "cleanup-pod-uid",
            "beforeSha256": "c" * 64, "afterSha256": "b" * 64,
            "completedAt": "2026-10-19T00:00:00Z"}


def ownership():
    return {"format": 1, "verified": True, "sourceSha": SHA,
            "evidenceSourceSha": EVIDENCE_SHA, "captureRunId": "456",
            "admissionRunId": "123", "placementRunId": "456",
            "placementVersionId": "version-1",
            "node": "zimaboard-2", "nodeUid": "uid", "bootID": "boot",
            "snapshotSha256": "c" * 64, "reviewedAt": "2026-10-19T00:00:00Z"}


def admission_attempt():
    return {"format": 1, "stage": "canary-admit", "status": "attempted",
            "verified": False, "sourceSha": EVIDENCE_SHA, "runId": "123",
            "node": "zimaboard-2", "nodeUid": "uid", "bootID": "boot",
            "placementRunId": "456", "placementVersionId": "version-1"}


def admission_receipt():
    return {"format": 1, "stage": "canary-admit", "status": "verified",
            "verified": True, "sourceSha": EVIDENCE_SHA, "runId": "123",
            "node": "zimaboard-2", "nodeUid": "uid", "bootID": "boot",
            "placementRunId": "456", "placementVersionId": "version-1",
            "resourceVersion": "11", "completedAt": "2026-10-19T00:00:00Z"}


def recovery_proof():
    return {"format": 1, "stage": "firewall-recovery-proof", "status": "verified",
            "verified": True, "sourceSha": SHA, "evidenceSourceSha": EVIDENCE_SHA,
            "runId": "789",
            "admissionRunId": "123", "placementRunId": "456",
            "placementVersionId": "version-1", "node": "zimaboard-2",
            "nodeUid": "uid", "bootID": "boot", "firewallBaselineEmpty": True,
            "ownedChains": 0, "ownedSets": 0, "podDeleted": True,
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "snapshotSha256": "d" * 64,
            "captureKey": f"openclaw-enterprise/platform/{SHA}/789/firewall-recovery-capture.json"}


def release_attempt():
    return {"format": 1, "stage": "canary-release", "status": "attempted",
            "verified": False, "sourceSha": SHA, "runId": "678",
            "cleanupRunId": "567", "captureRunId": "456",
            "cleanupPodUid": "cleanup-pod-uid", "evidenceSourceSha": EVIDENCE_SHA,
            "admissionRunId": "123", "placementRunId": "456",
            "placementVersionId": "version-1", "node": "zimaboard-2",
            "nodeUid": "uid", "bootID": "boot"}


def release_recovery_attempt(source_sha=SHA):
    return {**release_attempt(), "stage": "canary-release-recover",
            "sourceSha": source_sha, "runId": "789", "releaseSourceSha": SHA,
            "releaseRunId": "678", "podToken": "e" * 48}


def release_recovery_proof(source_sha=SHA):
    return {**release_recovery_attempt(source_sha),
            "stage": "firewall-release-recovery-proof", "status": "verified",
            "verified": True, "firewallBaselineEmpty": True, "ownedChains": 0,
            "ownedSets": 0, "podDeleted": True,
            "observedState": "taint-only",
            "snapshotSha256": "d" * 64,
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "captureKey": f"openclaw-enterprise/platform/{source_sha}/789/firewall-recovery-capture.json"}


def node(admitted=False):
    labels = {"foreign.example/owner": "keep"}
    annotations = {"foreign.example/note": "keep"}
    taints = [{"key": "foreign.example/maintenance", "value": "yes", "effect": "NoExecute"}]
    if admitted:
        labels[CANARY] = "true"
        annotations[SUT["ADMISSION"]] = SUT["admission_marker"](EVIDENCE_SHA, "123")
        taints.append(copy.deepcopy(TAINT))
    return {"metadata": {"name": "zimaboard-2", "uid": "uid",
                         "resourceVersion": "10", "labels": labels,
                         "annotations": annotations},
            "spec": {"taints": taints, "unschedulable": False},
            "status": {"nodeInfo": {"bootID": "boot"},
                       "conditions": [{"type": "Ready", "status": "True"}]}}


def taint_only(source_sha=EVIDENCE_SHA, run_id="123"):
    state = node(admitted=True)
    state["metadata"]["labels"].pop(CANARY)
    state["metadata"]["annotations"][SUT["ADMISSION"]] = \
        SUT["admission_marker"](source_sha, run_id)
    return state


def system_pod():
    return {"metadata": {"namespace": "kube-system", "name": "flannel-1",
                         "uid": "system-pod-uid", "ownerReferences": [
                             {"kind": "DaemonSet", "name": "kube-flannel-ds",
                              "controller": True}]},
            "spec": {"nodeName": "zimaboard-2"}}


def cleanup_pod():
    pod = system_pod()
    pod["metadata"].update({"name": "cleanup-pod", "uid": "cleanup-pod-uid"})
    pod["metadata"]["ownerReferences"][0]["name"] = SUT["CLEANUP"]["CLEANUP"]
    return pod


def dormant_cleanup_daemonset():
    return {"metadata": {"name": SUT["CLEANUP"]["CLEANUP"]},
            "spec": {"selector": {"matchLabels": {
                "app.kubernetes.io/name": SUT["CLEANUP"]["CLEANUP"]}},
                "template": {"spec": {"nodeSelector": {CANARY: "true"},
                    "automountServiceAccountToken": False, "hostNetwork": True,
                    "containers": [{"image": SUT["CLEANUP"]["IMAGE"],
                                    "command": ["/bin/sh", "-c"],
                                    "args": ["sleep 86400"],
                                    "securityContext": {"privileged": True}}]}}},
            "status": {"desiredNumberScheduled": 0, "numberReady": 0}}


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
    def test_release_runtime_requires_dormant_cleanup_controller_and_no_pods(self):
        for pods, daemonset, failure in (
                ([], dormant_cleanup_daemonset(), None),
                ([cleanup_pod()], dormant_cleanup_daemonset(), "cleanup Pod still exists"),
                ([], dormant_cleanup_daemonset() | {"status": {}}, "not the reviewed"),
                ([], dormant_cleanup_daemonset() | {"status": {
                    "desiredNumberScheduled": 1, "numberReady": 0}}, "not the reviewed")):
            with self.subTest(failure=failure):
                if pods:
                    pods[0]["spec"]["nodeName"] = "another-node"

                def kube_json(*arguments):
                    if arguments[:4] == ("-n", "kube-system", "get", "daemonset"):
                        return copy.deepcopy(daemonset)
                    if arguments[:4] == ("-n", "kube-system", "get", "pods") and \
                            "-l" not in arguments:
                        return {"metadata": {}, "items": copy.deepcopy(pods)}
                    return {"metadata": {}, "items": []}

                with patch.dict(SUT["CLEANUP"], {
                        "command": lambda *_: "", "kubernetes_json": kube_json,
                        "require_traefik_off_canary": lambda *_: None}):
                    if failure:
                        with self.assertRaisesRegex(ValueError, failure):
                            SUT["require_release_runtime_quiesced"](
                                CONFIG, placement(EVIDENCE_SHA), "cleanup-pod-uid", SHA)
                    else:
                        SUT["require_release_runtime_quiesced"](
                            CONFIG, placement(EVIDENCE_SHA), "cleanup-pod-uid", SHA)

    def test_clean_release_inventory_allows_workloads_but_rejects_firewall_or_incomplete_list(self):
        workload = {"metadata": {"namespace": "default", "name": "workload",
                                 "uid": "workload-uid"},
                    "spec": {"nodeName": "zimaboard-2"}}
        restarted = system_pod()
        restarted["metadata"]["uid"] = "restarted-system-pod"
        items = [restarted, workload]
        expected = [{"namespace": "default", "name": "workload", "uid": "workload-uid"},
                    {"namespace": "kube-system", "name": "flannel-1",
                     "uid": "restarted-system-pod"}]
        with patch.dict(SUT["CLEANUP"], {"kubernetes_json": lambda *_: {
                "metadata": {}, "items": items}}):
            self.assertEqual(SUT["clean_release_pods"](CONFIG, expected), expected)
            with self.assertRaisesRegex(ValueError, "changed since firewall proof"):
                SUT["clean_release_pods"](CONFIG, expected[:1])
        for listing, error in (({"metadata": {}, "items": [cleanup_pod()]}, "forbidden"),
                               ({"metadata": {"continue": "next"}, "items": items},
                                "incomplete")):
            with self.subTest(error=error), patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": lambda *_: listing}), self.assertRaisesRegex(
                    ValueError, error):
                SUT["clean_release_pods"](CONFIG)

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

    def test_istio_platform_daemonsets_can_be_receipt_bound(self):
        for owner in ("ztunnel", "istio-cni-node"):
            with self.subTest(owner=owner):
                pod = system_pod()
                pod["metadata"].update({"namespace": "istio-system",
                                        "name": f"{owner}-1", "uid": f"{owner}-uid"})
                pod["metadata"]["ownerReferences"][0]["name"] = owner
                receipt = placement()
                receipt["systemDaemonSetPods"] = [{"namespace": "istio-system",
                                                   "name": f"{owner}-1",
                                                   "uid": f"{owner}-uid"}]
                SUT["validate_placement"](receipt, CONFIG, SHA, True)
                with patch.dict(SUT["CLEANUP"], {"kubernetes_json": lambda *args:
                                 {"metadata": {}, "items": [pod]}}):
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

    def test_activation_allows_only_the_exact_ready_fixture_client(self):
        client = {"metadata": {"namespace": "network-policy-canary",
                               "name": "npq-client", "uid": "client-uid"},
                  "spec": {"nodeName": CONFIG["canary"]["node"]},
                  "status": {"phase": "Running", "conditions": [
                      {"type": "Ready", "status": "True"}]}}
        listing = {"metadata": {}, "items": [system_pod(), client]}
        with patch.dict(SUT["CLEANUP"], {
                "kubernetes_json": lambda *_: listing,
                "complete_items": lambda value, _: value["items"],
                "ready": lambda item: item["status"]["conditions"][0]["status"] == "True"}):
            SUT["verify_live_pods"](CONFIG, placement(), "client-uid")
            with self.assertRaisesRegex(ValueError, "foreign"):
                SUT["verify_live_pods"](CONFIG, placement())
            for mutation in (lambda item: item["metadata"].update(uid="replacement"),
                             lambda item: item["metadata"].update(ownerReferences=[
                                 {"kind": "Job", "name": "foreign"}]),
                             lambda item: item["status"]["conditions"][0].update(
                                 status="False")):
                changed = copy.deepcopy(client)
                mutation(changed)
                listing["items"] = [system_pod(), changed]
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    SUT["verify_live_pods"](CONFIG, placement(), "client-uid")
            listing["items"] = [system_pod(), client,
                                {"metadata": {"namespace": "default", "name": "foreign",
                                              "uid": "foreign-uid"},
                                 "spec": {"nodeName": CONFIG["canary"]["node"]}}]
            with self.assertRaisesRegex(ValueError, "foreign"):
                SUT["verify_live_pods"](CONFIG, placement(), "client-uid")

    def test_activation_runtime_exception_keeps_firewall_absent(self):
        def command(*args):
            if args[2:5] == ("-n", "kube-system", "get"):
                return ""
            return '{"kind":"Namespace"}'
        with patch.dict(SUT["require_runtime_absent"].__globals__, {
                "require_preflight_absent": lambda: None}), patch.dict(SUT["CLEANUP"], {
                "command": command,
                "kubernetes_json": lambda *_: {"metadata": {}, "items": []},
                "complete_items": lambda value, _: value["items"]}):
            with self.assertRaisesRegex(ValueError, "fixture namespace"):
                SUT["require_runtime_absent"](True)
            SUT["require_runtime_absent"](True, allow_reviewed_fixtures=True)

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
                   selected_run="456", selected_version="version-1", loaded_run=None,
                   source_sha=SHA, run_id="123", fail_main_after_label=False,
                   traefik_guard=None):
        commands, records, events = [], [], []
        self.last_commands = commands
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
                {"GITHUB_RUN_ID": run_id}), patch.dict(SUT["PLATFORM"], {
                    "validate_config": lambda _: CONFIG,
                    "protected_context": lambda _: None,
                    "private_directory": lambda path: path,
                    "private_output": lambda path: path,
                    "read_private_json": lambda path: (placement(EVIDENCE_SHA if action ==
                    "release" else source_sha) | {"placementRunId": loaded_run or selected_run}
                    if path.name == "placement.json" else
                    ownership() if path.name == "firewall-ownership.json" else cleanup())}), \
                    patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": kube_json, "command": command,
                    "require_traefik_off_canary": traefik_guard or (lambda *_: None),
                    "require_firewall_removal_transition": lambda *_: None,
                    "inspect_cluster": lambda *_: ("cleanup-pod", "pod-uid"),
                    "snapshot": lambda *_: {"backend": "nft"},
                    "cleanup_plan": lambda *_: ([("iptables-nft", "-D", "owned")] if
                                                 remaining else [], 0, 0),
                    "write_record": lambda _path, record, replace=False:
                    records.append(copy.deepcopy(record))}), patch.object(SUT["time"],
                    "sleep", lambda _: None), patch.dict(
                    SUT["execute"].__globals__, {
                        "require_current_main": lambda _: (_ for _ in ()).throw(
                            ValueError("source is not exact current main")) if
                            fail_main_after_label and state["metadata"]["labels"].get(
                                CANARY) == "true" else None,
                        "require_fresh_capacity": capacity_gate}):
            args = argparse.Namespace(action=action,
                                      config=ROOT / "scripts/config/platform-maintenance.json",
                                      expected_sha=source_sha, receipt_dir=Path(directory),
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
                     admission=None, action="recover", source_changed=False,
                     runtime_error=False, pods=None, expected_error=None):
        selected = selected if selected is not None else placement(EVIDENCE_SHA)
        attempt = attempt if attempt is not None else admission_attempt()
        proof = proof if proof is not None else recovery_proof()
        admission = admission if admission is not None else admission_receipt()
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
                        "admission-attempt.json" else admission if path.name ==
                        "admission.json" else proof)}), patch.dict(SUT["CLEANUP"], {
                    "kubernetes_json": kube_json, "command": command,
                    "require_traefik_off_canary": lambda *_: None,
                    "write_record": lambda _path, record, replace=False:
                    records.append(copy.deepcopy(record))}), patch.dict(SUT["OWNERSHIP"], {
                    "require_owner_attestation": lambda: None,
                    "PrivateStore": lambda _bucket: type("Store", (), {
                        "version": lambda _self, *_: "admission-version",
                        "read": lambda _self, *_: json.dumps(admission)})()}), patch.dict(
                    SUT["recover"].__globals__, {
                        "require_current_main": lambda _: None,
                        "require_abort_source": lambda *_: (_ for _ in ()).throw(
                            ValueError("canary source changed")) if source_changed else None,
                        "require_runtime_absent": lambda admit: (_ for _ in ()).throw(
                            ValueError("firewall DaemonSet remains")) if runtime_error else
                            SUT["require_runtime_absent"](admit),
                        "require_fresh_capacity": lambda *_: self.fail(
                            "recovery must not refresh capacity")}):
            args = argparse.Namespace(
                action=action, config=ROOT / "scripts/config/platform-maintenance.json",
                expected_sha=SHA, receipt_dir=Path(directory),
                output=Path(directory) / "result.json", bucket="bucket" if action == "abort"
                else None,
                evidence_source_sha=EVIDENCE_SHA,
                admission_run_id="123", placement_run_id="456",
                placement_version_id="version-1",
                admission_version_id="admission-version" if action == "abort" else None)
            if expected_error:
                with self.assertRaisesRegex(ValueError, expected_error):
                    SUT["recover"](args)
                return commands, records, state
            result = SUT["recover"](args)
        self.assertTrue(result["verified"])
        return commands, records, state

    def test_recover_expired_admission_removes_only_owned_label_then_taint(self):
        selected = placement(EVIDENCE_SHA)
        selected["capturedAt"] = "2026-01-01T00:00:00Z"
        selected["baselineCapturedAt"] = "2026-01-01T00:00:00Z"
        commands, records, state = self.run_recovery(node(admitted=True), selected=selected)
        self.assertEqual(len(commands), 2)
        self.assertEqual([operation["path"] for operation in commands[0][:2]],
                         ["/metadata/resourceVersion", "/metadata/uid"])
        self.assertEqual([(operation["op"], operation["path"])
                          for operation in commands[0][2:]],
                         [("test", SUT["LABEL_PATH"]),
                          ("test", SUT["ADMISSION_PATH"]),
                          ("test", "/spec/taints/1"), ("remove", SUT["LABEL_PATH"])])
        self.assertEqual([(operation["op"], operation["path"])
                          for operation in commands[1][2:]],
                         [("test", "/spec/taints/1"),
                          ("test", SUT["ADMISSION_PATH"]),
                          ("remove", SUT["ADMISSION_PATH"]),
                          ("remove", "/spec/taints/1")])
        self.assertEqual(state["metadata"]["labels"], {"foreign.example/owner": "keep"})
        self.assertEqual(state["spec"]["taints"], [{"key": "foreign.example/maintenance",
                                                   "value": "yes", "effect": "NoExecute"}])
        self.assertEqual([record["status"] for record in records], ["started", "verified"])
        self.assertEqual(records[-1]["stage"], "canary-admit-recover")
        self.assertEqual(records[-1]["firewallCaptureKey"], recovery_proof()["captureKey"])

    def test_recover_taint_only_or_already_clean_is_idempotent(self):
        commands, _, state = self.run_recovery(taint_only())
        self.assertEqual(len(commands), 1)
        self.assertNotIn(TAINT, state["spec"]["taints"])
        commands, _, _ = self.run_recovery(state)
        self.assertEqual(commands, [])

    def test_verified_admission_abort_removes_marker_and_taint_and_retries(self):
        commands, records, state = self.run_recovery(node(admitted=True), action="abort")
        self.assertEqual(len(commands), 2)
        self.assertEqual([(item["op"], item["path"]) for item in commands[0][2:]],
                         [("test", SUT["LABEL_PATH"]),
                          ("test", SUT["ADMISSION_PATH"]),
                          ("test", "/spec/taints/1"), ("remove", SUT["LABEL_PATH"])])
        self.assertEqual([(item["op"], item["path"]) for item in commands[1][2:]],
                         [("test", "/spec/taints/1"),
                          ("test", SUT["ADMISSION_PATH"]),
                          ("remove", SUT["ADMISSION_PATH"]),
                          ("remove", "/spec/taints/1")])
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertNotIn(SUT["ADMISSION"], state["metadata"]["annotations"])
        self.assertNotIn(TAINT, state["spec"]["taints"])
        self.assertEqual(records[-1]["stage"], "canary-abort")
        self.assertEqual(records[-1]["admissionVersionId"], "admission-version")
        commands, _, _ = self.run_recovery(state, action="abort")
        self.assertEqual(commands, [])

    def test_verified_admission_abort_rejects_replay_or_changed_source(self):
        for state, options, error in (
                (node(admitted=True), {"admission": admission_receipt() |
                 {"placementVersionId": "other"}}, "verified canary admission"),
                (node(admitted=True), {"source_changed": True}, "source changed"),
                (node(admitted=True), {"runtime_error": True}, "firewall DaemonSet"),
                (node(admitted=True), {"proof": recovery_proof() |
                 {"firewallBaselineEmpty": False}}, "same-run empty firewall"),
                (node(admitted=True), {}, "admission marker")):
            with self.subTest(error=error):
                if error == "admission marker":
                    state["metadata"]["annotations"][SUT["ADMISSION"]] = \
                        SUT["admission_marker"](EVIDENCE_SHA, "999")
                commands, records, _ = self.run_recovery(
                    state, action="abort", expected_error=error, **options)
                self.assertEqual((commands, records), ([], []))

    def test_aborted_admission_cannot_remove_later_taint_only_attempt(self):
        _, _, state = self.run_recovery(node(admitted=True), action="abort")
        with self.assertRaisesRegex(ValueError, "simulated label patch failure"):
            self.run_action("admit", state, source_sha=EVIDENCE_SHA, run_id="124",
                            fail_label_patch=True)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual(state["metadata"]["annotations"][SUT["ADMISSION"]],
                         SUT["admission_marker"](EVIDENCE_SHA, "124"))
        commands, records, _ = self.run_recovery(
            state, action="abort", expected_error="admission marker")
        self.assertEqual((commands, records), ([], []))

    def test_abort_source_allows_unrelated_main_advance_only(self):
        config = {"activationEnabled": False, "canary": {"node": "zimaboard-2"}}
        def committed(command, **_):
            if "rev-list" in command:
                return f"{SHA}\n{EVIDENCE_SHA}\n"
            return (ROOT / command[-1].split(":", 1)[1]).read_bytes()
        with patch.object(SUT["subprocess"], "check_output", side_effect=committed):
            SUT["require_abort_source"](config, EVIDENCE_SHA, SHA)
        def changed(command, **_):
            return f"{SHA}\n{EVIDENCE_SHA}\n" if "rev-list" in command else b"changed"
        with patch.object(SUT["subprocess"], "check_output", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "source changed"):
                SUT["require_abort_source"](config, EVIDENCE_SHA, SHA)
        with patch.object(SUT["subprocess"], "check_output",
                          return_value=f"{SHA}\n"):
            with self.assertRaisesRegex(ValueError, "not an ancestor"):
                SUT["require_abort_source"](config, EVIDENCE_SHA, SHA)
        with self.assertRaisesRegex(ValueError, "pre-activation"):
            SUT["require_abort_source"](
                {"activationEnabled": True, "canary": {"node": "zimaboard-2"}},
                EVIDENCE_SHA, SHA)

    def test_release_source_allows_unrelated_main_advance_but_not_runtime_drift(self):
        current = "d" * 40
        config = {"activationEnabled": True, "canary": {"node": "zimaboard-2"},
                  "activationAdmission": {"sourceSha": EVIDENCE_SHA,
                                          "runId": "123", "versionId": "selected"}}

        def committed(command, **_):
            if "rev-list" in command:
                return f"{current}\n{SHA}\n"
            relative = command[-1].split(":", 1)[1]
            if relative == "scripts/config/platform-maintenance.json":
                return json.dumps({**config, "unrelatedUpgrade": "older"}).encode()
            return (ROOT / relative).read_bytes()

        with patch.object(SUT["subprocess"], "check_output", side_effect=committed):
            SUT["require_release_source"](config, SHA, current)

        def changed(command, **_):
            if "rev-list" in command:
                return f"{current}\n{SHA}\n"
            relative = command[-1].split(":", 1)[1]
            if relative.endswith("cleanup/daemonset.yaml"):
                return b"changed"
            if relative == "scripts/config/platform-maintenance.json":
                return json.dumps(config).encode()
            return (ROOT / relative).read_bytes()

        with patch.object(SUT["subprocess"], "check_output", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "source changed"):
                SUT["require_release_source"](config, SHA, current)

        def changed_canary(command, **_):
            if "rev-list" in command:
                return f"{current}\n{SHA}\n"
            relative = command[-1].split(":", 1)[1]
            if relative == "scripts/config/platform-maintenance.json":
                return json.dumps({**config, "canary": {"node": "another-node"}}).encode()
            return (ROOT / relative).read_bytes()

        with patch.object(SUT["subprocess"], "check_output", side_effect=changed_canary):
            with self.assertRaisesRegex(ValueError, "configuration changed"):
                SUT["require_release_source"](config, SHA, current)

        def changed_admission(command, **_):
            if "rev-list" in command:
                return f"{current}\n{SHA}\n"
            relative = command[-1].split(":", 1)[1]
            if relative == "scripts/config/platform-maintenance.json":
                return json.dumps({**config, "activationAdmission": None}).encode()
            return (ROOT / relative).read_bytes()

        with patch.object(SUT["subprocess"], "check_output", side_effect=changed_admission):
            with self.assertRaisesRegex(ValueError, "configuration changed"):
                SUT["require_release_source"](config, SHA, current)

    def test_interrupted_abort_keeps_taint_then_can_retry(self):
        foreign = system_pod()
        foreign["metadata"].update({"namespace": "default", "name": "foreign",
                                    "uid": "foreign-uid", "ownerReferences": []})
        inventories = iter(([system_pod()], [system_pod(), foreign]))
        commands, records, state = self.run_recovery(
            node(admitted=True), action="abort", pods=lambda: next(inventories),
            expected_error="foreign")
        self.assertEqual(len(commands), 1)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual(state["metadata"]["annotations"][SUT["ADMISSION"]],
                         SUT["admission_marker"](EVIDENCE_SHA, "123"))
        self.assertEqual(records[-1]["status"], "interrupted")
        commands, records, state = self.run_recovery(state, action="abort")
        self.assertEqual(len(commands), 1)
        self.assertNotIn(TAINT, state["spec"]["taints"])
        self.assertEqual(records[-1]["status"], "verified")

    def test_recover_rejects_forged_selection_or_missing_firewall_proof(self):
        for evidence, changes, error in (
                ("attempt", {"sourceSha": SHA}, "admission attempt"),
                ("attempt", {"runId": "124"}, "admission attempt"),
                ("attempt", {"nodeUid": "other"}, "admission attempt"),
                ("attempt", {"placementVersionId": "forged"}, "admission attempt"),
                ("proof", {"runId": "788"}, "same-run empty firewall"),
                ("proof", {"evidenceSourceSha": SHA}, "same-run empty firewall"),
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
                                                expected_error="unexpected canary")
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
                         ["/spec/taints/-", SUT["ADMISSION_PATH"]])
        self.assertEqual([item["path"] for item in commands[1][2:]],
                         [SUT["LABEL_PATH"]])
        self.assertEqual(self.last_events, ["taint", "inventory", "label", "inventory"])
        self.assertEqual(state["metadata"]["labels"][CANARY], "true")
        self.assertEqual(state["metadata"]["annotations"][SUT["ADMISSION"]],
                         SUT["admission_marker"](SHA, "123"))
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
                         [("test", SUT["LABEL_PATH"]),
                          ("test", SUT["ADMISSION_PATH"]),
                          ("test", "/spec/taints/1"), ("remove", SUT["LABEL_PATH"])])
        self.assertEqual([(item["op"], item["path"]) for item in commands[1][2:]],
                         [("test", "/spec/taints/1"),
                          ("test", SUT["ADMISSION_PATH"]),
                          ("remove", SUT["ADMISSION_PATH"]),
                          ("remove", "/spec/taints/1")])
        self.assertEqual(self.last_events, ["unlabel", "cleanup-inventory",
                                            "cleanup-inventory", "inventory", "taint"])
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(len(state["spec"]["taints"]), 1)

    def test_release_keeps_taint_if_traefik_arrives_after_unlabel(self):
        state = node(admitted=True)
        checks = 0

        def guard(*_):
            nonlocal checks
            checks += 1
            if checks == 3:
                raise ValueError("Traefik EndpointSlice endpoint remains on canary")

        with self.assertRaisesRegex(ValueError, "Traefik EndpointSlice"):
            self.run_action("release", state, traefik_guard=guard)
        self.assertEqual(checks, 3)
        self.assertEqual(len(self.last_commands), 1)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertIn(TAINT, state["spec"]["taints"])
        self.assertEqual(self.last_records[-1]["status"], "interrupted")

    def test_release_retains_taint_while_cleanup_pod_remains(self):
        state = node(admitted=True)
        with patch.object(SUT["time"], "monotonic", side_effect=[0, 121]):
            with self.assertRaisesRegex(ValueError, "cleanup Pod remains"):
                self.run_action("release", state, cleanup_pods=lambda: [cleanup_pod()])
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual(state["metadata"]["annotations"][SUT["ADMISSION"]],
                         SUT["admission_marker"](EVIDENCE_SHA, "123"))
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

    def test_taint_only_admission_requires_selected_recovery(self):
        state = taint_only()
        with self.assertRaisesRegex(ValueError, "selected admission recovery"):
            self.run_action("admit", state)
        self.assertEqual(self.last_commands, [])
        self.assertNotIn(CANARY, state["metadata"]["labels"])

    def test_admit_refuses_label_only_or_already_admitted(self):
        with self.assertRaisesRegex(ValueError, "already labeled"):
            self.run_action("admit", node(admitted=True))
        label_only = node()
        label_only["metadata"]["labels"][CANARY] = "true"
        with self.assertRaisesRegex(ValueError, "already labeled"):
            self.run_action("admit", label_only)

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

    def test_interrupted_taint_only_state_requires_recovery_before_retry(self):
        state = node()
        with self.assertRaisesRegex(ValueError, "simulated label patch failure"):
            self.run_action("admit", state, source_sha=EVIDENCE_SHA,
                            fail_label_patch=True)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        self.assertEqual(state["metadata"]["annotations"][SUT["ADMISSION"]],
                         SUT["admission_marker"](EVIDENCE_SHA, "123"))
        self.assertEqual([item["status"] for item in self.last_records],
                         ["started", "interrupted"])
        with self.assertRaisesRegex(ValueError, "selected admission recovery"):
            self.run_action("admit", state, selected_run="457",
                            selected_version="version-2")
        self.assertEqual(self.last_commands, [])
        commands, _, state = self.run_recovery(state)
        self.assertEqual(len(commands), 1)
        self.assertNotIn(TAINT, state["spec"]["taints"])
        self.run_action("admit", state, selected_run="457", selected_version="version-2")
        self.assertEqual(self.last_records[-1]["placementRunId"], "457")
        self.assertEqual(self.last_records[-1]["placementVersionId"], "version-2")

    def test_stale_main_after_label_recovers_from_original_admission_sha(self):
        state = node()
        with self.assertRaisesRegex(ValueError, "exact current main"):
            self.run_action("admit", state, source_sha=EVIDENCE_SHA,
                            fail_main_after_label=True)
        self.assertEqual([item["status"] for item in self.last_records],
                         ["started", "interrupted"])
        self.assertEqual(state["metadata"]["labels"][CANARY], "true")
        self.assertEqual(state["spec"]["taints"][-1], TAINT)
        commands, records, state = self.run_recovery(state)
        self.assertEqual(len(commands), 2)
        self.assertEqual(records[-1]["sourceSha"], SHA)
        self.assertEqual(records[-1]["evidenceSourceSha"], EVIDENCE_SHA)
        self.assertNotIn(CANARY, state["metadata"]["labels"])
        self.assertNotIn(TAINT, state["spec"]["taints"])

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
        state["metadata"]["annotations"].pop(SUT["ADMISSION"])
        with self.assertRaisesRegex(ValueError, "unexpected canary"):
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

    def test_release_recovery_receipts_bind_original_cleanup_and_same_run_proof(self):
        args = argparse.Namespace(expected_sha="d" * 40, release_source_sha=SHA,
                                  release_run_id="678", cleanup_run_id="567",
                                  evidence_source_sha=EVIDENCE_SHA, admission_run_id="123")
        transition = []
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "789"}), patch.dict(SUT["CLEANUP"], {
                "require_firewall_removal_transition":
                lambda old, new: transition.append((old, new))}):
            SUT["validate_release_recovery_receipts"](
                release_attempt(), release_recovery_attempt(args.expected_sha),
                release_recovery_proof(args.expected_sha), cleanup(), ownership(),
                placement(EVIDENCE_SHA), args, CONFIG)
            self.assertEqual(transition, [(EVIDENCE_SHA, SHA)])
            for changed in ({"cleanupRunId": "999"}, {"cleanupPodUid": "other"},
                            {"admissionRunId": "999"}):
                with self.subTest(changed=changed), self.assertRaisesRegex(
                        ValueError, "release attempt"):
                    SUT["validate_release_recovery_receipts"](
                        release_attempt() | changed,
                        release_recovery_attempt(args.expected_sha),
                        release_recovery_proof(args.expected_sha), cleanup(), ownership(),
                        placement(EVIDENCE_SHA), args, CONFIG)
            with self.assertRaisesRegex(ValueError, "firewall proof"):
                SUT["validate_release_recovery_receipts"](
                    release_attempt(), release_recovery_attempt(args.expected_sha),
                    release_recovery_proof(args.expected_sha) | {"podDeleted": False},
                    cleanup(), ownership(), placement(EVIDENCE_SHA), args, CONFIG)
            with self.assertRaisesRegex(ValueError, "cleanup receipt"):
                SUT["validate_release_recovery_receipts"](
                    release_attempt(), release_recovery_attempt(args.expected_sha),
                    release_recovery_proof(args.expected_sha),
                    cleanup() | {"sourceSha": "f" * 40}, ownership(),
                    placement(EVIDENCE_SHA), args, CONFIG)

    def test_release_recovery_requires_owner_before_receipt_or_cluster_access(self):
        with patch.dict(SUT["PLATFORM"], {
                "require_reviewed_execution_config": lambda *_: None,
                "validate_config": lambda _: CONFIG,
                "protected_context": lambda _: None,
                "private_directory": lambda *_: self.fail("private receipt accessed")}), \
                patch.dict(SUT["OWNERSHIP"], {"require_owner_attestation":
                    lambda: (_ for _ in ()).throw(ValueError("owner required"))}), \
                patch.dict(SUT["release_recover"].__globals__, {
                    "require_current_main": lambda *_: self.fail("cluster accessed")}), \
                self.assertRaisesRegex(ValueError, "owner required"):
            SUT["release_recover"](argparse.Namespace(
                config=ROOT / "scripts/config/platform-maintenance.json",
                expected_sha=SHA))

    def test_release_recovery_requires_matching_marker_and_atomic_untaint(self):
        source_sha = "d" * 40

        def run(state, expected_error=None, proof_state=None, pods=None,
                traefik_guard=None):
            patches, records, sources = [], [], []
            proof_state = proof_state or ("taint-only" if TAINT in state["spec"]["taints"]
                                          else "clean")
            current_pods = [system_pod()] if pods is None else pods
            observed_pods = sorted(({
                "namespace": pod["metadata"]["namespace"],
                "name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"]}
                for pod in current_pods),
                key=lambda item: (item["namespace"], item["name"], item["uid"]))
            proof = release_recovery_proof(source_sha) | {"observedState": proof_state}
            if proof_state == "clean":
                proof["observedPods"] = observed_pods
            selected = {"placement.json": placement(EVIDENCE_SHA),
                        "firewall-ownership.json": ownership(), "cleanup.json": cleanup(),
                        "release-attempt.json": release_attempt(),
                        "recovery-attempt.json": release_recovery_attempt(source_sha),
                        "firewall-recovery-proof.json": proof}

            def kube_json(*arguments):
                if arguments[:2] == ("get", "node"):
                    return copy.deepcopy(state)
                if arguments[:2] == ("get", "pods"):
                    return {"metadata": {}, "items": copy.deepcopy(current_pods)}
                return {"metadata": {}, "items": []}

            def command(*arguments):
                if "patch" in arguments:
                    operations = json.loads(arguments[arguments.index("-p") + 1])
                    patches.append(operations)
                    apply_patch(state, operations)
                    return json.dumps(state)
                return ""

            with tempfile.TemporaryDirectory() as directory, patch.dict(
                    os.environ, {"GITHUB_RUN_ID": "789"}), patch.dict(SUT["PLATFORM"], {
                        "require_reviewed_execution_config": lambda *_: None,
                        "validate_config": lambda _: CONFIG,
                        "protected_context": lambda _: None,
                        "private_directory": lambda path: path,
                        "private_output": lambda path: path,
                        "read_private_json": lambda path: selected[path.name]}), patch.dict(
                    SUT["CLEANUP"], {"kubernetes_json": kube_json, "command": command,
                        "require_traefik_off_canary": traefik_guard or (lambda *_: None),
                        "require_firewall_removal_transition": lambda *_: None,
                        "write_record": lambda _path, record, replace=False:
                        records.append(copy.deepcopy(record))}), patch.dict(
                    SUT["OWNERSHIP"], {"require_owner_attestation": lambda: None}), patch.dict(
                    SUT["release_recover"].__globals__, {
                        "require_current_main": lambda _: None,
                        "require_release_source": lambda _config, old, new:
                        sources.append((old, new)),
                        "require_release_runtime_quiesced": lambda *_: None}):
                args = argparse.Namespace(
                    config=ROOT / "scripts/config/platform-maintenance.json",
                    expected_sha=source_sha, receipt_dir=Path(directory),
                    output=Path(directory) / "result.json", release_source_sha=SHA,
                    release_run_id="678", cleanup_run_id="567",
                    evidence_source_sha=EVIDENCE_SHA, admission_run_id="123")
                if expected_error:
                    with self.assertRaisesRegex(ValueError, expected_error):
                        SUT["release_recover"](args)
                else:
                    self.assertTrue(SUT["release_recover"](args)["verified"])
            return patches, records, sources

        state = taint_only()
        patches, records, sources = run(state)
        self.assertEqual(len(patches), 1)
        self.assertEqual([step["path"] for step in patches[0][-2:]],
                         [SUT["ADMISSION_PATH"], "/spec/taints/1"])
        self.assertNotIn(TAINT, state["spec"]["taints"])
        self.assertNotIn(SUT["ADMISSION"], state["metadata"]["annotations"])
        self.assertEqual([record["status"] for record in records], ["started", "verified"])
        self.assertTrue(records[-1]["mutationPerformed"])
        self.assertFalse(records[-1]["observedClean"])
        self.assertEqual(sources, [(SHA, source_sha), (SHA, source_sha)])
        def block_ingress(*_):
            raise ValueError("Traefik Pod remains on canary")
        patches, records, _ = run(taint_only(), "Traefik Pod remains",
                                  traefik_guard=block_ingress)
        self.assertEqual(patches, [])
        self.assertEqual(records[-1]["status"], "interrupted")
        patches, _, _ = run(taint_only(run_id="999"), "admission marker")
        self.assertEqual(patches, [])
        patches, _, _ = run(node(admitted=True), "isolation state changed")
        self.assertEqual(patches, [])
        workload = {"metadata": {"namespace": "default", "name": "workload",
                                 "uid": "workload-uid"},
                    "spec": {"nodeName": "zimaboard-2"}}
        patches, records, _ = run(node(), pods=[system_pod(), workload])
        self.assertEqual(patches, [])
        self.assertEqual([record["status"] for record in records], ["started", "verified"])
        self.assertFalse(records[-1]["mutationPerformed"])
        self.assertTrue(records[-1]["observedClean"])
        patches, _, _ = run(taint_only(), "isolation state changed", proof_state="clean")
        self.assertEqual(patches, [])
        stale = node()
        stale["metadata"]["annotations"][SUT["ADMISSION"]] = \
            SUT["admission_marker"](EVIDENCE_SHA, "999")
        patches, _, _ = run(stale, "unexpected canary")
        self.assertEqual(patches, [])


if __name__ == "__main__":
    unittest.main()
