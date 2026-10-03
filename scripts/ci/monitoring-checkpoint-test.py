#!/usr/bin/env python3
"""Synthetic cold-copy and fence failures; never opens production artifacts."""

import copy
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "checkpoint", Path(__file__).resolve().parents[1] / "monitoring-checkpoint.py"
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "wal").mkdir()
        (self.source / "wal" / "00000001").write_bytes(b"synthetic WAL fixture")
        (self.source / "silences").write_bytes(b"synthetic silence fixture")
        self.plan = {
            "workload": "prometheus",
            "migration_id": "fixture",
            "source_pvc_uid": "old",
            "target_pvc_uid": "new",
            "source_pv": "old-pv",
            "target_pv": "new-pv",
            "application_image_digest": "sha256:fixture",
            "writer_nodes": ["fixture-node"],
        }
        self.target = self.root / "checkpoint"
        self.receipt = {
            "plan_sha256": M.canonical(self.plan),
            "phase": "checkpoint",
            "observed_at": time.time(),
            "all_consumers_accounted": True,
            "controllers_zero": True,
            "writer_pods_absent": True,
            "nodes": [
                {
                    "name": "fixture-node",
                    "boot_id": "first-boot",
                    "healthy": True,
                    "writers_absent": True,
                    "writable_mounts_absent": True,
                }
            ],
        }

    def gate(self):
        M.Gate(self.plan, "checkpoint").validate(self.receipt)

    def checkpoint(self):
        return M.checkpoint(self.plan, self.source, self.target, self.gate)

    def proof(self):
        return {
            "manifest_sha256": self.checkpoint(),
            "isolated_application_restore_passed": True,
            "independent_backup_retrieved": True,
            "application_image_digest": "sha256:fixture",
        }

    def test_round_trip_and_no_start_authorization(self):
        proof = self.proof()
        restored = self.root / "prometheus-db"
        M.restore(self.plan, self.target, restored, proof, self.gate)
        self.assertEqual(
            (restored / "wal/00000001").read_bytes(),
            (self.source / "wal/00000001").read_bytes(),
        )
        self.assertFalse(
            json.loads((restored / "restore-receipt.json").read_text())[
                "startup_authorized"
            ]
        )

    def test_no_overwrite(self):
        self.checkpoint()
        before = M.digest(self.target / "manifest.json")
        with self.assertRaises(M.Refused):
            self.checkpoint()
        self.assertEqual(before, M.digest(self.target / "manifest.json"))

    def test_corrupt_checkpoint_cannot_restore(self):
        proof = self.proof()
        (self.target / "data/silences").write_bytes(b"corrupt")
        with self.assertRaises(M.Refused):
            M.restore(self.plan, self.target, self.root / "restore", proof, self.gate)

    def test_copy_failure_never_publishes(self):
        calls = 0

        def fail():
            nonlocal calls
            calls += 1
            if calls == 8:
                raise M.Refused("lost fence")

        with self.assertRaises(M.Refused):
            M.checkpoint(self.plan, self.source, self.target, fail)
        self.assertFalse(self.target.exists())
        self.assertTrue(self.source.exists())
        self.assertTrue(self.target.with_name("checkpoint.partial").exists())

    def test_source_change_never_publishes(self):
        original = M.copy_tree

        def corrupt(*args):
            original(*args)
            (self.source / "silences").write_bytes(b"concurrent writer")

        from unittest.mock import patch

        with patch.object(M, "copy_tree", corrupt), self.assertRaises(M.Refused):
            self.checkpoint()
        self.assertFalse(self.target.exists())

    def test_links_rejected(self):
        (self.source / "link").symlink_to(self.source / "silences")
        with self.assertRaises(M.Refused):
            self.checkpoint()

    def test_nested_target_rejected(self):
        with self.assertRaises(M.Refused):
            M.checkpoint(self.plan, self.source, self.source / "nested", self.gate)

    def test_same_claim_rejected(self):
        self.plan["target_pvc_uid"] = self.plan["source_pvc_uid"]
        with self.assertRaises(M.Refused):
            self.checkpoint()

    def test_no_collector_is_not_approval(self):
        with self.assertRaises(M.Refused):
            M.Gate(self.plan, "checkpoint")()

    def test_incomplete_or_stale_fence(self):
        for key, value in [
            ("all_consumers_accounted", False),
            ("controllers_zero", False),
            ("writer_pods_absent", False),
            ("nodes", []),
            ("plan_sha256", "another-plan"),
            ("phase", "restore"),
            ("observed_at", time.time() - 31),
            ("observed_at", time.time() + 10),
        ]:
            with self.subTest(key=key):
                receipt = dict(self.receipt, **{key: value})
                with self.assertRaises(M.Refused):
                    M.Gate(self.plan, "checkpoint").validate(receipt)

    def test_node_side_checks_required(self):
        for field in ["healthy", "writers_absent", "writable_mounts_absent", "boot_id"]:
            receipt = copy.deepcopy(self.receipt)
            receipt["nodes"][0][field] = False
            with self.subTest(field=field), self.assertRaises(M.Refused):
                M.Gate(self.plan, "checkpoint").validate(receipt)

    def test_node_restart_invalidates_fence(self):
        gate = M.Gate(self.plan, "checkpoint")
        gate.validate(self.receipt)
        self.receipt["nodes"][0]["boot_id"] = "second-boot"
        with self.assertRaises(M.Refused):
            gate.validate(self.receipt)

    def test_backup_and_application_proof_required(self):
        proof = self.proof()
        for key in [
            "manifest_sha256",
            "isolated_application_restore_passed",
            "independent_backup_retrieved",
            "application_image_digest",
        ]:
            bad = dict(proof, **{key: False})
            with self.subTest(key=key), self.assertRaises(M.Refused):
                M.restore(self.plan, self.target, self.root / "restore", bad, self.gate)

    def test_rollback_must_be_a_new_plan(self):
        proof = self.proof()
        new_plan = dict(self.plan, source_pvc_uid="new", target_pvc_uid="rollback")
        with self.assertRaises(M.Refused):
            M.restore(new_plan, self.target, self.root / "rollback", proof, self.gate)


if __name__ == "__main__":
    unittest.main()
