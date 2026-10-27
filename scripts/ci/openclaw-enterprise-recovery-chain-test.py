#!/usr/bin/env python3
"""Offline full-material and external-reference failure fixtures for T051."""

import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


CHAIN = module("oce_chain_test_subject",
               "scripts/ci/openclaw-enterprise-recovery-chain.py")
FIXTURE = module("oce_chain_capture_fixture",
                 "scripts/ci/openclaw-enterprise-capture-test.py")
SHA = FIXTURE.SHA
BACKUP_ID = "b" * 64


class RecoveryChain(unittest.TestCase):
    def setUp(self):
        self.fixture = FIXTURE.CaptureAssembler(
            "test_assembles_complete_private_tree_without_authorizing_publication")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.marker = self.fixture.run_assemble()
        marker_sha = hashlib.sha256(
            (self.fixture.output / "recovery.json").read_bytes()).hexdigest()
        self.watch = {"scope": "tenant-pod-watch", "publishable": False,
                      "sourceSha": SHA, "backupId": BACKUP_ID,
                      "tenantReaderPodUid": self.marker["tenantReaderPodUid"],
                      "observationSha256": self.marker["observationSha256"],
                      "markerSha256": marker_sha,
                      "startResourceVersion": "10", "endResourceVersion": "17"}
        self.ciphertext = self.fixture.root / "backup.tar.age"
        self.ciphertext.write_bytes(b"synthetic-encrypted-archive")
        self.ciphertext.chmod(0o600)

    def inspect(self, watch=None):
        return CHAIN.inspect_material(
            self.fixture.output, self.fixture.config, SHA, BACKUP_ID,
            self.watch if watch is None else watch)

    def references(self, material=None):
        material = self.inspect() if material is None else material
        expected = {field: material[field] for field in (
            "sourceSha", "backupId", "materialSha256", "installationId",
            "namespaceId", "agentId", "revisionId")}
        expected.update({
            "bucket": "homelab-application-backups-716182248480-us-east-1",
            "key": "openclaw-enterprise/new/" + BACKUP_ID + ".tar.age",
            "ciphertext": {"bytes": self.ciphertext.stat().st_size,
                           "sha256": hashlib.sha256(
                               self.ciphertext.read_bytes()).hexdigest()},
            "versionId": "immutable-version-one"})
        publication = {**expected, "workflow": "OpenClaw Enterprise Recovery Publication",
                       "runId": 101, "runHeadSha": SHA}
        restore = {**expected, "workflow": "OpenClaw Enterprise Recovery Restore",
                   "runId": 102, "runHeadSha": SHA, "isolated": True,
                   "databaseRestored": True,
                   "recoveryMaterialRestored": True}
        final_watch = {**self.watch, "throughPhase": "after-independent-restore",
                       "endResourceVersion": "23"}
        return material, publication, restore, final_watch

    def bind(self, material, publication, restore, final_watch):
        return CHAIN.bind_external_references(
            material, self.fixture.output, self.ciphertext,
            publication, restore, self.watch, final_watch, self.fixture.config)

    def test_complete_assembler_tree_and_exact_external_references_remain_unpublishable(self):
        material, publication, restore, watch = self.references()
        receipt = self.bind(material, publication, restore, watch)
        self.assertEqual(receipt["scope"], "source-only-recovery-chain")
        self.assertFalse(material["publishable"] or receipt["publishable"])
        self.assertEqual(receipt["materialSha256"], material["materialSha256"])
        self.assertEqual(receipt["namespaceId"], "ns_one")
        self.assertEqual(receipt["restoreRunId"], 102)

    def test_changed_operator_tenant_or_agent_byte_blocks_reference_binding(self):
        material, publication, restore, watch = self.references()
        secret = next((self.fixture.output / "tenant/secrets").iterdir())
        for path in (self.fixture.output / "journal/journal.json", secret,
                     self.fixture.output / "agent/state/state/openclaw.sqlite"):
            with self.subTest(path=path.relative_to(self.fixture.output)):
                original = path.read_bytes()
                path.write_bytes(original + b"tampered")
                with self.assertRaises(CHAIN.Blocked):
                    self.bind(material, publication, restore, watch)
                path.write_bytes(original)

    def test_marker_watch_or_namespace_identity_change_blocks_inspection(self):
        changed_watch = copy.deepcopy(self.watch)
        changed_watch["markerSha256"] = "0" * 64
        with self.assertRaises(CHAIN.Blocked):
            self.inspect(changed_watch)
        identity = self.fixture.output / "agent/identity.json"
        original = identity.read_bytes()
        identity.write_bytes(original.replace(b'"namespaceId":"ns_one"',
                                              b'"namespaceId":"ns_other"'))
        with self.assertRaises(CHAIN.Blocked):
            self.inspect()

    def test_missing_source_or_unsafe_link_blocks_full_tree(self):
        target = self.fixture.output / "bootstrap/initial-admin-password"
        target.unlink()
        with self.assertRaises(CHAIN.Blocked):
            self.inspect()
        target.symlink_to(self.fixture.output / "recovery.json")
        with self.assertRaises(CHAIN.Blocked):
            self.inspect()

    def test_wrong_destination_version_restore_run_and_identity_block(self):
        material, publication, restore, watch = self.references()
        for target, key, value in (
                (publication, "key", "openclaw-enterprise/legacy/foreign.tar.age"),
                (restore, "versionId", "other-version"),
                (restore, "runId", publication["runId"]),
                (restore, "namespaceId", "ns_foreign"),
                (restore, "databaseRestored", False),
                (restore, "runHeadSha", "0" * 40),
                (watch, "markerSha256", "0" * 64),
                (watch, "startResourceVersion", "11")):
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(target)
                changed[key] = value
                args = (changed if target is publication else publication,
                        changed if target is restore else restore,
                        changed if target is watch else watch)
                with self.assertRaises(CHAIN.Blocked):
                    self.bind(material, *args)

    def test_changed_ciphertext_blocks_publication_reference(self):
        material, publication, restore, watch = self.references()
        self.ciphertext.write_bytes(b"different-encrypted-archive")
        with self.assertRaises(CHAIN.Blocked):
            self.bind(material, publication, restore, watch)


if __name__ == "__main__":
    unittest.main()
