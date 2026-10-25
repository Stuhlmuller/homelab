#!/usr/bin/env python3
"""Offline failure tests for the protected admitted-canary activation gate."""

import argparse
import copy
import json
import os
import runpy
import shutil
import subprocess
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


SUT = runpy.run_path("scripts/network-policy-activation-capacity.py")
CURRENT = "b" * 40
EVIDENCE = "a" * 40
NODE = SUT["NODE"]
ENFORCER = SUT["ENFORCER"]
SYSTEM = [{"namespace": "kube-system", "name": "flannel-1", "uid": "system-uid"}]
SELECTION = {"sourceSha": EVIDENCE, "runId": "123", "versionId": "admit-version"}
CONFIG = {"activationEnabled": True, "canary": {"node": NODE,
          "taint": f"{SUT['CANARY']['CANARY']}=true:NoSchedule"},
          "activationAdmission": SELECTION}


def placement():
    return {"format": 1, "verified": True, "sourceSha": EVIDENCE,
            "placementRunId": "456", "node": NODE, "canaryNode": NODE,
            "nodeUid": "node-uid", "bootID": "boot-id",
            "systemDaemonSetPods": SYSTEM}


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


def enforcer_pod():
    return {"metadata": {"namespace": "kube-system", "name": ENFORCER + "-abc",
                         "uid": "enforcer-uid", "ownerReferences": [{"kind": "DaemonSet",
                         "name": ENFORCER, "uid": "daemonset-uid", "controller": True}]},
            "spec": {"nodeName": NODE, "nodeSelector": {SUT["CANARY"]["CANARY"]: "true"},
                     "hostNetwork": True, "dnsPolicy": "ClusterFirstWithHostNet",
                     "priorityClassName": "system-node-critical",
                     "volumes": [{"name": "xtables-lock", "hostPath": {
                         "path": "/run/xtables.lock", "type": "FileOrCreate"}}],
                     "serviceAccountName": ENFORCER, "tolerations": [
                         {**SUT["CANARY"]["TAINT"], "operator": "Equal"}],
                     "containers": [{"name": "kube-router", "image": SUT["IMAGE"],
                                     "args": SUT["ARGS"], "imagePullPolicy": "IfNotPresent",
                                     "ports": [{"name": "health", "containerPort": 20244,
                                                "protocol": "TCP"}],
                                     "livenessProbe": {"httpGet": {"host": "127.0.0.1",
                                         "path": "/healthz", "port": "health"},
                                         "initialDelaySeconds": 10, "periodSeconds": 10},
                                     "readinessProbe": {"httpGet": {"host": "127.0.0.1",
                                         "path": "/healthz", "port": "health"},
                                         "initialDelaySeconds": 10, "periodSeconds": 10},
                                     "securityContext": {"privileged": True},
                                     "volumeMounts": [{"name": "xtables-lock",
                                                       "mountPath": "/run/xtables.lock"}],
                                     "resources": {
                                         "requests": {"cpu": "250m", "memory": "250Mi"},
                                         "limits": {"memory": "512Mi"}}}]},
            "status": {"phase": "Running", "conditions": [
                {"type": "Ready", "status": "True"}]}}


class ActivationCapacityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("yq"), "reviewed YAML parser is in the Nix dev shell")
    def test_enforcer_spec_accepts_the_reviewed_manifest(self):
        manifest = SUT["ROOT"] / "clusters/homelab/platform/network-policy/daemonset.yaml"
        rendered = subprocess.run(["yq", "ea", "-o=json", "-I=0", "[.]", str(manifest)],
                                  text=True, capture_output=True, check=True, timeout=30)
        daemonset = next(item for item in json.loads(rendered.stdout)
                         if item.get("kind") == "DaemonSet")
        SUT["require_enforcer_spec"](daemonset["spec"]["template"]["spec"])

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
                    "CONFIG": SUT["CONFIG"], "subprocess": subprocess}), \
                patch("subprocess.check_output", side_effect=git_output):
            self.assertEqual(SUT["reviewed_config"](CURRENT)[1], SELECTION)
            for bad in (None, {**SELECTION, "versionId": ""},
                        {**SELECTION, "sourceSha": "c" * 40}):
                config["activationAdmission"] = bad
                with self.subTest(selection=bad), self.assertRaises(ValueError):
                    SUT["reviewed_config"](CURRENT)

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
                args, store, SELECTION, placement(), admission())
            self.assertEqual(called, ["probe"])
            self.assertEqual(result["captureVersionId"], "capture-version")
            capture["ownedChains"] = 1
            with self.assertRaises(ValueError):
                SUT["activation_firewall_baseline"](
                    args, CaptureStore(), SELECTION, placement(), admission())
            capture["ownedChains"] = 0

            class FailingStore(CaptureStore):
                def write_once(self, *_):
                    raise ValueError("attempt upload failed")

            called.clear()
            with self.assertRaisesRegex(ValueError, "attempt upload failed"):
                SUT["activation_firewall_baseline"](
                    args, FailingStore(), SELECTION, placement(), admission())
            self.assertEqual(called, [])

    def test_fixture_phase_requires_one_pinned_ready_enforcer_and_no_foreign_pod(self):
        pod = enforcer_pod()
        daemonset = {"metadata": {"namespace": "kube-system", "name": ENFORCER,
                                  "uid": "daemonset-uid", "generation": 1},
                     "spec": {"template": {"spec": pod["spec"]}},
                     "status": {"observedGeneration": 1, "desiredNumberScheduled": 1,
                                "numberReady": 1, "numberAvailable": 1,
                                "numberMisscheduled": 0}}
        system = {"metadata": {**SYSTEM[0], "ownerReferences": [
                  {"kind": "DaemonSet", "name": "flannel", "controller": True}]},
                  "spec": {"nodeName": NODE}}
        listing = {"metadata": {}, "items": [system, pod]}
        labeled = {"metadata": {}, "items": [pod]}

        def kube_json(*args):
            if args[:4] == ("-n", "kube-system", "get", "daemonset"):
                return daemonset
            if args[:4] == ("-n", "kube-system", "get", "pods"):
                return labeled
            return listing

        with patch.dict(SUT["CANARY"], {"require_preflight_absent": lambda: None}), \
                patch.dict(SUT["CLEANUP"], {
                    "command": lambda *_: "",
                    "kubernetes_json": kube_json,
                    "complete_items": lambda value, _: value["items"],
                    "ready": lambda _: True}):
            self.assertEqual(SUT["verify_enforcer"](CONFIG, placement()), pod)
            changed = copy.deepcopy(pod)
            changed["spec"]["containers"][0]["image"] = "unreviewed"
            listing["items"] = [system, changed]
            with self.assertRaisesRegex(ValueError, "image"):
                SUT["verify_enforcer"](CONFIG, placement())
            for override in (lambda item: item["spec"]["containers"][0].update(
                                 command=["/bin/true"]),
                             lambda item: item["spec"]["containers"][0].pop(
                                 "readinessProbe"),
                             lambda item: item["spec"]["containers"][0][
                                 "securityContext"].update(privileged=False),
                             lambda item: item["spec"]["containers"][0].update(
                                 volumeMounts=[{"name": "host", "mountPath": "/usr/bin"}])):
                changed = copy.deepcopy(pod)
                override(changed)
                listing["items"] = [system, changed]
                with self.subTest(override=override), self.assertRaises(ValueError):
                    SUT["verify_enforcer"](CONFIG, placement())
            listing["items"] = [system, pod, {"metadata": {"namespace": "default",
                "name": "tenant", "uid": "foreign"}, "spec": {"nodeName": NODE}}]
            with self.assertRaisesRegex(ValueError, "foreign"):
                SUT["verify_enforcer"](CONFIG, placement())

    def test_receipt_written_only_after_fresh_measurement_and_main_recheck(self):
        events = []
        store = Store()
        stamp = datetime.now(timezone.utc).isoformat()
        measured = {"nodeMetricsTimestamp": stamp, "nodeFsTimestamp": stamp,
                    "kubeletSummaryTimestamp": None, "plannedMemoryLimitBytes": 704 *
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
                "activation_firewall_baseline": lambda *_: (
                    events.append("firewall") or {
                        "completedAt": stamp, "snapshotSha256": "a" * 64,
                        "captureVersionId": "baseline-version"}),
                "require_admitted": lambda *_: events.append("admitted"),
                "OWNERSHIP": {"PrivateStore": lambda *_: store}}), \
                patch.dict(SUT["CANARY"], {
                    "require_runtime_absent": lambda *_: events.append("absent"),
                    "verify_live_pods": lambda *_: events.append("pods")}), \
                patch.dict(SUT["PLACEMENT"], {
                    "capacity": lambda *_: (events.append("capacity") or measured),
                    "fresh": lambda *_: events.append("fresh")}), \
                patch.dict(SUT["CLEANUP"], {"require_current_main": current_main}), \
                patch.dict(os.environ, {"GITHUB_RUN_ID": "789"}):
            args = argparse.Namespace(phase="enforcer", expected_sha=CURRENT,
                                      bucket="private-bucket")
            record = SUT["execute"](args)
            self.assertEqual(record["capacity"]["plannedMemoryLimitBytes"],
                             704 * SUT["PLACEMENT"]["MIB"])
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


if __name__ == "__main__":
    unittest.main()
