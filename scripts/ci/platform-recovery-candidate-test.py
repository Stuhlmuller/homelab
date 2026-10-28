#!/usr/bin/env python3
"""Offline fixtures for the operator-LAN recovery candidate producer."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "platform-recovery-candidate.py"
spec = importlib.util.spec_from_file_location("platform_recovery_candidate", SCRIPT)
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)
SHA = "a" * 40
SNAPSHOT_SHA = "b" * 64
MANIFEST_SHA = "c" * 64


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.paths = {}
        for name in ("publication", "retrieval", "restore", "receipts"):
            path = self.root / name
            path.mkdir(mode=0o700)
            self.paths[name] = path
        self.config = self.root / "talosconfig"
        self.config.write_text("private fixture only")
        self.config.chmod(0o600)
        self.talosctl = self.root / "talosctl"
        self.talosctl.write_text("#!/bin/sh\nexit 0\n")
        self.talosctl.chmod(0o700)
        self.args = SimpleNamespace(
            expected_sha=SHA, talosconfig=self.config, talosctl=self.talosctl,
            aws_cli=Path("/usr/bin/true"), profile="default",
            publication_directory=self.paths["publication"],
            retrieval_directory=self.paths["retrieval"],
            restore_directory=self.paths["restore"],
            receipt_directory=self.paths["receipts"],
            etcd_archive=self.root / "etcd.zip")
        self.retrieved = self.paths["retrieval"] / "retrieval-fixture"
        self.retrieved.mkdir(mode=0o700)
        self.restored = self.paths["restore"] / "restore-fixture"
        self.restored.mkdir(mode=0o700)
        self.snapshot = {
            "format": 1, "snapshot": "etcd.snapshot",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_node": "10.1.0.199",
            "integrity": {"bytes": 1024, "sha256": SNAPSHOT_SHA,
                          "embedded_sha256": "d" * 64},
        }
        self.restore_record = {"format": 1, "validation": "offline-database-restore",
                               "source_integrity": self.snapshot["integrity"],
                               "restore_checksum_enabled": True,
                               "source_unchanged": True, "server_started": False,
                               "control_plane_recovery_tested": False,
                               "tool": {"version": candidate.RESTORE.VERSION}}
        (self.restored / "receipt.json").write_text(json.dumps(self.restore_record) + "\n")
        (self.restored / "receipt.json").chmod(0o600)
        self.publication = {
            "format": 1, "status": "verified",
            "prefix": f"etcd/{SNAPSHOT_SHA}/{'e' * 32}",
            "objects": {
                "etcd.snapshot": {"version_id": "snapshot-version",
                                  "digest": {"sha256": SNAPSHOT_SHA, "bytes": 1024}},
                "manifest.json": {"version_id": "manifest-version",
                                  "digest": {"sha256": MANIFEST_SHA, "bytes": 256}},
            },
        }
        self.direct = {"interface": "en0", "sourceAddress": "10.1.0.55",
                       "nodeAddresses": {"acer": "10.1.0.199",
                                         "zimaboard-0": "10.1.0.200",
                                         "zimaboard-1": "10.1.0.201",
                                         "zimaboard-2": "10.1.0.202"},
                       "nodeEndpoints": {"acer": "10.1.0.199:50000",
                                         "zimaboard-0": "10.1.0.200:50000",
                                         "zimaboard-1": "10.1.0.201:50000",
                                         "zimaboard-2": "10.1.0.202:50000"},
                       "controlPlaneEndpoint": "10.1.0.199:50000",
                       "etcdStatusRead": True, "directClusterHealth": True}

    def captured(self):
        aws = SimpleNamespace(target=candidate.OFFSITE.destination())
        with patch.object(candidate, "require_main") as main, \
             patch.object(candidate, "direct_talos", return_value=self.direct) as talos, \
             patch.object(candidate, "ReadOnlyAWS", return_value=aws), \
             patch.object(candidate.OFFSITE, "load", return_value=(
                 self.paths["publication"], self.publication)) as load, \
             patch.object(candidate.OFFSITE, "retrieve", return_value=self.retrieved) as retrieve, \
             patch.object(candidate.OFFSITE.backup, "verify", return_value=self.snapshot), \
             patch.object(candidate.RESTORE, "restore_check", return_value=(
                 self.restored, self.restore_record)) as restore:
            directory = candidate.capture(self.args)
        self.assertEqual(main.call_count, 2)
        self.assertEqual(talos.call_count, 2)
        self.assertEqual(load.call_count, 2)
        self.assertEqual(retrieve.call_count, 1)
        self.assertEqual(restore.call_count, 1)
        return directory

    def test_candidates_bind_versions_and_remain_non_authoritative(self):
        directory = self.captured()
        direct = json.loads((directory / "direct-recovery.candidate.json").read_text())
        backup = json.loads((directory / "off-node-etcd-backup.candidate.json").read_text())
        self.assertEqual(direct["scope"], candidate.SCOPE)
        self.assertIs(direct["verified"], False)
        self.assertIs(backup["verified"], False)
        self.assertEqual(direct["sourceSha"], SHA)
        self.assertEqual(direct["nodes"], ["zimaboard-0", "zimaboard-1", "zimaboard-2", "acer"])
        self.assertEqual(direct["interface"], "en0")
        self.assertEqual(backup["snapshotSha256"], SNAPSHOT_SHA)
        self.assertEqual(backup["objectVersionId"], "snapshot-version")
        self.assertEqual(backup["manifestVersionId"], "manifest-version")
        self.assertEqual(backup["manifestSha256"], MANIFEST_SHA)
        self.assertEqual(backup["snapshotKey"], self.publication["prefix"] + "/etcd.snapshot")
        self.assertEqual(backup["manifestKey"], self.publication["prefix"] + "/manifest.json")
        self.assertEqual(backup["targetKey"],
                         f"openclaw-enterprise/platform/receipts/{SHA}/off-node-etcd-backup.json")
        self.assertEqual(backup["offsiteBucket"], candidate.OFFSITE.destination()["bucket"])
        self.assertEqual(backup["restoreReceiptSha256"],
                         candidate.OFFSITE.digest(directory / "offline-restore.receipt.json")["sha256"])
        for path in directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_stale_snapshot_stops_before_candidate(self):
        self.snapshot["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        with self.assertRaises(ValueError):
            self.captured()
        self.assertEqual(list(self.paths["receipts"].iterdir()), [])

    def test_candidates_cannot_authorize_upgrade(self):
        directory = self.captured()
        direct = json.loads((directory / "direct-recovery.candidate.json").read_text())
        backup = json.loads((directory / "off-node-etcd-backup.candidate.json").read_text())
        config = json.loads((candidate.ROOT / "scripts/config/platform-maintenance.json").read_text())
        with self.assertRaises(ValueError):
            candidate.PLATFORM.verify_prerequisites(config, SHA, {
                "direct-recovery": direct, "off-node-etcd-backup": backup})

    def test_direct_route_rejects_overlay_and_off_subnet_source(self):
        with patch.object(candidate.sys, "platform", "darwin"):
            self.assertEqual(candidate.direct_route("10.1.0.199",
                run=lambda *a, **k: "interface: en0\n", connect=lambda: "10.1.0.55"),
                ("en0", "10.1.0.55"))
            for interface, source in (("utun4", "10.1.0.55"),
                                      ("en0", "100.64.0.2")):
                with self.assertRaises(ValueError):
                    candidate.direct_route("10.1.0.199",
                        run=lambda *a, **k: f"interface: {interface}\n",
                        connect=lambda: source)

    def test_each_node_uses_direct_endpoint_and_reads_etcd_status(self):
        config = json.loads((candidate.ROOT / "scripts/config/platform-maintenance.json").read_text())
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            self.assertNotIn("HTTP_PROXY", kwargs.get("env", {}))
            if "--client" in command:
                return "Client:\nTalos v1.11.3\n"
            if command[-2:] == ["etcd", "status"]:
                return "NODE 10.1.0.199 member healthy\n"
            return "Client:\nTalos v1.11.3\nServer:\nTalos v1.11.3\n"
        routes = []
        def route(address):
            routes.append(address)
            return "en0", "10.1.0.55"
        with patch.dict(os.environ, {"HTTP_PROXY": "http://fixture.invalid"}):
            result = candidate.direct_talos(config, self.config, self.talosctl,
                                            run=run, route=route)
        self.assertTrue(result["etcdStatusRead"])
        self.assertTrue(result["directClusterHealth"])
        self.assertEqual(len([call for call in calls if "--nodes" in call]), 5)
        self.assertEqual(len(routes), 12)
        for name in ("zimaboard-0", "zimaboard-1", "zimaboard-2", "acer"):
            address = config["expectedStart"]["nodes"][name]["address"]
            self.assertIn([str(self.talosctl), "--talosconfig", str(self.config),
                           "--endpoints", address, "--nodes", address,
                           "version", "--short"], calls)

    def test_read_only_aws_blocks_broad_profile_writes(self):
        aws = candidate.ReadOnlyAWS(Path("/usr/bin/true"), "default",
                                    candidate.OFFSITE.destination())
        with self.assertRaises(ValueError):
            aws.call("s3api", "put-object", ["--key", "anything"])

    def test_exact_main_rejects_ambient_selectors_and_pins_github(self):
        with patch.dict(os.environ, {"GH_HOST": "attacker.invalid"}):
            with self.assertRaises(ValueError):
                candidate.require_main(SHA)
        with patch.dict(os.environ, {"GIT_DIR": "/tmp/other"}):
            with self.assertRaises(ValueError):
                candidate.require_main(SHA)
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if command[-2:] == ["rev-parse", "--show-toplevel"]:
                return str(candidate.ROOT) + "\n"
            if command[-3:] == ["remote", "get-url", "origin"]:
                return "https://github.com/Stuhlmuller/homelab.git\n"
            if command[-2:] == ["rev-parse", "HEAD"]:
                return SHA + "\n"
            if command[-2:] == ["status", "--porcelain"]:
                return ""
            return SHA + "\n"
        with patch.object(candidate, "quiet", side_effect=run):
            candidate.require_main(SHA)
        self.assertIn(["gh", "api", "--hostname", "github.com",
                       "repos/Stuhlmuller/homelab/git/ref/heads/main",
                       "--jq", ".object.sha"], calls)

    def test_backup_timestamp_normalizes_to_gate_utc_seconds(self):
        result = candidate.captured_utc_seconds(datetime.now(timezone.utc).isoformat())
        self.assertRegex(result, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        with self.assertRaises(ValueError):
            candidate.captured_utc_seconds("2026-10-20T00:00:00-07:00")

    def test_quiet_cli_failure_hides_diagnostics(self):
        result = subprocess.CompletedProcess([], 1, stdout=b"private-key", stderr=b"secret")
        with patch.object(candidate.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ValueError, "required local verification failed") as error:
                candidate.quiet(["fake"])
        self.assertNotIn("private-key", str(error.exception))
        self.assertNotIn("secret", str(error.exception))

    def test_stage_uploads_only_non_authoritative_exact_versions(self):
        directory = self.captured()
        staged_bytes = {}
        operations = []
        bucket = candidate.OFFSITE.destination()

        class FakeAWS:
            target = bucket

            def check(self):
                operations.append("check")

            def call(self, service, operation, arguments=()):
                operations.append(operation)
                if operation == "get-bucket-encryption":
                    return {"ServerSideEncryptionConfiguration": {"Rules": [{
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "aws:kms",
                            "KMSMasterKeyID":
                                f"arn:aws:kms:us-east-1:{bucket['account_id']}:alias/aws/s3"},
                        "BucketKeyEnabled": True}]}}
                key = arguments[arguments.index(
                    "--prefix" if operation == "list-object-versions" else "--key") + 1]
                if operation == "put-object":
                    staged_bytes[key] = Path(arguments[arguments.index("--body") + 1]).read_bytes()
                    return {"VersionId": "version-1", "ChecksumSHA256":
                            arguments[arguments.index("--checksum-sha256") + 1]}
                import base64, hashlib
                payload = staged_bytes[key]
                checksum = base64.b64encode(hashlib.sha256(payload).digest()).decode()
                if operation == "list-object-versions":
                    return {"IsTruncated": False, "Versions": [
                        {"Key": key, "VersionId": "version-1", "IsLatest": True}]}
                if operation == "get-object":
                    Path(arguments[-1]).write_bytes(payload)
                return {"VersionId": "version-1", "ChecksumSHA256": checksum,
                        "ContentLength": len(payload), "ServerSideEncryption": "aws:kms",
                        "BucketKeyEnabled": True,
                        "SSEKMSKeyId":
                            f"arn:aws:kms:us-east-1:{bucket['account_id']}:key/fixture-key"}

        args = SimpleNamespace(expected_sha=SHA, candidate_directory=directory,
                               aws_cli=Path("/usr/bin/true"), profile="default")
        with patch.object(candidate, "require_main") as main, \
             patch.object(candidate, "StagingAWS", return_value=FakeAWS()):
            receipt = candidate.stage(args)
        self.assertEqual(main.call_count, 5)
        self.assertIs(receipt["verified"], False)
        self.assertEqual(receipt["bucket"], bucket["bucket"])
        self.assertEqual(set(receipt["objects"]),
                         {"direct-recovery", "off-node-etcd-backup", "offline-restore"})
        self.assertEqual(len(staged_bytes), 3)
        for name, record in receipt["objects"].items():
            self.assertEqual(record["versionId"], "version-1")
            filename = ("offline-restore.receipt.json" if name == "offline-restore"
                        else f"{name}.candidate.json")
            self.assertEqual(record["key"], f"{receipt['prefix']}/{filename}")
            self.assertEqual(record["bytes"], len(staged_bytes[record["key"]]))
        self.assertTrue(all(key.startswith(f"platform-candidates/{SHA}/")
                            for key in staged_bytes))
        self.assertNotIn("delete-object", operations)
        self.assertEqual((directory / "staging.json").stat().st_mode & 0o777, 0o600)

    def test_stage_rejects_modified_candidate_before_aws(self):
        directory = self.captured()
        path = directory / "off-node-etcd-backup.candidate.json"
        value = json.loads(path.read_text())
        value["snapshotKey"] = value["snapshotKey"].replace(
            "/etcd.snapshot", "/extra/etcd.snapshot")
        path.write_bytes(candidate.canonical(value))
        with patch.object(candidate, "require_main"), \
             patch.object(candidate, "StagingAWS") as aws:
            with self.assertRaises(ValueError):
                candidate.stage(SimpleNamespace(expected_sha=SHA,
                    candidate_directory=directory, aws_cli=Path("/usr/bin/true"),
                    profile="default"))
        aws.assert_not_called()

    def test_stage_rejects_malformed_restore_receipt_without_traceback(self):
        directory = self.captured()
        (directory / "offline-restore.receipt.json").write_text("[]\n")
        with self.assertRaises(ValueError):
            candidate.candidate_files(directory, SHA)

    def test_server_prerelease_is_not_reviewed_baseline(self):
        config = json.loads((candidate.ROOT / "scripts/config/platform-maintenance.json").read_text())
        def run(command, **kwargs):
            if "--client" in command:
                return "Client:\nTalos v1.11.3\n"
            return "Server:\nTalos v1.11.3-rc1\n"
        with self.assertRaises(ValueError):
            candidate.direct_talos(config, self.config, self.talosctl,
                run=run, route=lambda address: ("en0", "10.1.0.55"))


if __name__ == "__main__":
    unittest.main()
