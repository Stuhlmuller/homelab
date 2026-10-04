#!/usr/bin/env python3
"""Offline failure/integrity checks for Wazuh API initialization and backup."""
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "clusters/homelab/apps/wazuh"


def load(name):
    spec = importlib.util.spec_from_file_location("wazuh_" + name, CORE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    with patch.object(ssl, "create_default_context", return_value=Mock()):
        spec.loader.exec_module(module)
    return module


BOOTSTRAP = load("bootstrap")
BACKUP = load("backup")


def response(value):
    return io.BytesIO(json.dumps(value).encode())


class BootstrapTests(unittest.TestCase):
    def test_dashboard_uses_only_mounted_password_and_indexer_uses_client_certificate(self):
        password = "test"
        with patch.object(BOOTSTRAP.Path, "read_text", return_value=password) as read_password, \
                patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=[response({}), response({})]) as http:
            BOOTSTRAP.request("GET", "/_cluster/health")
            read_password.assert_not_called()
            indexer_request = http.call_args.args[0]
            self.assertIsNone(indexer_request.get_header("Authorization"))
            self.assertIs(http.call_args.kwargs["context"], BOOTSTRAP.TLS)
            BOOTSTRAP.request("POST", "/api/saved_objects/index-pattern/wazuh-archives", {}, dashboard=True)
            dashboard_request = http.call_args.args[0]
            self.assertEqual(dashboard_request.get_header("Authorization"),
                             "Basic " + base64.b64encode(("admin:" + password).encode()).decode())
            self.assertEqual(dashboard_request.get_header("Osd-xsrf"), "wazuh-bootstrap")
        with patch.object(BOOTSTRAP.Path, "read_text", side_effect=FileNotFoundError), \
                patch.object(BOOTSTRAP.urllib.request, "urlopen") as http:
            with self.assertRaises(FileNotFoundError):
                BOOTSTRAP.request("POST", "/api/saved_objects/index-pattern/wazuh-archives", {}, dashboard=True)
            http.assert_not_called()

    def test_only_explicit_missing_responses_are_tolerated(self):
        for status, missing, accepted in ((404, True, True), (404, False, False), (403, True, False)):
            failure = urllib.error.HTTPError("https://fixture.invalid", status, "private-response", {}, None)
            with self.subTest(status=status, missing=missing), \
                    patch.object(BOOTSTRAP.urllib.request, "urlopen", side_effect=failure):
                if accepted:
                    self.assertIsNone(BOOTSTRAP.request("GET", "/policy", missing=missing))
                else:
                    with self.assertRaisesRegex(RuntimeError, f"HTTP {status}") as error:
                        BOOTSTRAP.request("GET", "/policy", missing=missing)
                    self.assertNotIn("private-response", str(error.exception))
            failure.close()

    def test_retention_updates_use_concurrency_control_and_failure_stops_bootstrap(self):
        calls = []

        def request(method, path, value=None, **kwargs):
            calls.append((method, path, value))
            if path.startswith("/_cluster/health"):
                return {"status": "yellow"}
            if method == "GET" and "/policies/" in path:
                return {"_seq_no": 7, "_primary_term": 3}
            if "/_ism/add/" in path:
                return {"updated_indices": 0, "failures": False, "failed_indices": []}
            if "/_ism/explain/" in path:
                return {"total_managed_indices": 0}
            if path == "/_snapshot/homelab/_verify":
                raise RuntimeError("snapshot verification rejected")
            return {}

        with patch.object(BOOTSTRAP, "request", side_effect=request):
            with self.assertRaisesRegex(RuntimeError, "snapshot verification rejected"):
                BOOTSTRAP.main()
        for category, days in (("archives", 30), ("alerts", 90)):
            policy = next(value for method, path, value in calls
                          if method == "PUT" and path.startswith(f"/_plugins/_ism/policies/homelab-{category}"))
            self.assertEqual(policy["policy"]["states"][0]["transitions"][0]["conditions"],
                             {"min_index_age": f"{days}d"})
        self.assertTrue(all("if_seq_no=7&if_primary_term=3" in path
                            for method, path, _ in calls if method == "PUT" and "/policies/" in path))
        self.assertFalse(any(path.startswith("/api/") for _, path, _ in calls))

    def test_http_200_existing_policy_failure_requires_matching_enabled_readback(self):
        index = "wazuh-archives-4.x-2026.10.03"
        policy = "homelab-archives-30d"
        added = {"updated_indices": 0, "failures": True, "failed_indices": [
            {"index_name": index, "reason": "This index already has a policy"}
        ]}
        for assigned, succeeds in (("other-retention", False), (policy, True)):
            def api(method, path, value=None, **kwargs):
                if path.startswith("/_cluster/health"):
                    return {"status": "yellow"}
                if method == "GET" and "/policies/" in path:
                    return None
                if path == "/_plugins/_ism/add/wazuh-archives-*":
                    self.assertFalse(kwargs.get("missing", False))
                    return added
                if "/_ism/add/" in path:
                    return {"updated_indices": 0, "failures": False, "failed_indices": []}
                if path == "/_plugins/_ism/explain/wazuh-archives-*":
                    return {index: {"policy_id": assigned, "enabled": True}, "total_managed_indices": 1}
                if "/_ism/explain/" in path:
                    return {"total_managed_indices": 0}
                return {}

            with self.subTest(assigned=assigned), \
                    patch.object(BOOTSTRAP, "request", side_effect=api) as request, \
                    patch.object(BOOTSTRAP.time, "sleep") as sleep, \
                    contextlib.redirect_stdout(io.StringIO()):
                if succeeds:
                    BOOTSTRAP.main()
                else:
                    with self.assertRaisesRegex(RuntimeError, "Conflicting ISM policy"):
                        BOOTSTRAP.main()
                paths = [call.args[1] for call in request.call_args_list]
                self.assertEqual("/_snapshot/homelab/_verify" in paths, succeeds)
                self.assertFalse(any("/change_policy/" in path or "/remove/" in path for path in paths))
                sleep.assert_not_called()

    def test_retention_waits_for_all_indices_and_rejects_unconfirmed_assignments(self):
        policy = "homelab-archives-30d"
        first, second = "wazuh-archives-first", "wazuh-archives-second"
        added = {"updated_indices": 2, "failures": False, "failed_indices": []}
        matching = {"policy_id": policy, "enabled": True}
        pending = {first: matching, second: {"policy_id": None}, "total_managed_indices": 1}
        complete = {first: matching, second: matching, "total_managed_indices": 2}
        with patch.object(BOOTSTRAP, "request", side_effect=[pending, complete]), \
                patch.object(BOOTSTRAP.time, "sleep") as sleep:
            BOOTSTRAP.verify_retention([("wazuh-archives-*", policy, added)])
            sleep.assert_called_once_with(10)
        for incomplete in (pending, {"total_managed_indices": 0},
                           {first: matching, second: {"policy_id": policy, "enabled": False}}):
            with self.subTest(incomplete=incomplete), \
                    patch.object(BOOTSTRAP, "request", return_value=incomplete), \
                    patch.object(BOOTSTRAP.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "retention assignments not confirmed"):
                    BOOTSTRAP.verify_retention([("wazuh-archives-*", policy, added)])

    def test_retention_never_ignores_failed_indices_absent_from_readback(self):
        added = {"updated_indices": 0, "failures": True, "failed_indices": [
            {"index_name": "wazuh-archives-closed", "reason": "This index is closed"}
        ]}
        with patch.object(BOOTSTRAP, "request", return_value={"total_managed_indices": 0}):
            with self.assertRaisesRegex(RuntimeError, "failures missing from readback"):
                BOOTSTRAP.verify_retention([("wazuh-archives-*", "homelab-archives-30d", added)])


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="wazuh-backup-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "manager/logs/archives/2026/Oct/ossec-01.json.gz"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"closed-archive-fixture")
        closed_time = time.time() - 172800
        os.utime(self.source, (closed_time, closed_time))
        self.target = self.root / "backups/raw/archives/2026/Oct/ossec-01.json.gz"
        self.path_patch = patch.object(BACKUP, "Path", side_effect=lambda path: self.root / str(path).lstrip("/"))
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_closed_archive_copy_is_verified_idempotent_and_keeps_sources(self):
        fresh = self.source.with_name("ossec-02.json.gz")
        fresh.write_bytes(b"still-rolling")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            BACKUP.mirror_archives()
            original_mtime = self.target.stat().st_mtime_ns
            BACKUP.mirror_archives()
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.target.stat().st_mtime_ns, original_mtime)
        self.assertEqual(self.target.with_suffix(".gz.sha256").read_text().strip(), BACKUP.digest(self.source))
        self.assertFalse(self.target.with_name(fresh.name).exists())
        self.assertTrue(self.source.exists())
        self.assertTrue(fresh.exists())
        self.assertIn("copied 1 closed files", output.getvalue())
        self.assertIn("copied 0 closed files", output.getvalue())

    def test_concurrent_source_change_never_publishes_a_partial_copy(self):
        copy = shutil.copyfileobj

        def mutate_after_copy(incoming, outgoing):
            copy(incoming, outgoing)
            self.source.write_bytes(b"changed-after-copy")

        with patch.object(BACKUP.shutil, "copyfileobj", side_effect=mutate_after_copy):
            with self.assertRaisesRegex(RuntimeError, "changed during backup"):
                BACKUP.mirror_archives()
        self.assertTrue(self.source.exists())
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.with_suffix(".gz.partial").exists())

    def test_checksum_mismatch_never_publishes_a_partial_copy(self):
        digest = BACKUP.digest
        with patch.object(BACKUP, "digest", side_effect=lambda path: "corrupt" if path.suffix == ".partial" else digest(path)):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                BACKUP.mirror_archives()
        self.assertTrue(self.source.exists())
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.with_suffix(".gz.partial").exists())

    def test_snapshot_requires_acceptance_and_full_success_without_deleting_data(self):
        cases = [
            ([{"accepted": False}], False),
            ([{"accepted": True}, {"snapshots": [{"state": "PARTIAL"}]}], False),
            ([{"accepted": True}, {"snapshots": [{"state": "IN_PROGRESS"}]},
              {"snapshots": [{"state": "SUCCESS"}]}], True),
        ]
        for responses, succeeds in cases:
            with self.subTest(responses=responses), \
                    patch.object(BACKUP.ssl, "create_default_context", return_value=Mock()), \
                    patch.object(BACKUP.time, "sleep"), \
                    patch.object(BACKUP.urllib.request, "urlopen", side_effect=[response(value) for value in responses]) as http, \
                    contextlib.redirect_stdout(io.StringIO()):
                if succeeds:
                    BACKUP.snapshot()
                else:
                    with self.assertRaises(RuntimeError):
                        BACKUP.snapshot()
                first = http.call_args_list[0].args[0]
                self.assertEqual(first.method, "PUT")
                self.assertEqual(json.loads(first.data)["include_global_state"], False)
                self.assertTrue(all(isinstance(call.args[0], str) for call in http.call_args_list[1:]))
                self.assertTrue(self.source.exists())


class SnapshotRetentionTests(unittest.TestCase):
    def setUp(self):
        self.now = 1791078000
        self.current = "homelab-20261004-020000"

    def item(self, name, days, state="SUCCESS"):
        return {"snapshot": name, "state": state,
                "end_time_in_millis": (self.now - days * 86400) * 1000}

    def run_retention(self, records, *, acknowledge=True, readback=True):
        deleted = []

        def api(request, **kwargs):
            suffix = request.full_url.rsplit("/", 1)[-1]
            if request.method == "DELETE":
                self.assertRegex(suffix, r"^homelab-[0-9]{8}-[0-9]{6}$")
                deleted.append(suffix)
                return response({"acknowledged": acknowledge})
            self.assertEqual(suffix, "_all")
            return response({"snapshots": [item for item in records
                            if not readback or item["snapshot"] not in deleted]})

        with patch.object(BACKUP.time, "time", return_value=self.now), \
                patch.object(BACKUP.ssl, "create_default_context", return_value=Mock()), \
                patch.object(BACKUP.urllib.request, "urlopen", side_effect=api), \
                contextlib.redirect_stdout(io.StringIO()):
            BACKUP.prune_snapshots(self.current)
        return deleted

    def test_only_expired_successes_deleted_and_minimum_three_kept(self):
        records = [self.item(self.current, 0),
                   self.item("homelab-20261003-020000", 1),
                   self.item("homelab-20260910-020000", 24),
                   self.item("homelab-20260909-020000", 25),
                   self.item("operator-manual-backup", 100),
                   self.item("homelab-20260901-020000", 33, "PARTIAL"),
                   self.item("homelab-20260902-020000", 32, "IN_PROGRESS")]
        deleted = self.run_retention(records)
        self.assertEqual(deleted, ["homelab-20260909-020000"])
        self.assertEqual(self.run_retention([i for i in records if i["snapshot"] not in deleted]), [])

    def test_recent_snapshots_and_last_three_successes_survive(self):
        for ages in ((1, 2, 3, 4), (20, 21)):
            records = [self.item(self.current, 0)] + [
                self.item(f"homelab-202609{day:02d}-020000", age)
                for day, age in enumerate(ages, 1)]
            self.assertEqual(self.run_retention(records), [])

    def test_new_snapshot_must_be_a_verified_success_before_deletion(self):
        for records in ([], [self.item(self.current, 0, "PARTIAL")],
                        [{"snapshot": self.current, "state": "SUCCESS"}]):
            with self.subTest(records=records), self.assertRaisesRegex(RuntimeError, "missing from retention"):
                self.run_retention(records)

    def test_deletion_requires_acknowledgement_and_absent_readback(self):
        records = [self.item(self.current, 0)] + [
            self.item(f"homelab-202609{day:02d}-020000", 20 + day)
            for day in range(1, 5)]
        with self.assertRaisesRegex(RuntimeError, "not acknowledged"):
            self.run_retention(records, acknowledge=False)
        with self.assertRaisesRegex(RuntimeError, "readback failed"):
            self.run_retention(records, readback=False)


if __name__ == "__main__":
    unittest.main()
