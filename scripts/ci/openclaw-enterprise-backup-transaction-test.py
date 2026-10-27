#!/usr/bin/env python3
"""Offline failure fixtures for the dormant Enterprise backup transaction."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "oce_backup_base", ROOT / "scripts/ci/openclaw-enterprise-test.py")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
OCE = BASE.OCE


class BackupAPI(BASE.ActiveTenantAPI):
    """Pinned deploy creates a new revision even at unchanged generation."""

    def post_accepted(self, path, body=None):
        if (path.endswith("/deploy") and len(self.revisions) >= 2 and
                self.agents["agt_one"]["desiredRuntimeState"] == "stopped"):
            self.calls.append(("POST-202", path, copy.deepcopy(body)))
            revision_id = f"rev_backup_{len(self.revisions) + 1}"
            revision = copy.deepcopy(self.revisions["rev_two"])
            revision["id"] = revision_id
            self.revisions[revision_id] = revision
            self.deployments[revision_id] = {
                "deploymentId": revision_id, "namespaceId": "ns_one",
                "agentId": "agt_one", "status": "succeeded"}
            self.agents["agt_one"]["desiredRuntimeState"] = "running"
            self.agents["agt_one"]["activeRevisionId"] = revision_id
            self.runtime_pods = [{"name": "agent-one"}]
            if self.lose == "deploy":
                self.lose = None
                raise OCE.Blocked("lost backup deploy response")
            return copy.deepcopy(revision)
        return super().post_accepted(path, body)


class BackupTransaction(unittest.TestCase):
    backup_id = "b" * 64

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-backup-transaction-")
        self.addCleanup(self.temp.cleanup)
        private = Path(self.temp.name).resolve() / "private"
        private.mkdir(mode=0o700)
        self.config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.config["privateJournal"]["mountPath"] = str(private / "journal.json")
        self.api = BackupAPI()
        self.kube = BASE.TenantKubernetes(self.api)
        credential = {"version": 1, "key": "new-openrouter-key-only"}
        with OCE.ProtectedJournal(private / "journal.json", self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as journal:
            journal.save({"installationId": "ins_one", "namespaceId": "ns_one"})
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            OCE.reconcile(self.config, self.api, self.kube, "a" * 40)
        self.config["activationEnabled"] = True
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            OCE.reconcile_active(self.config, self.api, self.kube, credential)
        self.config["privateOrigins"]["nativeOrigin"] = (
            "https://agent-da7e7bd6a45b40f25fcbdbf97f38683e.agents.oce.stinkyboi.com")
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            OCE.reconcile_active(self.config, self.api, self.kube, credential)
        self.credential = credential

    def _journal(self):
        return OCE.read_journal(self.config["privateJournal"]["mountPath"],
                                self.config["source"]["revision"],
                                OCE._identity_hash(self.config))[0]

    def _begin(self, backup_id=None):
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}), \
                patch.object(OCE, "check", return_value={"installationId": "ins_one"}):
            return OCE.begin_backup_stop(self.config, self.api, self.kube,
                                         "a" * 40, backup_id or self.backup_id)

    def _resume(self, verify_capture=None):
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}), \
                patch.object(OCE, "check", return_value={"installationId": "ins_one"}):
            return OCE.resume_backup(self.config, self.api, self.kube, "a" * 40,
                                     self.backup_id, verify_capture)

    @staticmethod
    def _capture(context):
        assert context == {"backupId": "b" * 64, "namespaceId": "ns_one",
                           "agentId": "agt_one", "revisionId": "rev_two"}
        return "c" * 64

    def _writes(self, suffix):
        return [call for call in self.api.calls if call[1].endswith(suffix) and
                call[0].startswith("POST")]

    def test_completed_transaction_retries_and_ordinary_reconcile_do_not_redeploy(self):
        self.assertEqual(self._begin()["phase"], "stopped")
        self.assertEqual(self._begin()["phase"], "stopped")
        self.assertEqual(len(self._writes("/stop")), 1)
        self.assertEqual(self._resume(self._capture)["revisionId"], "rev_backup_3")
        self.assertEqual(self._resume(self._capture)["revisionId"], "rev_backup_3")
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}), \
                patch.object(OCE, "check", return_value={"installationId": "ins_one"}):
            self.assertEqual(OCE.reconcile_active(self.config, self.api, self.kube,
                                                  self.credential)["revisionId"], "rev_backup_3")
        self.assertEqual(len(self._writes("/deploy")), 3)
        self.assertEqual(self._journal()["revisionIds"], ["rev_one", "rev_two", "rev_backup_3"])
        self.assertEqual(self._journal()["backup"]["phase"], "complete")

    def test_lost_stop_response_and_restart_adopt_exact_stopped_state(self):
        self.api.lose = "stop"
        with self.assertRaisesRegex(OCE.Blocked, "lost stop response"):
            self._begin()
        self.assertEqual(self._journal()["backup"]["phase"], "stopping")
        self.assertEqual(self._begin()["phase"], "stopped")
        self.assertEqual(len(self._writes("/stop")), 1)

    def test_unknown_stop_does_not_repost_or_clear_intent(self):
        with patch.object(self.api, "post_accepted", side_effect=OCE.Blocked("lost stop")) as post:
            with self.assertRaisesRegex(OCE.Blocked, "lost stop"):
                self._begin()
            with self.assertRaisesRegex(OCE.Blocked, "stop outcome is unknown"):
                self._begin()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(self._journal()["backup"]["phase"], "stopping")
        self.api.agents["agt_one"]["desiredRuntimeState"] = "stopped"
        self.api.agents["agt_one"]["activeRevisionId"] = None
        self.api.runtime_pods = []
        self.assertEqual(self._begin()["phase"], "stopped")

    def test_missing_capture_proof_blocks_resume_and_normal_reconcile(self):
        self._begin()
        with self.assertRaisesRegex(OCE.Blocked, "capture proof"):
            self._resume()
        with self.assertRaisesRegex(OCE.Blocked, "capture proof"):
            self._resume(lambda _context: None)
        with self.assertRaisesRegex(OCE.Blocked, "backup transaction"):
            with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
                OCE.reconcile_active(self.config, self.api, self.kube, self.credential)
        self.assertEqual(len(self._writes("/deploy")), 2)
        self.assertEqual(self._journal()["backup"]["phase"], "stopped")
        with patch.object(OCE, "prove_driver_identity", return_value={"installationId": "ins_one"}):
            with self.assertRaisesRegex(OCE.Blocked, "backup transaction"):
                OCE.stop_agent(self.config, self.api, self.kube, "a" * 40)
        self.assertEqual(len(self._writes("/stop")), 1)

    def test_changed_stopped_agent_blocks_before_capture_callback(self):
        self._begin()
        self.api.agents["agt_one"]["desiredRuntimeState"] = "running"
        self.api.agents["agt_one"]["activeRevisionId"] = "rev_two"
        with patch.object(self, "_capture", return_value="c" * 64) as capture:
            with self.assertRaisesRegex(OCE.Blocked, "backup stop proof changed"):
                self._resume(capture)
        capture.assert_not_called()
        self.assertEqual(len(self._writes("/deploy")), 2)
        self.assertEqual(self._journal()["backup"]["phase"], "stopped")

    def test_definitive_stop_rejection_resets_only_proven_unchanged_intent(self):
        with patch.object(self.api, "post_accepted",
                          side_effect=OCE.DefinitiveRejection("HTTP 403")):
            with self.assertRaises(OCE.DefinitiveRejection):
                self._begin()
        self.assertNotIn("backup", self._journal())
        self.assertEqual(self._begin()["phase"], "stopped")
        self.assertEqual(len(self._writes("/stop")), 1)

    def test_definitive_deploy_rejection_preserves_stopped_capture(self):
        self._begin()
        with patch.object(self.api, "post_accepted",
                          side_effect=OCE.DefinitiveRejection("HTTP 403")):
            with self.assertRaises(OCE.DefinitiveRejection):
                self._resume(self._capture)
        self.assertEqual(self._journal()["backup"]["phase"], "stopped")
        self.assertEqual(self._resume(self._capture)["revisionId"], "rev_backup_3")
        self.assertEqual(len(self._writes("/deploy")), 3)

    def test_lost_deploy_response_and_crash_adopt_one_exact_revision(self):
        self._begin()
        self.api.lose = "deploy"
        with self.assertRaisesRegex(OCE.Blocked, "lost backup deploy response"):
            self._resume(self._capture)
        self.assertEqual(self._journal()["backup"]["phase"], "resuming")
        self.assertEqual(self._resume(self._capture)["revisionId"], "rev_backup_3")
        self.assertEqual(len(self._writes("/deploy")), 3)

    def test_crash_after_resume_intent_blocks_repost_without_revision(self):
        self._begin()
        original_save = OCE.ProtectedJournal.save

        def crash_after_intent(journal, state):
            original_save(journal, state)
            if state.get("backup", {}).get("phase") == "resuming":
                raise RuntimeError("process died before POST")

        with patch.object(OCE.ProtectedJournal, "save", crash_after_intent):
            with self.assertRaisesRegex(RuntimeError, "before POST"):
                self._resume(self._capture)
        with self.assertRaisesRegex(OCE.Blocked, "outcome remains unknown"):
            self._resume(self._capture)
        self.assertEqual(len(self._writes("/deploy")), 2)
        self.assertEqual(self._journal()["backup"]["phase"], "resuming")

    def test_crash_after_completed_journal_retry_is_idempotent(self):
        self._begin()
        original_save = OCE.ProtectedJournal.save

        def crash_after_completion(journal, state):
            original_save(journal, state)
            if state.get("backup", {}).get("phase") == "complete":
                raise RuntimeError("process died after durable commit")

        with patch.object(OCE.ProtectedJournal, "save", crash_after_completion):
            with self.assertRaisesRegex(RuntimeError, "after durable commit"):
                self._resume(self._capture)
        self.assertEqual(self._resume(self._capture)["revisionId"], "rev_backup_3")
        self.assertEqual(len(self._writes("/deploy")), 3)

    def test_changed_capture_proof_cannot_adopt_pending_deploy(self):
        self._begin()
        self.api.lose = "deploy"
        with self.assertRaisesRegex(OCE.Blocked, "lost backup deploy response"):
            self._resume(self._capture)
        with self.assertRaisesRegex(OCE.Blocked, "capture proof changed"):
            self._resume(lambda _context: "d" * 64)
        self.assertEqual(len(self._writes("/deploy")), 3)
        self.assertEqual(self._journal()["backup"]["phase"], "resuming")

    def test_second_backup_uses_new_transaction_id_and_extends_history(self):
        self._begin()
        self._resume(self._capture)
        self.backup_id = "d" * 64
        self.assertEqual(self._begin()["revisionId"], "rev_backup_3")

        def second_capture(context):
            self.assertEqual(context["backupId"], "d" * 64)
            self.assertEqual(context["revisionId"], "rev_backup_3")
            return "e" * 64

        self.assertEqual(self._resume(second_capture)["revisionId"], "rev_backup_4")
        self.assertEqual(self._journal()["revisionIds"],
                         ["rev_one", "rev_two", "rev_backup_3", "rev_backup_4"])
        self.assertEqual(len(self._writes("/stop")), 2)
        self.assertEqual(len(self._writes("/deploy")), 4)

    def test_unknown_deploy_never_reposts_and_foreign_revision_blocks(self):
        self._begin()
        with patch.object(self.api, "post_accepted", side_effect=OCE.Blocked("lost deploy")) as post:
            with self.assertRaisesRegex(OCE.Blocked, "lost deploy"):
                self._resume(self._capture)
            with self.assertRaisesRegex(OCE.Blocked, "outcome remains unknown"):
                self._resume(self._capture)
        self.assertEqual(post.call_count, 1)
        foreign = copy.deepcopy(self.api.revisions["rev_two"])
        foreign["id"] = "rev_foreign"
        foreign["configurationGeneration"] = 99
        self.api.revisions["rev_foreign"] = foreign
        with self.assertRaisesRegex(OCE.Blocked, "ambiguous deploy outcome"):
            self._resume(self._capture)
        self.assertEqual(self._journal()["backup"]["phase"], "resuming")

    def test_duplicate_new_revisions_block_adoption_after_lost_response(self):
        self._begin()
        self.api.lose = "deploy"
        with self.assertRaisesRegex(OCE.Blocked, "lost backup deploy response"):
            self._resume(self._capture)
        duplicate = copy.deepcopy(self.api.revisions["rev_backup_3"])
        duplicate["id"] = "rev_duplicate"
        self.api.revisions["rev_duplicate"] = duplicate
        with self.assertRaisesRegex(OCE.Blocked, "ambiguous deploy outcome"):
            self._resume(self._capture)
        self.assertEqual(self._journal()["backup"]["phase"], "resuming")
        self.assertEqual(len(self._writes("/deploy")), 3)

    def test_foreign_revision_after_stop_blocks_resume_before_post(self):
        self._begin()
        foreign = copy.deepcopy(self.api.revisions["rev_two"])
        foreign["id"] = "rev_foreign"
        self.api.revisions["rev_foreign"] = foreign
        with self.assertRaisesRegex(OCE.Blocked, "revision history changed"):
            self._resume(self._capture)
        self.assertEqual(self._journal()["backup"]["phase"], "stopped")
        self.assertEqual(len(self._writes("/deploy")), 2)

    def test_incomplete_new_deployment_waits_without_repost(self):
        self._begin()
        original_post = self.api.post_accepted

        def queued(path, body=None):
            result = original_post(path, body)
            if path.endswith("/deploy"):
                self.api.deployments["rev_backup_3"]["status"] = "running"
            return result

        with patch.object(self.api, "post_accepted", side_effect=queued):
            with self.assertRaisesRegex(OCE.Blocked, "deployment is not complete"):
                self._resume(self._capture)
        self.assertEqual(self._journal()["backup"]["phase"], "resuming")
        self.api.deployments["rev_backup_3"]["status"] = "succeeded"
        self.assertEqual(self._resume(self._capture)["revisionId"], "rev_backup_3")
        self.assertEqual(len(self._writes("/deploy")), 3)

    def test_duplicate_or_foreign_history_blocks_stop_before_post(self):
        foreign = copy.deepcopy(self.api.revisions["rev_two"])
        foreign["id"] = "rev_foreign"
        self.api.revisions["rev_foreign"] = foreign
        with self.assertRaisesRegex(OCE.Blocked, "revision history changed"):
            self._begin()
        self.assertEqual(len(self._writes("/stop")), 0)
        del self.api.revisions["rev_foreign"]
        original = self.api.revisions_page

        def duplicate(path, cursor=None):
            page = original(path, cursor)
            page["data"].append(copy.deepcopy(page["data"][0]))
            return page

        with patch.object(self.api, "revisions_page", side_effect=duplicate):
            with self.assertRaisesRegex(OCE.Blocked, "revision history changed"):
                self._begin()
        self.assertEqual(len(self._writes("/stop")), 0)

    def test_full_journal_history_blocks_before_stop(self):
        state = self._journal()
        history = ["rev_one", "rev_two"]
        for number in range(3, 101):
            revision_id = f"rev_backup_{number}"
            revision = copy.deepcopy(self.api.revisions["rev_two"])
            revision["id"] = revision_id
            self.api.revisions[revision_id] = revision
            self.api.deployments[revision_id] = {
                "deploymentId": revision_id, "namespaceId": "ns_one",
                "agentId": "agt_one", "status": "succeeded"}
            history.append(revision_id)
        state["revisionIds"] = history
        state["revisionId"] = history[-1]
        self.api.agents["agt_one"]["activeRevisionId"] = history[-1]
        with OCE.ProtectedJournal(self.config["privateJournal"]["mountPath"],
                                  self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as journal:
            journal.save(state)
        with self.assertRaisesRegex(OCE.Blocked, "no resume headroom"):
            self._begin()
        self.assertEqual(len(self._writes("/stop")), 0)
        self.assertNotIn("backup", self._journal())


if __name__ == "__main__":
    unittest.main()
