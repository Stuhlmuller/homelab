#!/usr/bin/env python3
"""Offline retry and watch-gap fixtures for the dormant backup coordinator."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "oce_backup_coordinator", ROOT / "scripts/ci/openclaw-enterprise-backup-coordinator.py")
COORDINATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COORDINATOR)
OCE = COORDINATOR.OCE
SHA = "a" * 40
BACKUP_ID = "b" * 64
OTHER_ID = "c" * 64
POD_UID = "55555555-5555-4555-8555-555555555555"
OPERATOR_UID = "44444444-4444-4444-8444-444444444444"


def listing(version, pods=()):
    return {"kind": "PodList", "metadata": {"resourceVersion": version},
            "items": list(pods)}


def event(kind, pod=None, version="12"):
    obj = copy.deepcopy(pod) if pod is not None else {"kind": "Pod", "metadata": {
        "namespace": "openclaw-agents", "name": "unrelated", "uid": POD_UID}}
    obj["metadata"]["resourceVersion"] = version
    return {"type": kind, "object": obj}


class FakeWatch:
    def __init__(self, batches):
        self.batches = list(batches)
        self.opened = None
        self.barriers = []

    def open_from(self, namespace, version):
        if namespace != "openclaw-agents":
            raise RuntimeError("unexpected namespace")
        self.opened = version

    def drain_until(self, version):
        if self.opened is None:
            raise RuntimeError("watch was not opened")
        self.barriers.append(version)
        return self.batches.pop(0)


class BackupCoordinator(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-backup-coordinator-")
        self.addCleanup(self.temp.cleanup)
        private = Path(self.temp.name).resolve() / "private"
        private.mkdir(mode=0o700)
        self.config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.config["privateJournal"]["mountPath"] = str(private / "journal.json")
        self.state = {"installationId": "ins_one", "namespaceId": "ns_one",
                      "agentId": "agt_one", "configurationId": "cfg_one",
                      "configurationGeneration": 2, "firstRevisionId": "rev_one",
                      "revisionId": "rev_two", "revisionIds": ["rev_one", "rev_two"],
                      "servicePrincipalId": "sp_one", "secretId": "sec_one"}
        self.save()
        self.reader = {"kind": "Pod", "metadata": {
            "name": "occ-reader-tenant-" + BACKUP_ID[:40],
            "namespace": "openclaw-agents", "uid": POD_UID,
            "resourceVersion": "11",
            "annotations": {"homelab.dev/source-sha": SHA,
                            "homelab.dev/backup-id": BACKUP_ID}}}

    def save(self):
        with OCE.ProtectedJournal(self.config["privateJournal"]["mountPath"],
                                  self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as journal:
            journal.save(self.state)

    def bind_capture(self, fence, marker=None, observations=None, transaction=None):
        if observations is None:
            observations = self.observations()
        digest = hashlib.sha256(json.dumps(
            observations, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if marker is None:
            marker = {"schemaVersion": 2, "sourceSha": SHA,
                      "observationSha256": digest,
                      "installationId": "ins_one",
                      "operatorReaderPodUid": OPERATOR_UID,
                      "tenantReaderPodUid": POD_UID,
                      "namespaceId": "ns_one", "agentId": "agt_one",
                      "revisionId": "rev_two", "writerStopped": True,
                      "continuousFenceVerified": False}
        if transaction is None:
            transaction = {"backupId": BACKUP_ID,
                           "namespaceId": "ns_one", "agentId": "agt_one",
                           "revisionId": "rev_two"}
        fence.bind_capture_reference(marker, observations, transaction)
        return digest

    @staticmethod
    def snapshot(version):
        return {"tenantPods": listing(version), "claims": {}, "volumes": {},
                "systemSecrets": {}, "tenantSecrets": {}, "agent": {},
                "deployment": {}, "runtime": {}, "journalSha256": "e" * 64}

    def observations(self):
        return {"schemaVersion": 1, "sourceSha": SHA,
                "identity": {"installationId": "ins_one", "namespaceId": "ns_one",
                             "agentId": "agt_one", "revisionId": "rev_two"},
                "readers": {"operator": {"metadata": {"uid": OPERATOR_UID}},
                            "tenant": self.reader},
                "duringTenantPods": listing("12", [self.reader]),
                "before": self.snapshot("10"), "after": self.snapshot("14")}

    def test_new_id_is_explicit_and_unfinished_id_is_recovered(self):
        with self.assertRaisesRegex(COORDINATOR.Blocked, "explicit durable ID"):
            COORDINATOR.select_backup_id(self.config)
        self.assertEqual(COORDINATOR.select_backup_id(self.config, BACKUP_ID), BACKUP_ID)
        self.state["backup"] = {"id": BACKUP_ID, "phase": "stopping",
                                "sourceRevisionId": "rev_two",
                                "baselineRevisionIds": ["rev_one", "rev_two"]}
        self.save()
        self.assertEqual(COORDINATOR.select_backup_id(self.config), BACKUP_ID)
        self.assertEqual(COORDINATOR.select_backup_id(self.config, BACKUP_ID), BACKUP_ID)
        with self.assertRaisesRegex(COORDINATOR.Blocked, "differs from unfinished"):
            COORDINATOR.select_backup_id(self.config, OTHER_ID)

    def test_completed_idempotent_retry_needs_same_explicit_id(self):
        self.state["revisionId"] = "rev_three"
        self.state["revisionIds"].append("rev_three")
        self.state["backup"] = {"id": BACKUP_ID, "phase": "complete",
                                "sourceRevisionId": "rev_two",
                                "baselineRevisionIds": ["rev_one", "rev_two"],
                                "captureDigest": "d" * 64,
                                "resumedRevisionId": "rev_three"}
        self.save()
        with self.assertRaisesRegex(COORDINATOR.Blocked, "explicit durable ID"):
            COORDINATOR.select_backup_id(self.config)
        self.assertEqual(COORDINATOR.select_backup_id(self.config, BACKUP_ID), BACKUP_ID)
        self.assertEqual(COORDINATOR.select_backup_id(self.config, OTHER_ID), OTHER_ID)

    def test_watcher_requires_reader_creation_and_deletion_across_barriers(self):
        watch = FakeWatch([[], [event("ADDED", self.reader)],
                           [event("DELETED", self.reader, "14")]])
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
        fence.start(listing("10"))
        fence.bind_reader(self.reader)
        fence.checkpoint(listing("12", [self.reader]))
        digest = self.bind_capture(fence)
        receipt = fence.finish(listing("14"))
        self.assertEqual(watch.opened, "10")
        self.assertEqual(watch.barriers, ["10", "12", "14"])
        self.assertEqual(receipt, {
            "scope": "tenant-pod-watch", "publishable": False,
            "sourceSha": SHA, "backupId": BACKUP_ID,
            "tenantReaderPodUid": POD_UID,
            "observationSha256": digest,
            "startResourceVersion": "10", "endResourceVersion": "14"})
        with self.assertRaises(COORDINATOR.Blocked):
            fence.checkpoint(listing("15", [self.reader]))

    def test_same_watch_covers_post_publication_and_restore_checkpoints(self):
        watch = FakeWatch([[], [event("ADDED", self.reader)],
                           [event("DELETED", self.reader, "14")], [], []])
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
        fence.start(listing("10"))
        fence.bind_reader(self.reader)
        fence.checkpoint(listing("12", [self.reader]))
        self.bind_capture(fence)
        transfer = fence.finish(listing("14"))
        publication = fence.continuity_checkpoint("after-publication", listing("15"))
        restored = fence.continuity_checkpoint("after-independent-restore", listing("16"))
        self.assertEqual(watch.barriers, ["10", "12", "14", "15", "16"])
        self.assertFalse(transfer["publishable"] or publication["publishable"] or
                         restored["publishable"])
        self.assertEqual(restored["throughPhase"], "after-independent-restore")
        with self.assertRaisesRegex(COORDINATOR.Blocked, "phase is invalid"):
            fence.continuity_checkpoint("after-independent-restore", listing("17"))
        self.assertTrue(fence.failed)

    def test_post_transfer_foreign_event_and_skipped_phase_poison(self):
        for post_events, phase, message in (
                ([event("ADDED")], "after-publication", "writer appeared"),
                ([], "after-independent-restore", "phase is invalid")):
            with self.subTest(phase=phase, post_events=post_events):
                watch = FakeWatch([[], [event("ADDED", self.reader)],
                                   [event("DELETED", self.reader, "14")],
                                   post_events])
                fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
                fence.start(listing("10"))
                fence.bind_reader(self.reader)
                fence.checkpoint(listing("12", [self.reader]))
                self.bind_capture(fence)
                fence.finish(listing("14"))
                with self.assertRaisesRegex(COORDINATOR.Blocked, message):
                    fence.continuity_checkpoint(phase, listing("15"))
                self.assertTrue(fence.failed)

    def test_transient_foreign_pod_blocks_even_when_final_list_is_empty(self):
        foreign = {"kind": "Pod", "metadata": {"name": "writer",
                   "namespace": "openclaw-agents",
                   "uid": "77777777-7777-4777-8777-777777777777"}}
        watch = FakeWatch([[], [event("ADDED", self.reader)],
                           [event("ADDED", foreign), event("DELETED", foreign)]])
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
        fence.start(listing("10"))
        fence.bind_reader(self.reader)
        fence.checkpoint(listing("12", [self.reader]))
        self.bind_capture(fence)
        with self.assertRaisesRegex(COORDINATOR.Blocked, "writer appeared"):
            fence.finish(listing("14"))
        self.assertTrue(fence.failed)

    def test_watch_gap_or_missing_reader_event_blocks(self):
        watch = FakeWatch([[], []])
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
        fence.start(listing("10"))
        fence.bind_reader(self.reader)
        with self.assertRaisesRegex(COORDINATOR.Blocked, "missed creation"):
            fence.checkpoint(listing("12", [self.reader]))
        self.assertTrue(fence.failed)
        watch.batches.append([event("ADDED", self.reader)])
        with self.assertRaisesRegex(COORDINATOR.Blocked, "not active"):
            fence.checkpoint(listing("12", [self.reader]))
        failed_watch = FakeWatch([[]])
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, failed_watch)
        fence.start(listing("10"))
        fence.bind_reader(self.reader)
        with self.assertRaisesRegex(COORDINATOR.Blocked, "lost continuity"):
            fence.checkpoint(listing("12", [self.reader]))

    def test_wrong_reader_identity_and_initial_pod_block(self):
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, FakeWatch([[]]))
        with self.assertRaisesRegex(COORDINATOR.Blocked, "Pod list changed"):
            fence.start(listing("10", [self.reader]))
        fence.start(listing("10"))
        changed = copy.deepcopy(self.reader)
        changed["metadata"]["annotations"]["homelab.dev/backup-id"] = OTHER_ID
        with self.assertRaisesRegex(COORDINATOR.Blocked, "reader identity changed"):
            fence.bind_reader(changed)
        self.assertTrue(fence.failed)
        with self.assertRaisesRegex(COORDINATOR.Blocked, "binding is invalid"):
            fence.bind_reader(self.reader)

    def test_rejected_checkpoint_list_poisoned_before_watch_drain(self):
        watch = FakeWatch([[], [event("ADDED", self.reader)]])
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
        fence.start(listing("10"))
        fence.bind_reader(self.reader)
        with self.assertRaisesRegex(COORDINATOR.Blocked, "Pod list changed"):
            fence.checkpoint(listing("12"))
        self.assertTrue(fence.failed)
        self.assertEqual(watch.barriers, ["10"])
        with self.assertRaisesRegex(COORDINATOR.Blocked, "not active"):
            fence.checkpoint(listing("12", [self.reader]))

    def test_watch_cannot_seal_without_matching_unpublishable_capture(self):
        watch = FakeWatch([[], [event("ADDED", self.reader)],
                           [event("DELETED", self.reader, "14")]])
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
        fence.start(listing("10"))
        fence.bind_reader(self.reader)
        fence.checkpoint(listing("12", [self.reader]))
        with self.assertRaisesRegex(COORDINATOR.Blocked, "bound capture"):
            fence.finish(listing("14"))
        self.assertTrue(fence.failed)
        with self.assertRaisesRegex(COORDINATOR.Blocked, "no active capture"):
            self.bind_capture(fence)

        watch = FakeWatch([[], [event("ADDED", self.reader)],
                           [event("DELETED", self.reader, "14")]])
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
        fence.start(listing("10"))
        fence.bind_reader(self.reader)
        fence.checkpoint(listing("12", [self.reader]))
        marker = {"schemaVersion": 2, "sourceSha": SHA,
                  "observationSha256": "d" * 64,
                  "installationId": "ins_one",
                  "operatorReaderPodUid": OPERATOR_UID,
                  "tenantReaderPodUid": POD_UID,
                  "namespaceId": "ns_one", "agentId": "agt_one",
                  "revisionId": "rev_two", "writerStopped": True,
                  "continuousFenceVerified": True}
        with self.assertRaisesRegex(COORDINATOR.Blocked, "marker changed"):
            self.bind_capture(fence, marker=marker)
        self.assertTrue(fence.failed)
        with self.assertRaisesRegex(COORDINATOR.Blocked, "no active capture"):
            self.bind_capture(fence)

    def test_rejected_finish_list_cannot_be_retried(self):
        watch = FakeWatch([[], [event("ADDED", self.reader)],
                           [event("DELETED", self.reader, "14")]])
        fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
        fence.start(listing("10"))
        fence.bind_reader(self.reader)
        fence.checkpoint(listing("12", [self.reader]))
        self.bind_capture(fence)
        with self.assertRaisesRegex(COORDINATOR.Blocked, "Pod list changed"):
            fence.finish(listing("14", [self.reader]))
        self.assertTrue(fence.failed)
        self.assertEqual(watch.barriers, ["10", "12"])
        with self.assertRaisesRegex(COORDINATOR.Blocked, "no bound capture"):
            fence.finish(listing("14"))

    def test_incomplete_assembler_shape_never_yields_watch_evidence(self):
        for missing in ("schemaVersion", "installationId", "claims", "tenantSecrets"):
            with self.subTest(missing=missing):
                watch = FakeWatch([[], [event("ADDED", self.reader)]])
                fence = COORDINATOR.TenantWriterFence(SHA, BACKUP_ID, watch)
                fence.start(listing("10"))
                fence.bind_reader(self.reader)
                fence.checkpoint(listing("12", [self.reader]))
                observations = self.observations()
                if missing == "installationId":
                    observations["identity"].pop(missing)
                elif missing in ("claims", "tenantSecrets"):
                    observations["before"].pop(missing)
                else:
                    observations.pop(missing)
                with self.assertRaises(COORDINATOR.Blocked):
                    self.bind_capture(fence, observations=observations)
                self.assertTrue(fence.failed)
                with self.assertRaisesRegex(COORDINATOR.Blocked, "no active capture"):
                    self.bind_capture(fence)


if __name__ == "__main__":
    unittest.main()
