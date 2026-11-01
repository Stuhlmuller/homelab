#!/usr/bin/env python3
"""Offline failure tests for the protected admitted-canary activation gate."""

import argparse
import copy
import json
import os
import runpy
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SUT = runpy.run_path("scripts/network-policy-activation-capacity.py")
CURRENT = "b" * 40
EVIDENCE = "a" * 40
NODE = SUT["NODE"]
SYSTEM = [{"namespace": "kube-system", "name": "flannel-1", "uid": "system-uid"}]
SELECTION = {"sourceSha": EVIDENCE, "runId": "123", "versionId": "admit-version"}
CONFIG = {"activationEnabled": True, "canary": {"node": NODE,
          "taint": f"{SUT['CANARY']['CANARY']}=true:NoSchedule"},
          "activationAdmission": SELECTION}


def placement():
    return {"format": 1, "verified": True, "sourceSha": EVIDENCE,
            "placementRunId": "456", "node": NODE, "canaryNode": NODE,
            "nodeUid": "node-uid", "bootID": "boot-id",
            "fixtureNode": "zimaboard-1", "fixtureNodeUid": "fixture-uid",
            "fixtureBootID": "fixture-boot",
            "systemDaemonSetPods": SYSTEM}


def fixture_proof():
    return {"pods": {"npq-client": {"uid": "client-uid", "node": NODE,
                                "podIP": "10.42.0.1",
                                "containerID": "containerd://client",
                                "imageID": "mirror@sha256:" + "1" * 64},
                     "npq-allowed": {"uid": "allowed-uid", "node": "zimaboard-1",
                                     "podIP": "10.42.0.2",
                                     "containerID": "containerd://allowed",
                                     "imageID": "mirror@sha256:" + "1" * 64},
                     "npq-denied": {"uid": "denied-uid", "node": "zimaboard-1",
                                    "podIP": "10.42.0.3",
                                    "containerID": "containerd://denied",
                                    "imageID": "mirror@sha256:" + "1" * 64}},
            "policySha256": "a" * 64, "fixtureNodeUid": "fixture-uid",
            "fixtureBootID": "fixture-boot"}


def admission():
    return {"format": 1, "stage": "canary-admit", "status": "verified",
            "verified": True, "sourceSha": EVIDENCE, "runId": "123", "node": NODE,
            "nodeUid": "node-uid", "bootID": "boot-id", "placementRunId": "456",
            "placementVersionId": "place-version", "resourceVersion": "1234",
            "completedAt":
            datetime.now(timezone.utc).isoformat()}


class Store:
    def __init__(self, proof=None, selected=None):
        self.proof = proof if proof is not None else admission()
        self.selected = selected if selected is not None else placement()
        self.writes = []
        self.store = self

    def check(self):
        pass

    def version(self, key, required):
        assert required
        return "admit-version" if key.endswith("canary-admit.json") else "place-version"

    def read(self, key, limit):
        assert limit == 1048576
        return json.dumps(self.proof if key.endswith("canary-admit.json") else
                          self.selected).encode()

    def write_once(self, key, record, limit):
        self.writes.append((key, record, limit))


class ActivationCapacityTests(unittest.TestCase):
    def test_source_phase_requires_committed_fixture_first_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "clusters/homelab/platform/network-policy/kustomization.yaml"
            canary = root / "clusters/homelab/platform/network-policy/canary/kustomization.yaml"
            canary.parent.mkdir(parents=True)
            policy.write_bytes(SUT["EMPTY"])
            canary.write_bytes(SUT["FIXTURE_SOURCE"])
            committed = {"clusters/homelab/platform/network-policy/kustomization.yaml":
                         SUT["EMPTY"],
                         "clusters/homelab/platform/network-policy/canary/kustomization.yaml":
                         SUT["FIXTURE_SOURCE"]}
            def git_show(command, **_):
                return committed[command[-1].split(":", 1)[1]]
            with patch.dict(SUT["require_source_phase"].__globals__, {"ROOT": root}), \
                    patch("subprocess.check_output", side_effect=git_show):
                SUT["require_source_phase"](CURRENT, "fixtures")
                policy.write_bytes(SUT["ENFORCER_SOURCE"])
                with self.assertRaisesRegex(ValueError, "source phase"):
                    SUT["require_source_phase"](CURRENT, "fixtures")
                committed[next(iter(committed))] = SUT["ENFORCER_SOURCE"]
                SUT["require_source_phase"](CURRENT, "enforcer")
                canary.write_bytes(SUT["EMPTY"])
                with self.assertRaisesRegex(ValueError, "source phase"):
                    SUT["require_source_phase"](CURRENT, "enforcer")

    def test_live_application_must_match_reviewed_source_and_sync(self):
        app = {"metadata": {"name": "platform-network-policy-canary",
                            "namespace": "argocd"},
               "spec": {"project": "homelab", "destination": {
                   "server": "https://kubernetes.default.svc",
                   "namespace": "network-policy-canary"},
                   "sources": [{"repoURL": "https://github.com/Stuhlmuller/homelab.git",
                                "path": "clusters/homelab/platform/network-policy/canary",
                                "targetRevision": "main"}],
                   "syncPolicy": {"syncOptions": ["CreateNamespace=false",
                                                  "ServerSideApply=true"],
                                  "automated": {"enabled": True, "prune": True,
                                                "allowEmpty": False,
                                                "selfHeal": True}}},
               "status": {"sync": {"status": "Synced", "revisions": [CURRENT]},
                          "health": {"status": "Healthy"}}}
        with patch.dict(SUT["CLEANUP"], {"kubernetes_json": lambda *_: app}):
            SUT["require_application"]("platform-network-policy-canary", CURRENT)
            for edit in ({"status": {"sync": {"status": "OutOfSync",
                                               "revisions": [CURRENT]},
                                     "health": {"status": "Healthy"}}},
                         {"status": {"sync": {"status": "Synced",
                                               "revisions": [EVIDENCE]},
                                     "health": {"status": "Healthy"}}},
                         {"metadata": {"name": "platform-network-policy-canary",
                                       "namespace": "argocd",
                                       "deletionTimestamp": "2026-11-01T00:00:00Z"}}):
                original = {key: app[key] for key in edit}
                app.update(edit)
                with self.subTest(edit=edit), self.assertRaisesRegex(
                        ValueError, "Application differs"):
                    SUT["require_application"]("platform-network-policy-canary", CURRENT)
                app.update(original)
            policy = copy.deepcopy(app)
            policy["metadata"]["name"] = "platform-network-policy"
            policy["spec"]["destination"]["namespace"] = "kube-system"
            policy["spec"]["sources"][0]["path"] = (
                "clusters/homelab/platform/network-policy")
            policy["spec"]["syncPolicy"]["automated"].update(
                enabled=False, prune=False)
            policy["status"]["sync"]["status"] = "OutOfSync"
            with patch.dict(SUT["CLEANUP"], {"kubernetes_json": lambda *_: policy}):
                SUT["require_application"]("platform-network-policy")
                policy["spec"]["syncPolicy"]["automated"]["enabled"] = True
                with self.assertRaisesRegex(ValueError, "Application differs"):
                    SUT["require_application"]("platform-network-policy")

    def test_first_pull_requires_exact_ready_fixture_image_id_and_node_identity(self):
        image_id = "docker.io/example/python@sha256:" + "1" * 64
        def node(uid, boot):
            return {"metadata": {"uid": uid},
                    "status": {"nodeInfo": {"bootID": boot}}}
        pods = {}
        for index, (name, assigned) in enumerate((("npq-client", NODE),
                               ("npq-allowed", "zimaboard-1"),
                               ("npq-denied", "zimaboard-1")), 1):
            pods[name] = {"metadata": {"uid": name + "-uid"},
                          "spec": {"nodeName": assigned},
                          "status": {"podIP": f"10.42.0.{index}",
                                     "containerStatuses": [{
                              "imageID": image_id, "containerID": "containerd://" + name,
                              "restartCount": 0}]}}
        state = [node("node-uid", "boot-id"), node("fixture-uid", "fixture-boot"),
                 pods, None, "policy-sha"]
        calls = []
        def inspect(_config, require_firewall=True):
            self.assertFalse(require_firewall)
            return state
        with patch.dict(SUT["QUALIFY"], {"inspect": inspect}), patch.dict(
                SUT["CANARY"], {"verify_live_pods": lambda *args: calls.append(args[-1])}):
            client, proof = SUT["verified_fixtures"](CONFIG, placement())
            self.assertEqual(client["metadata"]["uid"], "npq-client-uid")
            self.assertEqual(calls, ["npq-client-uid"])
            self.assertEqual(proof["pods"]["npq-allowed"]["imageID"], image_id)
            for changed, error in ((lambda: state[1]["status"]["nodeInfo"].update(
                                         bootID="replacement"), "Nodes differ"),
                                   (lambda: pods["npq-allowed"]["status"][
                                       "containerStatuses"][0].update(
                                           imageID="unverified"), "first-pull"),
                                   (lambda: pods["npq-client"]["status"][
                                       "containerStatuses"][0].update(
                                           restartCount=1), "first-pull")):
                candidate = copy.deepcopy(state)
                changed()
                with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                    SUT["verified_fixtures"](CONFIG, placement())
                state[:] = candidate
                pods = state[2]

    def test_reviewed_activation_requires_pinned_first_parent_admission(self):
        config = copy.deepcopy(CONFIG)

        def git_output(command, **_):
            if "rev-list" in command:
                return CURRENT + "\n" + EVIDENCE + "\n"
            return (SUT["ROOT"] / command[-1].split(":", 1)[1]).read_bytes()

        with patch.dict(SUT["PLATFORM"], {
                "require_reviewed_execution_config": lambda *_: None,
                "validate_config": lambda value: config,
                "protected_context": lambda *_: None}), \
                patch.dict(SUT["CLEANUP"], {"require_current_main": lambda *_: None}), \
                patch.dict(SUT["PLACEMENT"], {"pinned_manifests": lambda *_: None}), \
                patch.dict(SUT["reviewed_config"].__globals__, {
                    "CONFIG": SUT["CONFIG"], "subprocess": subprocess,
                    "require_source_phase": lambda *_: None}), \
                patch("subprocess.check_output", side_effect=git_output):
            self.assertEqual(SUT["reviewed_config"](CURRENT, "fixtures")[1], SELECTION)
            for bad in (None, {**SELECTION, "versionId": ""},
                        {**SELECTION, "sourceSha": "c" * 40}):
                config["activationAdmission"] = bad
                with self.subTest(selection=bad), self.assertRaises(ValueError):
                    SUT["reviewed_config"](CURRENT, "fixtures")

    def test_selected_receipts_reject_wrong_version_and_unverified_admission(self):
        with patch.dict(SUT["CANARY"], {"validate_placement": lambda *_: None}):
            selected, proof, _, _ = SUT["selected_placement"](
                Store(), CONFIG, SELECTION)
            self.assertEqual(selected["nodeUid"], proof["nodeUid"])
            for bad_store, bad_selection in (
                    (Store(), SELECTION | {"versionId": "wrong"}),
                    (Store(proof=admission() | {"verified": False}), SELECTION),
                    (Store(selected=placement() | {"bootID": "wrong"}), SELECTION)):
                with self.subTest(selection=bad_selection), self.assertRaises(ValueError):
                    SUT["selected_placement"](bad_store, CONFIG, bad_selection)

    def test_activation_probe_attempt_precedes_create_and_capture_must_match(self):
        stamp = datetime.now(timezone.utc).isoformat()
        snapshot = {"backend": "nft", "nft": "", "legacy": "", "ip6nft": "",
                    "ip6legacy": "", "ipset": ""}
        capture = {"format": 1, "stage": "firewall-activation-baseline",
                   "status": "verified", "verified": True, "sourceSha": CURRENT,
                   "runId": "789", "nodeUid": "node-uid", "bootID": "boot-id",
                   "evidenceSourceSha": EVIDENCE, "admissionRunId": "123",
                   "admissionVersionId": "admit-version", "placementRunId": "456",
                   "placementVersionId": "place-version", "systemDaemonSetPods": SYSTEM,
                   "fixtureClientUid": "client-uid", "fixtureNodeUid": "fixture-uid",
                   "fixtureBootID": "fixture-boot",
                   "firewallBaselineEmpty": True, "ownedChains": 0, "ownedSets": 0,
                   "podDeleted": True, "completedAt": stamp,
                   "snapshotSha256": "0" * 64, "snapshot": snapshot}

        class CaptureStore(Store):
            def version(self, key, required):
                self.assert_required = required
                return "capture-version"

            def read(self, key, limit):
                return json.dumps(capture).encode()

        store = CaptureStore()
        called = []

        def baseline_execute(args):
            called.append("probe")
            self.assertEqual(store.writes[0][1]["stage"],
                             "firewall-activation-baseline")
            self.assertEqual(os.stat(args.attempt).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(args.activation_placement).st_mode & 0o777, 0o600)
            return {key: capture[key] for key in (
                "format", "stage", "status", "verified", "sourceSha", "runId",
                "nodeUid", "bootID", "admissionVersionId", "placementVersionId",
                "fixtureClientUid", "fixtureNodeUid", "fixtureBootID",
                "firewallBaselineEmpty", "ownedChains", "ownedSets", "podDeleted",
                "completedAt", "snapshotSha256")} | {
                    "captureKey": f"openclaw-enterprise/platform/{CURRENT}/789/"
                                  "firewall-activation-capture.json"}

        args = argparse.Namespace(expected_sha=CURRENT, bucket="private-bucket")
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "789"}), \
                patch.dict(SUT["BASELINE"], {"execute": baseline_execute}), \
                patch.dict(SUT["CLEANUP"], {
                    "snapshot_sha256": lambda *_: "0" * 64,
                    "cleanup_plan": lambda *_: ([], set(), set())}), \
                patch.dict(SUT["PLACEMENT"], {"fresh": lambda *_: None}):
            result = SUT["activation_firewall_baseline"](
                args, store, SELECTION, placement(), admission(), fixture_proof())
            self.assertEqual(called, ["probe"])
            self.assertEqual(result["captureVersionId"], "capture-version")
            capture["ownedChains"] = 1
            with self.assertRaises(ValueError):
                SUT["activation_firewall_baseline"](
                    args, CaptureStore(), SELECTION, placement(), admission(),
                    fixture_proof())
            capture["ownedChains"] = 0

            class FailingStore(CaptureStore):
                def write_once(self, *_):
                    raise ValueError("attempt upload failed")

            called.clear()
            with self.assertRaisesRegex(ValueError, "attempt upload failed"):
                SUT["activation_firewall_baseline"](
                    args, FailingStore(), SELECTION, placement(), admission(),
                    fixture_proof())
            self.assertEqual(called, [])

    def test_receipt_written_only_after_fresh_measurement_and_main_recheck(self):
        events = []
        store = Store()
        stamp = datetime.now(timezone.utc).isoformat()
        measured = {"nodeMetricsTimestamp": stamp, "nodeFsTimestamp": stamp,
                    "kubeletSummaryTimestamp": None, "plannedMemoryLimitBytes": 576 *
                    SUT["PLACEMENT"]["MIB"], "memoryMarginBytes": 128 *
                    SUT["PLACEMENT"]["MIB"]}

        def current_main(_):
            events.append("main")
            if events.count("main") == 1 and fail_main[0]:
                raise ValueError("main advanced")

        fail_main = [False]
        with patch.dict(SUT["execute"].__globals__, {
                "reviewed_config": lambda *_: (CONFIG, SELECTION),
                "selected_placement": lambda *_: (placement(), admission(),
                    f"openclaw-enterprise/platform/{EVIDENCE}/123/canary-admit.json",
                    f"openclaw-enterprise/platform/receipts/{EVIDENCE}/placement/456.json"),
                "verified_fixtures": lambda *_: (events.append("fixtures") or
                    ({"metadata": {"uid": "client-uid"}}, fixture_proof())),
                "require_application": lambda *_: events.append("app"),
                "fixture_capacity": lambda *_: (events.append("fixture-capacity") or
                    {"fixtureProjectedLimitBytes": 128 * SUT["PLACEMENT"]["MIB"]}),
                "activation_firewall_baseline": lambda *_: (
                    events.append("firewall") or {
                        "completedAt": stamp, "snapshotSha256": "a" * 64,
                        "captureVersionId": "baseline-version"}),
                "require_admitted": lambda *_: events.append("admitted"),
                "OWNERSHIP": {"PrivateStore": lambda *_: store}}), \
                patch.dict(SUT["CANARY"], {
                    "require_runtime_absent": lambda *_, **__: events.append("absent"),
                    "verify_live_pods": lambda *_: events.append("pods")}), \
                patch.dict(SUT["PLACEMENT"], {
                    "capacity": lambda *_, **__: (events.append("capacity") or measured),
                    "fresh": lambda *_: events.append("fresh")}), \
                patch.dict(SUT["CLEANUP"], {"require_current_main": current_main}), \
                patch.dict(os.environ, {"GITHUB_RUN_ID": "789"}):
            args = argparse.Namespace(phase="enforcer", expected_sha=CURRENT,
                                      bucket="private-bucket")
            record = SUT["execute"](args)
            self.assertEqual(record["capacity"]["plannedMemoryLimitBytes"],
                             576 * SUT["PLACEMENT"]["MIB"])
            self.assertEqual(record["fixtures"], fixture_proof())
            self.assertEqual(record["fixtureNodeUid"], "fixture-uid")
            self.assertEqual(len(store.writes), 1)
            self.assertEqual([event for event in events if event in
                              {"capacity", "firewall"}],
                             ["capacity", "firewall", "capacity"])
            self.assertTrue(store.writes[0][0].endswith(
                f"/{CURRENT}/789/activation-capacity-enforcer.json"))
            store.writes.clear()
            events.clear()
            fail_main[0] = True
            with self.assertRaisesRegex(ValueError, "main advanced"):
                SUT["execute"](args)
            self.assertEqual(store.writes, [])

    def test_fixture_first_gate_has_no_firewall_probe(self):
        events = []
        store = Store()
        stamp = datetime.now(timezone.utc).isoformat()
        measured = {"nodeMetricsTimestamp": stamp, "nodeFsTimestamp": stamp,
                    "kubeletSummaryTimestamp": None}
        with patch.dict(SUT["execute"].__globals__, {
                "reviewed_config": lambda *_: (CONFIG, SELECTION),
                "selected_placement": lambda *_: (placement(), admission(),
                    "canary-admit.json", "placement.json"),
                "require_admitted": lambda *_: events.append("admitted"),
                "require_application": lambda *_: events.append("app"),
                "fixture_capacity": lambda *_: {"fixtureImageCached": False},
                "activation_firewall_baseline": lambda *_: self.fail(
                    "firewall probe must follow first fixture pull"),
                "verified_fixtures": lambda *_: self.fail(
                    "fixtures must be absent before first pull"),
                "OWNERSHIP": {"PrivateStore": lambda *_: store}}), patch.dict(
                SUT["CANARY"], {
                    "require_runtime_absent": lambda *_, **__: events.append("absent"),
                    "verify_live_pods": lambda *_: events.append("pods")}), patch.dict(
                SUT["PLACEMENT"], {
                    "capacity": lambda *_: measured,
                    "fresh": lambda *_: None}), patch.dict(SUT["CLEANUP"], {
                    "require_current_main": lambda *_: None}), patch.dict(
                os.environ, {"GITHUB_RUN_ID": "789"}):
            record = SUT["execute"](argparse.Namespace(
                phase="fixtures", expected_sha=CURRENT, bucket="private-bucket"))
        self.assertIsNone(record["fixtures"])
        self.assertIsNone(record["firewallBaseline"])
        self.assertEqual(events, ["admitted", "app", "absent", "pods",
                                  "admitted", "app", "absent", "pods"])
        self.assertEqual(len(store.writes), 1)

    def test_enforcer_phase_blocks_runtime_or_fixture_drift_before_receipt(self):
        stamp = datetime.now(timezone.utc).isoformat()
        measured = {"nodeMetricsTimestamp": stamp, "nodeFsTimestamp": stamp,
                    "kubeletSummaryTimestamp": None}
        for drift in ("enforcer", "imageID", "containerID", "podIP"):
            with self.subTest(drift=drift):
                store = Store()
                checks = [0]
                inspections = [0]
                def absent(*_, **kwargs):
                    self.assertTrue(kwargs.get("allow_reviewed_fixtures"))
                    checks[0] += 1
                    if drift == "enforcer" and checks[0] == 2:
                        raise ValueError("firewall DaemonSet must be absent")
                def fixtures(*_):
                    inspections[0] += 1
                    proof = fixture_proof()
                    if inspections[0] > 1 and drift in {"imageID", "containerID", "podIP"}:
                        proof["pods"]["npq-allowed"][drift] = "replacement"
                    return {"metadata": {"uid": "client-uid"}}, proof
                with patch.dict(SUT["execute"].__globals__, {
                        "reviewed_config": lambda *_: (CONFIG, SELECTION),
                        "selected_placement": lambda *_: (placement(), admission(),
                            "canary-admit.json", "placement.json"),
                        "require_admitted": lambda *_: None,
                        "require_application": lambda *_: None,
                        "verified_fixtures": fixtures,
                        "fixture_capacity": lambda *_: {},
                        "activation_firewall_baseline": lambda *_: {
                            "completedAt": stamp, "captureVersionId": "baseline-version"},
                        "OWNERSHIP": {"PrivateStore": lambda *_: store}}), patch.dict(
                        SUT["CANARY"], {"require_runtime_absent": absent}), patch.dict(
                        SUT["PLACEMENT"], {"capacity": lambda *_, **__: measured,
                                           "fresh": lambda *_: None}), patch.dict(
                        SUT["CLEANUP"], {"require_current_main": lambda *_: None}), \
                        patch.dict(os.environ, {"GITHUB_RUN_ID": "789"}):
                    with self.assertRaisesRegex(ValueError, "absent|identity changed"):
                        SUT["execute"](argparse.Namespace(
                            phase="enforcer", expected_sha=CURRENT,
                            bucket="private-bucket"))
                self.assertEqual(store.writes, [])


if __name__ == "__main__":
    unittest.main()
