#!/usr/bin/env python3
"""Fail-closed fixtures for private firewall snapshot capture and approval."""

import copy
import base64
import hashlib
import json
import runpy
import stat
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SUT = runpy.run_path(str(ROOT / "scripts/network-policy-ownership.py"))
FIXTURE = runpy.run_path(str(ROOT / "scripts/ci/network-policy-cleanup-test.py"))
SHA = "a" * 40
EVIDENCE_SHA = "b" * 40
NODE = "zimaboard-1"


def qualification():
    cases = [{"source": source, "target": target, "port": port,
              "protocol": protocol, "permitted": permitted,
              "observed": "NPQ_ALLOWED" if permitted else "NPQ_DENIED"}
             for source, target, port, protocol, permitted in SUT["QUALIFY"]["CASES"]]
    cases += [{"source": "npq-client", "target": "kube-dns", "port": 53,
               "protocol": protocol, "permitted": True, "observed": "NPQ_DNS_ALLOWED"}
              for protocol in ("TCP", "UDP")]
    return {"format": 1, "result": "traffic-probe-passed-lifecycle-unverified",
            "sourceSha": EVIDENCE_SHA, "node": NODE, "nodeUid": "node-uid", "bootID": "boot-id",
            "cases": cases, "unverifiedLifecycleScenarios":
            list(SUT["QUALIFY"]["LIFECYCLE_SCENARIOS"])}


class MemoryStore:
    def __init__(self):
        self.records = {
            f"{SUT['PREFIX']}/receipts/{EVIDENCE_SHA}/placement.json": {
                "format": 1, "verified": True, "sourceSha": EVIDENCE_SHA, "node": NODE,
                "nodeUid": "node-uid", "bootID": "boot-id", "firewallBaselineEmpty": True,
            },
            f"{SUT['PREFIX']}/{EVIDENCE_SHA}/7/qualification.json": qualification(),
        }

    def read(self, key, _limit):
        return (json.dumps(self.records[key], sort_keys=True) + "\n").encode()

    def write_once(self, key, record, _limit):
        if key in self.records:
            raise ValueError("duplicate private receipt")
        self.records[key] = copy.deepcopy(record)


class FirewallOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.owner = patch.dict("os.environ", {
            "GITHUB_ACTOR_ID": SUT["OWNER_ACTOR_ID"], "GITHUB_RUN_ATTEMPT": "1",
        })
        self.owner.start()
        self.addCleanup(self.owner.stop)
        self.store = MemoryStore()
        self.config = {"canary": {"node": NODE}}
        self.state = FIXTURE["state"]()
        self.cleanup = SUT["CLEANUP"]
        self.patches = patch.dict(self.cleanup, {
            "inspect_cluster": lambda *_: ("cleanup-pod", "cleanup-pod-uid"),
            "snapshot": lambda *_: self.state,
            "require_current_main": lambda *_: None,
            "require_firewall_removal_transition": lambda *_: None,
        })
        self.patches.start()
        self.addCleanup(self.patches.stop)

    def test_capture_and_approval_pin_full_snapshot_and_probe(self):
        SUT["capture"](self.store, SHA, EVIDENCE_SHA, "8", "7", self.config)
        candidate = self.store.records[f"{SUT['PREFIX']}/{SHA}/8/firewall-capture.json"]
        self.assertFalse(candidate["verified"])
        self.assertEqual(candidate["snapshot"], self.state)
        self.assertEqual(candidate["snapshotSha256"],
                         self.cleanup["snapshot_sha256"](self.state))
        SUT["approve"](self.store, SHA, "8", candidate["snapshotSha256"], self.config)
        receipt = self.store.records[
            f"{SUT['PREFIX']}/receipts/{SHA}/firewall-ownership/8.json"]
        self.assertTrue(receipt["verified"])
        self.assertEqual(receipt["nodeUid"], "node-uid")
        self.assertEqual(receipt["bootID"], "boot-id")
        self.assertEqual(receipt["evidenceSourceSha"], EVIDENCE_SHA)
        self.assertEqual(receipt["snapshotSha256"], candidate["snapshotSha256"])

    def test_capture_refuses_missing_baseline_or_failed_probe(self):
        placement_key = f"{SUT['PREFIX']}/receipts/{EVIDENCE_SHA}/placement.json"
        probe_key = f"{SUT['PREFIX']}/{EVIDENCE_SHA}/7/qualification.json"
        self.store.records[placement_key]["firewallBaselineEmpty"] = False
        with self.assertRaisesRegex(ValueError, "pre-enable placement"):
            SUT["capture"](self.store, SHA, EVIDENCE_SHA, "8", "7", self.config)
        self.store.records[placement_key]["firewallBaselineEmpty"] = True
        for field, value in (("result", "traffic-probe-failed"),
                             ("nodeUid", "other"), ("cases", []),
                             ("unverifiedLifecycleScenarios", [])):
            with self.subTest(field=field):
                old = self.store.records[probe_key][field]
                self.store.records[probe_key][field] = value
                with self.assertRaisesRegex(ValueError, "canary traffic probe"):
                    SUT["capture"](self.store, SHA, EVIDENCE_SHA, "8", "7", self.config)
                self.store.records[probe_key][field] = old

    def test_approval_refuses_unreviewed_hash_and_live_drift(self):
        SUT["capture"](self.store, SHA, EVIDENCE_SHA, "8", "7", self.config)
        candidate = self.store.records[f"{SUT['PREFIX']}/{SHA}/8/firewall-capture.json"]
        expected = candidate["snapshotSha256"]
        with self.assertRaisesRegex(ValueError, "capture is missing or differs"):
            SUT["approve"](self.store, SHA, "8", "b" * 64, self.config)
        self.state = {**self.state, "ipset": self.state["ipset"] + "add KUBE-SRC-CCCCCCCCCCCCCCCC 10.0.0.2\n"}
        with self.assertRaisesRegex(ValueError, "live firewall"):
            SUT["approve"](self.store, SHA, "8", expected, self.config)
        self.assertNotIn(f"{SUT['PREFIX']}/receipts/{SHA}/firewall-ownership/8.json",
                         self.store.records)

    def test_interrupted_cleanup_can_review_new_partial_snapshot(self):
        SUT["capture"](self.store, SHA, EVIDENCE_SHA, "8", "7", self.config)
        first = self.store.records[f"{SUT['PREFIX']}/{SHA}/8/firewall-capture.json"]
        SUT["approve"](self.store, SHA, "8", first["snapshotSha256"], self.config)
        first_receipt = self.store.records[
            f"{SUT['PREFIX']}/receipts/{SHA}/firewall-ownership/8.json"]
        jump = self.cleanup["top_jump_comment"]("INPUT", "KUBE-ROUTER-INPUT")
        self.state = {**self.state, "nft": self.state["nft"].replace(
            f'-A INPUT -m comment --comment "{jump}" -j KUBE-ROUTER-INPUT\n', "")}
        with self.assertRaisesRegex(ValueError, "ownership snapshot"):
            self.cleanup["require_ownership"](first_receipt,
                {"nodeUid": "node-uid", "bootID": "boot-id"}, self.state, SHA, NODE)
        SUT["capture"](self.store, SHA, EVIDENCE_SHA, "9", "7", self.config)
        second = self.store.records[f"{SUT['PREFIX']}/{SHA}/9/firewall-capture.json"]
        SUT["approve"](self.store, SHA, "9", second["snapshotSha256"], self.config)
        second_receipt = self.store.records[
            f"{SUT['PREFIX']}/receipts/{SHA}/firewall-ownership/9.json"]
        self.cleanup["require_ownership"](second_receipt,
            {"nodeUid": "node-uid", "bootID": "boot-id"}, self.state, SHA, NODE)
        self.assertNotEqual(first_receipt["snapshotSha256"], second_receipt["snapshotSha256"])

    def test_all_objects_removed_can_be_reviewed_as_noop(self):
        empty = self.state["legacy"]
        self.state = {"backend": "nft", "nft": empty, "legacy": empty,
                      "ip6nft": empty, "ip6legacy": empty, "ipset": "\n"}
        SUT["capture"](self.store, SHA, EVIDENCE_SHA, "9", "7", self.config)
        candidate = self.store.records[f"{SUT['PREFIX']}/{SHA}/9/firewall-capture.json"]
        self.assertEqual((candidate["ownedChains"], candidate["ownedSets"]), (0, 0))
        SUT["approve"](self.store, SHA, "9", candidate["snapshotSha256"], self.config)
        receipt = self.store.records[
            f"{SUT['PREFIX']}/receipts/{SHA}/firewall-ownership/9.json"]
        self.assertEqual(receipt["snapshotSha256"], candidate["snapshotSha256"])

    def test_approval_refuses_changed_capture_or_probe(self):
        SUT["capture"](self.store, SHA, EVIDENCE_SHA, "8", "7", self.config)
        key = f"{SUT['PREFIX']}/{SHA}/8/firewall-capture.json"
        expected = self.store.records[key]["snapshotSha256"]
        self.store.records[key]["snapshot"]["ipset"] += "add KUBE-SRC-CCCCCCCCCCCCCCCC 10.0.0.2\n"
        with self.assertRaisesRegex(ValueError, "capture is missing or differs"):
            SUT["approve"](self.store, SHA, "8", expected, self.config)
        self.store.records[key]["snapshot"] = FIXTURE["state"]()
        self.store.records[f"{SUT['PREFIX']}/{EVIDENCE_SHA}/7/qualification.json"]["nodeUid"] = "other"
        with self.assertRaisesRegex(ValueError, "canary traffic probe"):
            SUT["approve"](self.store, SHA, "8", expected, self.config)

    def test_version_history_and_checksums_fail_closed(self):
        store = SUT["PrivateStore"]("homelab-application-backups-716182248480-us-east-1")
        key = "private/key.json"
        version = {"Key": key, "IsLatest": True, "VersionId": "v1"}
        with patch.object(store, "call", return_value={"IsTruncated": False,
                                                       "Versions": [version]}) as call:
            self.assertEqual(store.version(key, True), "v1")
            self.assertIn("--no-paginate", call.call_args.args[1])
        for listing in ({"IsTruncated": True, "Versions": [version]},
                        {"IsTruncated": False, "Versions": [version, version]},
                        {"IsTruncated": False, "Versions": [version],
                         "DeleteMarkers": [{"Key": key}]},
                        {"Versions": [version]}):
            with (self.subTest(listing=listing), patch.object(store, "call", return_value=listing)):
                with self.assertRaisesRegex(ValueError, "history"):
                    store.version(key, True)
        content = b'{"ok":true}\n'
        def corrupt_read(operation, arguments):
            if operation == "list-object-versions":
                return {"IsTruncated": False, "Versions": [version]}
            Path(arguments[-1]).write_bytes(content)
            Path(arguments[-1]).chmod(0o600)
            return {"VersionId": "v1", "ContentLength": len(content),
                    "ChecksumSHA256": "wrong", "ServerSideEncryption": "aws:kms"}
        with patch.object(store, "call", side_effect=corrupt_read):
            with self.assertRaisesRegex(ValueError, "checksum"):
                store.read(key, 1048576)

    def test_write_once_checks_immutable_private_readback(self):
        store = SUT["PrivateStore"]("homelab-application-backups-716182248480-us-east-1")
        key = "private/key.json"
        content = None
        checksum = None
        operations = []
        def s3(operation, arguments):
            nonlocal content, checksum
            operations.append(operation)
            if operation == "list-object-versions":
                versions = [] if content is None else [
                    {"Key": key, "IsLatest": True, "VersionId": "v1"}]
                return {"IsTruncated": False, "Versions": versions}
            if operation == "put-object":
                self.assertIn("--if-none-match", arguments)
                self.assertIn("--server-side-encryption", arguments)
                path = Path(arguments[arguments.index("--body") + 1])
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                content = path.read_bytes()
                checksum = base64.b64encode(hashlib.sha256(content).digest()).decode()
                return {"VersionId": "v1", "ChecksumSHA256": checksum}
            Path(arguments[-1]).write_bytes(content)
            Path(arguments[-1]).chmod(0o600)
            return {"VersionId": "v1", "ContentLength": len(content),
                    "ChecksumSHA256": checksum, "ServerSideEncryption": "aws:kms"}
        with patch.object(store, "call", side_effect=s3):
            store.write_once(key, {"approved": True}, 1048576)
            self.assertEqual(operations,
                             ["list-object-versions", "put-object",
                              "list-object-versions", "list-object-versions", "get-object"])
            with self.assertRaisesRegex(ValueError, "history"):
                store.write_once(key, {"approved": False}, 1048576)

    def test_only_fresh_owner_dispatch_can_attest(self):
        for actor, attempt in ((None, "1"), ("123", "1"),
                               (SUT["OWNER_ACTOR_ID"], None),
                               (SUT["OWNER_ACTOR_ID"], "2")):
            with (self.subTest(actor=actor, attempt=attempt),
                  patch.dict("os.environ", {"GITHUB_ACTOR_ID": actor or "",
                                           "GITHUB_RUN_ATTEMPT": attempt or ""})):
                with self.assertRaisesRegex(ValueError, "fresh owner dispatch"):
                    SUT["require_owner_attestation"]()
        with patch.dict("os.environ", {"GITHUB_ACTOR_ID": SUT["OWNER_ACTOR_ID"],
                                       "GITHUB_RUN_ATTEMPT": "1"}):
            SUT["require_owner_attestation"]()

    def test_unowned_approval_stops_before_config_or_private_access(self):
        args = ["network-policy-ownership.py", "approve", "--expected-sha", SHA,
                "--bucket", "homelab-application-backups-716182248480-us-east-1",
                "--capture-run-id", "8", "--reviewed-snapshot-sha256", "b" * 64]
        def external_access(*_):
            raise AssertionError("approval reached private access")
        with (patch.object(sys, "argv", args),
              patch.dict("os.environ", {"GITHUB_ACTOR_ID": "123",
                                        "GITHUB_RUN_ATTEMPT": "1"}),
              patch.dict(SUT["PLATFORM"], {"validate_config": external_access}),
              patch.dict(SUT["main"].__globals__, {"PrivateStore": external_access})):
            self.assertEqual(SUT["main"](), 1)


if __name__ == "__main__":
    unittest.main()
