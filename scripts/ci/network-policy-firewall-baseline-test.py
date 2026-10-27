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
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SUT = runpy.run_path(str(ROOT / "scripts/network-policy-firewall-baseline.py"))
SHA = "a" * 40


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

    def run_baseline(self, plan, identities=None, delete_fails=False, create_fails=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            path.chmod(0o700)
            output = path / "baseline.json"
            config = json.loads(SUT["CONFIG"].read_text())
            events = []

            class Store:
                def __init__(self, _bucket):
                    self.store = self

                def check(self):
                    events.append("store-check")

                def write_once(self, key, record, limit):
                    events.append("capture")
                    self.capture = (key, record, limit)

            store = Store("bucket")
            def write_record(target, record, replace=False):
                events.append("record-" + record.get("status", "manifest"))
                target.write_text(json.dumps(record))
                target.chmod(0o600)

            def absent(_admit):
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
            helper = SUT["execute"].__globals__
            with patch.dict(SUT["PLATFORM"], {
                    "require_reviewed_execution_config": lambda *_: None,
                    "validate_config": lambda *_: config,
                    "protected_context": lambda *_: None,
                    "private_output": lambda *_: output}), \
                    patch.dict(SUT["CLEANUP"], {
                        "require_current_main": lambda *_: None,
                        "kubernetes_json": kube_json,
                        "write_record": write_record,
                        "snapshot": lambda *_: state,
                        "cleanup_plan": lambda *_: plan,
                        "snapshot_sha256": lambda *_: "0" * 64}), \
                    patch.dict(SUT["CANARY"], {"require_runtime_absent": absent}), \
                    patch.dict(SUT["OWNERSHIP"], {"PrivateStore": lambda *_: store}), \
                    patch.dict(helper, {"require_reviewed_manifest": lambda *_:
                                     json.loads(SUT["MANIFEST"].read_text()),
                                     "read_attempt": lambda *_: {"podToken": "1" * 48},
                                     "node_identity": node_identity,
                                     "system_pods": lambda: [],
                                     "get_pod": get_pod,
                                     "require_probe_pod": lambda *_, **__: "pod-uid",
                                     "wait_ready": lambda *_: None,
                                     "delete_probe": delete}), \
                    patch.dict("os.environ", {"GITHUB_RUN_ID": "123"}):
                error = None
                try:
                    result = SUT["execute"](argparse.Namespace(
                        config=SUT["CONFIG"], expected_sha=SHA,
                        bucket="bucket", attempt=path / "attempt.json", output=output))
                except ValueError as exc:
                    result = None
                    error = str(exc)
            return result, error, events, output.read_text(), getattr(store, "capture", None)

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
                                        "read_attempt": lambda *_: {"podToken": "1" * 48},
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
