#!/usr/bin/env python3
"""Fail-closed tests for the pre-enable firewall baseline stage."""

import argparse
import copy
import json
import os
import runpy
import shutil
import socketserver
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SUT = runpy.run_path(str(ROOT / "scripts/network-policy-firewall-baseline.py"))
SHA = "a" * 40
EVIDENCE_SHA = "b" * 40


def pod(token="token", uid="pod-uid"):
    candidate = json.loads(SUT["MANIFEST"].read_text())
    candidate["metadata"].update(uid=uid, annotations={SUT["RUN_ANNOTATION"]: token})
    candidate["spec"]["nodeName"] = SUT["NODE"]
    candidate["status"] = {"phase": "Running", "conditions":
                           [{"type": "Ready", "status": "True"}]}
    return candidate


class FirewallBaselineTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("kubectl"), "kubectl unavailable")
    def test_proxy_forwards_uid_precondition_and_rejects_api_conflict(self):
        for status in (202, 409):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                observed = {}

                class Handler(socketserver.StreamRequestHandler):
                    def handle(self):
                        observed["request"] = self.rfile.readline().decode().strip()
                        headers = {}
                        while line := self.rfile.readline().decode().strip():
                            name, value = line.split(":", 1)
                            headers[name.lower()] = value.strip()
                        observed["body"] = json.loads(self.rfile.read(
                            int(headers["content-length"])))
                        reason = "Accepted" if status == 202 else "Conflict"
                        self.wfile.write((f"HTTP/1.1 {status} {reason}\r\n"
                                          "Content-Length: 0\r\n\r\n").encode())

                with socketserver.TCPServer(("127.0.0.1", 0), Handler) as upstream:
                    config = path / "kubeconfig.json"
                    config.write_text(json.dumps({
                        "apiVersion": "v1", "kind": "Config", "current-context": "fixture",
                        "clusters": [{"name": "fixture", "cluster": {"server":
                                      f"http://127.0.0.1:{upstream.server_address[1]}"}}],
                        "contexts": [{"name": "fixture", "context":
                                      {"cluster": "fixture", "user": "fixture"}}],
                        "users": [{"name": "fixture", "user": {}}]}))
                    thread = threading.Thread(target=upstream.handle_request)
                    thread.start()
                    try:
                        with patch.dict(os.environ, {"KUBECONFIG": str(config)}):
                            if status == 409:
                                with self.assertRaisesRegex(ValueError, "UID changed"):
                                    SUT["delete_with_uid"]("pod-uid", path)
                            else:
                                SUT["delete_with_uid"]("pod-uid", path)
                    finally:
                        thread.join(timeout=2)
                self.assertEqual(observed["request"],
                                 f"DELETE {SUT['POD_API_PATH']} HTTP/1.1")
                self.assertEqual(observed["body"]["preconditions"], {"uid": "pod-uid"})

    def test_manifest_must_match_exact_source_and_narrow_pod_pattern(self):
        source = SUT["MANIFEST"].read_text()
        with patch.dict(SUT["CLEANUP"], {"command": lambda *_: source}):
            self.assertEqual(SUT["require_reviewed_manifest"](SHA), json.loads(source))
        with patch.dict(SUT["CLEANUP"], {"command": lambda *_: source + " "}):
            with self.assertRaisesRegex(ValueError, "differs"):
                SUT["require_reviewed_manifest"](SHA)
        with patch.dict(SUT["CLEANUP"], {"command": lambda *_: source}), \
                patch.dict(SUT["require_reviewed_manifest"].__globals__,
                           {"MANIFEST_SHA256": "0" * 64}):
            with self.assertRaisesRegex(ValueError, "differs"):
                SUT["require_reviewed_manifest"](SHA)

    def test_recovery_probe_rejects_another_admission_marker_before_pod_access(self):
        state = {"metadata": {"uid": "node-uid", "annotations": {
            SUT["CANARY"]["ADMISSION"]: f"{EVIDENCE_SHA}:124"}},
            "status": {"nodeInfo": {"bootID": "boot"}}}
        with patch.dict(SUT["CANARY"], {
                "node_state": lambda *_: (state, False, True)}), patch.dict(
                SUT["CLEANUP"], {"kubernetes_json": lambda *_: self.fail(
                    "probe should not inspect or create a Pod")}), self.assertRaisesRegex(
                ValueError, "admission marker"):
            SUT["recovery_node_identity"]({}, EVIDENCE_SHA, "123")

    def test_probe_rejects_wrong_node_token_command_and_capability(self):
        valid = pod()
        self.assertEqual(SUT["require_probe_pod"](valid, "token", "pod-uid", True),
                         "pod-uid")
        terminating = copy.deepcopy(valid)
        terminating["metadata"]["deletionTimestamp"] = "2026-10-25T00:00:00Z"
        with self.assertRaises(ValueError):
            SUT["require_probe_pod"](terminating, "token", "pod-uid")
        self.assertEqual(SUT["require_probe_owner"](
            terminating, "token", "pod-uid"), "pod-uid")
        changes = (
            ("token", lambda item: item["metadata"]["annotations"].update(
                {SUT["RUN_ANNOTATION"]: "other"})),
            ("uid", lambda item: item["metadata"].update(uid="replacement")),
            ("node", lambda item: item["spec"].update(nodeName="zimaboard-1")),
            ("command", lambda item: item["spec"]["containers"][0].update(args=["sh"])),
            ("capability", lambda item: item["spec"]["containers"][0]["securityContext"]
             ["capabilities"].update(add=["SYS_ADMIN"])),
            ("lifecycle", lambda item: item["spec"]["containers"][0].update(
                lifecycle={"postStart": {"exec": {"command": ["iptables", "-F"]}}})),
            ("environment", lambda item: item["spec"]["containers"][0].update(
                env=[{"name": "LD_PRELOAD", "value": "/payload.so"}])),
            ("sidecar", lambda item: item["spec"]["containers"].append({"name": "extra"})),
        )
        for name, change in changes:
            with self.subTest(name=name):
                candidate = copy.deepcopy(valid)
                change(candidate)
                with self.assertRaises(ValueError):
                    SUT["require_probe_pod"](candidate, "token", "pod-uid", True)

    def test_delete_refuses_replaced_pod_name(self):
        commands = []
        with patch.dict(SUT["delete_probe"].__globals__,
                        {"get_pod": iter((pod(), pod(uid="replacement"))).__next__,
                         "delete_with_uid": lambda uid, _directory: commands.append(uid)}):
            with self.assertRaisesRegex(ValueError, "reused"):
                SUT["delete_probe"]("token", Path("/unused"), "pod-uid")
        self.assertEqual(len(commands), 1)

    def test_lost_create_response_can_delete_only_matching_run_token(self):
        commands = []
        with patch.dict(SUT["delete_probe"].__globals__,
                        {"get_pod": iter((pod(), None)).__next__,
                         "delete_with_uid": lambda uid, _directory: commands.append(uid)}):
            SUT["delete_probe"]("token", Path("/unused"))
        self.assertEqual(len(commands), 1)
        with patch.dict(SUT["delete_probe"].__globals__,
                        {"get_pod": lambda: pod(token="other")}):
            with self.assertRaisesRegex(ValueError, "ownership"):
                SUT["delete_probe"]("token", Path("/unused"))

    def test_recovery_can_remove_own_pod_after_admission_mutates_spec(self):
        unsafe = pod()
        unsafe["spec"]["containers"][0]["lifecycle"] = {
            "postStart": {"exec": {"command": ["iptables", "-F"]}}}
        unsafe["metadata"]["deletionTimestamp"] = "2026-10-25T00:00:00Z"
        deleted = []
        with patch.dict(SUT["delete_probe"].__globals__,
                        {"get_pod": iter((unsafe, None)).__next__,
                         "delete_with_uid": lambda uid, _directory: deleted.append(uid)}):
            SUT["delete_probe"]("token", Path("/unused"), "pod-uid")
        self.assertEqual(deleted, ["pod-uid"])

    def test_recovery_probe_requires_exact_canary_toleration(self):
        valid = pod()
        valid["spec"]["tolerations"] = [SUT["CANARY_TOLERATION"]]
        self.assertEqual(SUT["require_probe_pod"](
            valid, "token", "pod-uid", True, recovery=True), "pod-uid")
        for tolerations in ([], [{"key": SUT["CLEANUP"]["CANARY"],
                                   "operator": "Exists", "effect": "NoSchedule"}],
                            [SUT["CANARY_TOLERATION"], {"key": SUT["CLEANUP"]["CANARY"],
                                                          "operator": "Exists"}]):
            with self.subTest(tolerations=tolerations):
                changed = copy.deepcopy(valid)
                changed["spec"]["tolerations"] = tolerations
                with self.assertRaisesRegex(ValueError, "preflight Pod"):
                    SUT["require_probe_pod"](changed, "token", "pod-uid", True,
                                             recovery=True)

    def test_recovery_attempt_binds_selected_run_version_and_node(self):
        placement = {"placementRunId": "456", "nodeUid": "node-uid", "bootID": "boot-id"}
        attempt = {"format": 1, "stage": "canary-admit-recover", "status": "attempted",
                   "verified": False, "sourceSha": SHA, "runId": "123",
                   "evidenceSourceSha": EVIDENCE_SHA,
                   "node": SUT["NODE"], "nodeUid": "node-uid", "bootID": "boot-id",
                   "admissionRunId": "789", "placementRunId": "456",
                   "placementVersionId": "version-2", "podToken": "1" * 48}
        with patch.dict(SUT["PLATFORM"], {"read_private_json": lambda *_: attempt}):
            self.assertEqual(SUT["read_recovery_attempt"](Path("/unused"), SHA,
                                                          EVIDENCE_SHA, "123",
                                                          placement), attempt)
            self.assertEqual(SUT["read_attempt"](Path("/unused"), SHA, "123",
                                                  stage=None), attempt)
            attempt["stage"] = "canary-abort"
            self.assertEqual(SUT["read_recovery_attempt"](Path("/unused"), SHA,
                                                          EVIDENCE_SHA, "123",
                                                          placement), attempt)
            attempt["stage"] = "canary-admit-recover"
            with self.assertRaisesRegex(ValueError, "preflight ownership"):
                SUT["read_attempt"](Path("/unused"), SHA, "123")
            for changed in ({"admissionRunId": ""}, {"evidenceSourceSha": SHA},
                            {"placementRunId": "455"},
                            {"placementVersionId": ""}, {"nodeUid": "replacement"},
                            {"bootID": "new-boot"}, {"podToken": "a" * 47}):
                with self.subTest(changed=changed), patch.dict(attempt, changed):
                    with self.assertRaises(ValueError):
                        SUT["read_recovery_attempt"](Path("/unused"), SHA,
                                                     EVIDENCE_SHA, "123",
                                                     placement)

    def test_release_probe_requires_taint_only_and_binds_attempt(self):
        placement = {"placementRunId": "456", "nodeUid": "node-uid", "bootID": "boot-id"}
        attempt = {"format": 1, "stage": "canary-release-recover", "status": "attempted",
                   "verified": False, "sourceSha": SHA, "runId": "123",
                   "evidenceSourceSha": EVIDENCE_SHA, "node": SUT["NODE"],
                   "nodeUid": "node-uid", "bootID": "boot-id", "admissionRunId": "789",
                   "placementRunId": "456", "placementVersionId": "version-2",
                   "releaseSourceSha": SHA, "releaseRunId": "234",
                   "cleanupRunId": "345", "captureRunId": "456",
                   "cleanupPodUid": "cleanup-uid", "podToken": "1" * 48}
        with patch.dict(SUT["PLATFORM"], {"read_private_json": lambda *_: attempt}):
            self.assertEqual(SUT["read_recovery_attempt"](
                Path("/unused"), SHA, EVIDENCE_SHA, "123", placement, True), attempt)
            self.assertEqual(SUT["read_attempt"](
                Path("/unused"), SHA, "123", stage=None), attempt)
            with patch.dict(attempt, {"cleanupRunId": ""}):
                with self.assertRaisesRegex(ValueError, "release recovery probe"):
                    SUT["read_recovery_attempt"](
                        Path("/unused"), SHA, EVIDENCE_SHA, "123", placement, True)
        state = {"metadata": {"uid": "node-uid", "annotations": {
            SUT["CANARY"]["ADMISSION"]: f"{EVIDENCE_SHA}:789"}},
            "status": {"nodeInfo": {"bootID": "boot-id"}}}
        for labeled, tainted, release_clean in ((True, True, False),
                                                 (False, False, False),
                                                 (False, True, True)):
            with self.subTest(labeled=labeled, tainted=tainted), patch.dict(SUT["CANARY"], {
                    "node_state": lambda *_: (state, labeled, tainted)}), patch.dict(
                    SUT["CLEANUP"], {"kubernetes_json": lambda *_: self.fail(
                        "release probe should reject before Pod access")}), self.assertRaisesRegex(
                    ValueError, "isolation state changed"):
                SUT["recovery_node_identity"](placement, EVIDENCE_SHA, "789",
                                              True, release_clean)

    def test_release_probe_requires_owner_before_cluster_access(self):
        config = json.loads(SUT["CONFIG"].read_text())
        with patch.dict(SUT["PLATFORM"], {
                "require_reviewed_execution_config": lambda *_: None,
                "validate_config": lambda *_: config,
                "protected_context": lambda *_: None}), patch.dict(SUT["OWNERSHIP"], {
                "require_owner_attestation": lambda: (_ for _ in ()).throw(
                    ValueError("owner required"))}), patch.dict(SUT["CLEANUP"], {
                "require_current_main": lambda *_: self.fail("cluster or main access")}), \
                self.assertRaisesRegex(ValueError, "owner required"):
            SUT["execute"](argparse.Namespace(
                config=SUT["CONFIG"], expected_sha=SHA, release_recovery=True,
                recovery_placement=Path("/unused")))

    def test_activation_attempt_binds_verified_admission_and_is_recoverable(self):
        config = {"activationAdmission": {"sourceSha": EVIDENCE_SHA,
                  "runId": "987", "versionId": "admit-version"}}
        placement = {"placementRunId": "456", "nodeUid": "node-uid",
                     "bootID": "boot-id", "fixtureNodeUid": "fixture-uid",
                     "fixtureBootID": "fixture-boot"}
        marker = {"format": 1, "stage": "firewall-activation-baseline",
                  "status": "attempted", "verified": False, "sourceSha": SHA,
                  "runId": "123", "node": SUT["NODE"], "nodeUid": "node-uid",
                  "bootID": "boot-id", "admissionSourceSha": EVIDENCE_SHA,
                  "admissionRunId": "987", "admissionVersionId": "admit-version",
                  "placementRunId": "456", "placementVersionId": "place-version",
                  "fixtureNodeUid": "fixture-uid", "fixtureBootID": "fixture-boot",
                  "fixtureClientUid": "client-uid",
                  "podToken": "1" * 48}
        with patch.dict(SUT["PLATFORM"], {"read_private_json": lambda *_: marker}):
            self.assertEqual(SUT["read_activation_attempt"](
                Path("/unused"), SHA, EVIDENCE_SHA, "123", placement, config), marker)
            self.assertEqual(SUT["read_attempt"](Path("/unused"), SHA, "123",
                                                  stage=None), marker)
            for changed in ({"admissionVersionId": "wrong"}, {"nodeUid": "replaced"},
                            {"fixtureNodeUid": "replaced"},
                            {"fixtureClientUid": ""}, {"placementVersionId": ""}):
                with self.subTest(changed=changed), patch.dict(marker, changed):
                    with self.assertRaises(ValueError):
                        SUT["read_activation_attempt"](
                            Path("/unused"), SHA, EVIDENCE_SHA, "123", placement, config)

    def run_baseline(self, plan, identities=None, delete_fails=False, create_fails=False,
                     recovery=False, activation=False, assigned=None, capture_fails=False,
                     admitted=True, release=False, release_clean=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            path.chmod(0o700)
            output = path / "baseline.json"
            config = json.loads(SUT["CONFIG"].read_text())
            if release or activation:
                config["activationEnabled"] = True
            if activation:
                config["activationAdmission"] = {
                    "sourceSha": EVIDENCE_SHA, "runId": "987", "versionId": "admit-version"}
            events = []
            stale = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            placement = {"format": 1, "verified": True,
                         "sourceSha": EVIDENCE_SHA if recovery or activation else SHA,
                         "placementRunId": "456", "node": SUT["NODE"],
                         "canaryNode": SUT["NODE"], "nodeUid": "node-uid",
                         "bootID": "boot-id", "measured": True,
                         "fixtureNode": "zimaboard-1", "fixtureNodeUid": "fixture-uid",
                         "fixtureBootID": "fixture-boot",
                         "fixtureCapacity": {"fixtureImageCached": False},
                         "isolatedTaint": config["canary"]["taint"],
                         "firewallBaselineEmpty": True,
                         "baselineSourceSha": EVIDENCE_SHA if recovery or activation else SHA,
                         "baselineRunId": "789", "baselineCapturedAt": stale,
                         "baselineCaptureSha256": "0" * 64,
                         "baselineCaptureVersionId": "version-1",
                         "systemDaemonSetPods": [], "capturedAt": stale}
            marker = {"format": 1, "stage": "firewall-activation-baseline" if activation else
                      "canary-admit-recover",
                      "status": "attempted", "verified": False, "sourceSha": SHA,
                      "evidenceSourceSha": EVIDENCE_SHA,
                      "runId": "123", "node": SUT["NODE"], "nodeUid": "node-uid",
                      "bootID": "boot-id", "admissionRunId": "987",
                      "placementRunId": "456", "placementVersionId": "version-2",
                      "podToken": "1" * 48}
            if release:
                marker.update(stage="canary-release-recover", releaseSourceSha=EVIDENCE_SHA,
                              releaseRunId="234", cleanupRunId="345", captureRunId="456",
                              cleanupPodUid="cleanup-uid")
            if activation:
                marker.update(admissionSourceSha=EVIDENCE_SHA,
                              admissionVersionId="admit-version",
                              fixtureNodeUid="fixture-uid", fixtureBootID="fixture-boot",
                              fixtureClientUid="client-uid")

            class Store:
                def __init__(self, _bucket):
                    self.store = self

                def check(self):
                    events.append("store-check")

                def write_once(self, key, record, limit):
                    events.append("capture")
                    if capture_fails:
                        raise ValueError("capture receipt upload failed")
                    self.capture = (key, record, limit)

            store = Store("bucket")
            def write_record(target, record, replace=False):
                events.append("record-" + record.get("status", "manifest"))
                target.write_text(json.dumps(record))
                target.chmod(0o600)

            def absent(_admit, **kwargs):
                if activation:
                    self.assertTrue(kwargs.get("allow_reviewed_fixtures"))
                events.append("runtime-absent")

            def delete(*_args):
                events.append("delete")
                if delete_fails:
                    raise ValueError("preflight Pod deletion was not observed")

            def get_pod():
                events.append("pod-absent")
                return None

            state = {"backend": "nft", "nft": "empty", "legacy": "empty",
                     "ip6nft": "empty", "ip6legacy": "empty", "ipset": ""}
            identities = iter(identities) if identities is not None else None
            def node_identity():
                return next(identities) if identities is not None else ("node-uid", "boot-id")
            def kube_json(*_args):
                if create_fails:
                    raise ValueError("Pod create response lost")
                return pod()
            def fixture_inspect(_config, require_firewall=True):
                self.assertFalse(require_firewall)
                events.append("fixtures-checked")
                node = {"metadata": {"uid": "node-uid"},
                        "status": {"nodeInfo": {"bootID": "boot-id"}}}
                server = {"metadata": {"uid": "fixture-uid"},
                          "status": {"nodeInfo": {"bootID": "fixture-boot"}}}
                client = {"metadata": {"uid": "client-uid"}}
                return node, server, {"npq-client": client}, None, "policy-sha"
            helper = SUT["execute"].__globals__
            with patch.dict(SUT["PLATFORM"], {
                    "require_reviewed_execution_config": lambda *_: None,
                    "validate_config": lambda *_: config,
                    "protected_context": lambda *_: None,
                    "private_output": lambda *_: output,
                    "read_private_json": lambda target: placement if target.name ==
                    "placement.json" else marker}), \
                    patch.dict(SUT["CLEANUP"], {
                        "require_current_main": lambda *_: None,
                        "kubernetes_json": kube_json,
                        "write_record": write_record,
                        "snapshot": lambda *_: state,
                        "cleanup_plan": lambda *_: plan,
                        "snapshot_sha256": lambda *_: "0" * 64}), \
                    patch.dict(SUT["CANARY"], {
                        "require_runtime_absent": absent,
                        "verify_live_pods": lambda *_: events.append("pods-checked"),
                        "node_state": lambda *_: ({}, admitted if activation else False,
                                                  admitted if activation else not release_clean),
                        "clean_release_pods": lambda *_: ([{
                            "namespace": "default", "name": "workload", "uid": "workload-uid"}]
                            if assigned is None else assigned),
                        "require_release_runtime_quiesced": lambda *_: events.append(
                            "release-runtime-quiesced"),
                        "require_release_source": lambda *_: events.append(
                            "release-source-checked"),
                        "require_exclusive_canary_label": lambda *_: events.append(
                            "exclusive-label")}), \
                    patch.dict(SUT["OWNERSHIP"], {"PrivateStore": lambda *_: store,
                                                  "require_owner_attestation": lambda: None}), \
                    patch.dict(SUT["QUALIFY"], {"inspect": fixture_inspect}), \
                    patch.dict(helper, {"require_reviewed_manifest": lambda *_:
                                     json.loads(SUT["MANIFEST"].read_text()),
                                     "read_attempt": lambda *_, **__: marker if recovery else
                                     {"podToken": "1" * 48},
                                     "read_activation_attempt": lambda *_: marker,
                                     "node_identity": node_identity,
                                     "recovery_node_identity": lambda *_: node_identity(),
                                     "system_pods": lambda: [] if assigned is None else assigned,
                                     "get_pod": get_pod,
                                     "require_probe_pod": lambda *_, **__: "pod-uid",
                                     "wait_ready": lambda *_, **__: None,
                                     "delete_probe": delete}), \
                    patch.dict("os.environ", {"GITHUB_RUN_ID": "123"}):
                error = None
                try:
                    result = SUT["execute"](argparse.Namespace(
                        config=SUT["CONFIG"], expected_sha=SHA,
                        bucket="bucket", attempt=path / "attempt.json", output=output,
                        evidence_source_sha=EVIDENCE_SHA if recovery or activation else None,
                        recovery_placement=path / "placement.json" if recovery else None,
                        activation_placement=path / "placement.json" if activation else None,
                        release_recovery=release))
                except ValueError as exc:
                    result = None
                    error = str(exc)
            return (result, error, events, output.read_text() if output.exists() else None,
                    getattr(store, "capture", None))

    def test_owned_object_fails_and_still_deletes_probe(self):
        result, error, events, receipt, capture = self.run_baseline(
            ([('iptables-nft', '-D', 'owned')], 1, 0))
        self.assertIsNone(result)
        self.assertIn("not empty", error)
        self.assertIn("delete", events)
        self.assertIsNone(capture)
        self.assertFalse(json.loads(receipt)["verified"])

    def test_verified_capture_follows_pod_deletion_and_absence(self):
        result, error, events, receipt, capture = self.run_baseline(([], 0, 0))
        self.assertIsNone(error)
        self.assertTrue(result["firewallBaselineEmpty"])
        self.assertTrue(json.loads(receipt)["podDeleted"])
        self.assertLess(events.index("delete"), events.index("capture"))
        self.assertLess(len(events) - 1 - events[::-1].index("runtime-absent"),
                        events.index("capture"))
        self.assertTrue(capture[1]["verified"])
        self.assertEqual(capture[1]["nodeUid"], "node-uid")
        self.assertEqual(capture[1]["bootID"], "boot-id")
        self.assertEqual(capture[1]["snapshot"]["backend"], "nft")

    def test_boot_id_change_after_pod_deletion_cannot_issue_receipt(self):
        original = ("node-uid", "boot-id")
        result, error, events, receipt, capture = self.run_baseline(
            ([], 0, 0), identities=[original] * 4 + [("node-uid", "new-boot")])
        self.assertIsNone(result)
        self.assertIn("Node or assigned Pods changed", error)
        self.assertIn("delete", events)
        self.assertIsNone(capture)
        self.assertFalse(json.loads(receipt)["verified"])

    def test_unobserved_pod_deletion_cannot_issue_receipt(self):
        result, error, events, receipt, capture = self.run_baseline(
            ([], 0, 0), delete_fails=True)
        self.assertIsNone(result)
        self.assertIn("deletion was not observed", error)
        self.assertIn("delete", events)
        self.assertIsNone(capture)
        self.assertFalse(json.loads(receipt)["verified"])

    def test_lost_create_response_still_attempts_owned_pod_cleanup(self):
        result, error, events, receipt, capture = self.run_baseline(
            ([], 0, 0), create_fails=True)
        self.assertIsNone(result)
        self.assertIn("response lost", error)
        self.assertIn("delete", events)
        self.assertIsNone(capture)
        self.assertFalse(json.loads(receipt)["verified"])

    def test_recovery_probes_empty_firewall_after_placement_expiry(self):
        result, error, events, receipt, capture = self.run_baseline(([], 0, 0),
                                                                     recovery=True)
        self.assertIsNone(error)
        proof = json.loads(receipt)
        self.assertEqual(proof["stage"], "firewall-recovery-proof")

        self.assertEqual(proof["sourceSha"], SHA)
        self.assertEqual(proof["evidenceSourceSha"], EVIDENCE_SHA)
        self.assertEqual(proof["runId"], "123")
        self.assertEqual(proof["admissionRunId"], "987")
        self.assertEqual(proof["placementRunId"], "456")
        self.assertEqual(proof["placementVersionId"], "version-2")
        self.assertEqual(proof["nodeUid"], "node-uid")
        self.assertEqual(proof["bootID"], "boot-id")
        self.assertTrue(proof["firewallBaselineEmpty"])
        self.assertTrue(proof["podDeleted"])
        self.assertEqual(proof["snapshotSha256"], "0" * 64)
        self.assertEqual(proof["captureKey"],
                         f"openclaw-enterprise/platform/{SHA}/123/"
                         "firewall-recovery-capture.json")
        self.assertEqual(capture[0], proof["captureKey"])
        self.assertEqual(capture[1]["evidenceSourceSha"], EVIDENCE_SHA)
        self.assertIn("snapshot", capture[1])
        self.assertLess(events.index("delete"), events.index("capture"))
        self.assertEqual(result["captureKey"], proof["captureKey"])

    def test_release_probe_accepts_active_config_only_with_quiesced_runtime(self):
        result, error, events, receipt, capture = self.run_baseline(
            ([], 0, 0), recovery=True, release=True)
        self.assertIsNone(error)
        self.assertEqual(result["stage"], "firewall-release-recovery-proof")
        self.assertEqual(result["cleanupRunId"], "345")
        self.assertEqual(result["releaseRunId"], "234")
        self.assertTrue(result["podDeleted"])
        self.assertLess(events.index("delete"), events.index("capture"))
        self.assertEqual(events.count("release-runtime-quiesced"), 2)
        self.assertNotIn("runtime-absent", events)
        self.assertEqual(result["observedState"], "taint-only")
        clean, error, events, _, _ = self.run_baseline(
            ([], 0, 0), recovery=True, release=True, release_clean=True)
        self.assertIsNone(error)
        self.assertEqual(clean["observedState"], "clean")
        self.assertEqual(clean["observedPods"], [{"namespace": "default",
                                                  "name": "workload",
                                                  "uid": "workload-uid"}])
        self.assertTrue(clean["podDeleted"])

    def test_activation_baseline_requires_empty_host_and_verified_deletion(self):
        result, error, events, receipt, capture = self.run_baseline(
            ([], 0, 0), activation=True)
        self.assertIsNone(error)
        self.assertEqual(result["stage"], "firewall-activation-baseline")
        self.assertTrue(result["podDeleted"])
        self.assertEqual(result["admissionVersionId"], "admit-version")
        self.assertEqual(capture[0],
                         f"openclaw-enterprise/platform/{SHA}/123/"
                         "firewall-activation-capture.json")
        self.assertLess(events.index("delete"), events.index("capture"))
        for options, message in (({"plan": ([('iptables-nft', '-D', 'owned')], 1, 0)},
                                  "not empty"),
                                 ({"plan": ([], 0, 0), "delete_fails": True},
                                  "deletion was not observed"),
                                 ({"plan": ([], 0, 0), "capture_fails": True},
                                  "capture receipt upload failed"),
                                 ({"plan": ([], 0, 0), "admitted": False},
                                  "admitted Node isolation")):
            candidate, failure, activity, output, saved = self.run_baseline(
                activation=True, **options)
            with self.subTest(message=message):
                self.assertIsNone(candidate)
                self.assertIn(message, failure)
                self.assertIsNone(saved)
                if message != "admitted Node isolation":
                    self.assertIn("delete", activity)
                self.assertFalse(json.loads(output)["verified"] if output else False)
        changed, failure, activity, output, saved = self.run_baseline(
            ([], 0, 0), activation=True,
            identities=[("node-uid", "boot-id")] * 4 + [("replaced", "boot-id")])
        self.assertIsNone(changed)
        self.assertIn("Node or assigned Pods changed", failure)
        self.assertIn("delete", activity)
        self.assertIsNone(saved)

    def test_recovery_refuses_owned_firewall_and_deletes_probe(self):
        result, error, events, receipt, capture = self.run_baseline(
            ([("iptables-nft", "-D", "owned")], 1, 0), recovery=True)
        self.assertIsNone(result)
        self.assertIn("not empty", error)
        self.assertIn("delete", events)
        self.assertIsNone(capture)
        self.assertFalse(json.loads(receipt)["verified"])

    def test_recovery_refuses_changed_system_pod_before_probe_creation(self):
        result, error, events, receipt, capture = self.run_baseline(
            ([], 0, 0), recovery=True,
            assigned=[{"namespace": "kube-system", "name": "replacement", "uid": "new"}])
        self.assertIsNone(result)
        self.assertIn("system Pods differ", error)
        self.assertIsNone(receipt)
        self.assertIsNone(capture)
        self.assertNotIn("delete", events)

    def test_recovery_never_proves_absence_before_probe_deletion(self):
        result, error, events, receipt, capture = self.run_baseline(
            ([], 0, 0), recovery=True, delete_fails=True)
        self.assertIsNone(result)
        self.assertIn("deletion was not observed", error)
        self.assertIsNone(capture)
        self.assertFalse(json.loads(receipt)["verified"])

    def test_recovery_deletes_only_original_token_pod_and_cannot_certify_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            output = path / "recover.json"
            config = json.loads(SUT["CONFIG"].read_text())
            config["activationEnabled"] = True
            config["canary"]["node"] = "zimaboard-2"
            deleted = []
            pods = iter((pod(token="1" * 48), None))

            def write_record(target, record, replace=False):
                target.write_text(json.dumps(record))

            helper = SUT["recover"].__globals__
            with patch.dict(SUT["PLATFORM"], {
                    "require_reviewed_execution_config": lambda *_: None,
                    "validate_config": lambda *_: config,
                    "protected_context": lambda *_: None,
                    "private_output": lambda *_: output}), \
                    patch.dict(SUT["CLEANUP"], {"require_current_main": lambda *_: None,
                                                "write_record": write_record}), \
                    patch.dict(SUT["CANARY"], {"require_preflight_absent": lambda: None}), \
                    patch.dict(helper, {"require_reviewed_manifest": lambda *_:
                                     (_ for _ in ()).throw(ValueError("old manifest removed")),
                                        "read_attempt": lambda *_, **__: {"podToken": "1" * 48},
                                        "get_pod": pods.__next__,
                                        "delete_probe": lambda *args: deleted.append(args)}), \
                    patch.dict("os.environ", {"GITHUB_RUN_ID": "123"}):
                result = SUT["recover"](argparse.Namespace(
                    config=SUT["CONFIG"], expected_sha=SHA,
                    baseline_source_sha="b" * 40, baseline_run_id="456",
                    attempt=path / "attempt.json", output=output))
            self.assertTrue(result["podDeleted"])
            self.assertEqual(deleted[0][0], "1" * 48)
            self.assertEqual(deleted[0][2], "pod-uid")
            self.assertNotIn("firewallBaselineEmpty", result)


if __name__ == "__main__":
    unittest.main()
