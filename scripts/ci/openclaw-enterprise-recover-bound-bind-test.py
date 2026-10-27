#!/usr/bin/env python3
"""Offline adversarial checks for the dormant post-CAS binding recovery."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recovery = load("oce_bound_recovery", "scripts/ci/openclaw-enterprise-recover-bound-bind.py")
fixtures = load("oce_binding_fixtures", "scripts/ci/openclaw-enterprise-journal-operator-test.py")
SHA = fixtures.SHA
JOB_UID = fixtures.UUID
POD_UID = fixtures.POD_UID
OTHER_UID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
VERIFIER_POD_UID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


def receipt_fixture():
    candidate = (ROOT / "clusters/homelab/apps/openclaw-enterprise/installation.yaml").read_bytes()
    old = {"jobRv": "202", "jobHash": "a" * 64, "podHash": "b" * 64,
           "proofHash": "c" * 64, "logHash": "d" * 64,
           "storage": "e" * 64, "projectionId": (JOB_UID, "99"),
           "baseline": {recovery.journal.BINDING_VERSION: "100",
                        recovery.journal.BINDING_DIGEST: hashlib.sha256(candidate).hexdigest()}}
    verifier = {"name": "oce-journal-bind-installation-67890-1",
                "jobUid": OTHER_UID, "podUid": VERIFIER_POD_UID,
                "jobHash": "f" * 64, "podHash": "0" * 64,
                "proofHash": "1" * 64, "logHash": "2" * 64,
                "projectionUid": JOB_UID, "projectionRv": "99"}
    intended = recovery.receipt_object(SHA, old, verifier, SHA, "12345", "1",
                                       JOB_UID, POD_UID, JOB_UID, "101", "ins_one",
                                       "openclaw-system", "67890", "1")
    actual = copy.deepcopy(intended)
    actual["metadata"].update({"uid": OTHER_UID, "resourceVersion": "303"})
    return intended, actual, verifier


class BoundRecovery(unittest.TestCase):
    def test_failed_source_proof_is_source_bound_and_stale_or_unbound_blocks(self):
        operator, job, actual, pod, _, proof = fixtures.binding_objects()
        now = int(time.time())
        pod["metadata"]["creationTimestamp"] = "2026-10-26T00:00:00Z"
        pod["status"] = {"phase": "Failed", "containerStatuses": [{
            "name": "operator", "state": {"terminated": {
                "exitCode": 1, "finishedAt": "2026-10-28T00:00:00Z"}}}]}
        proof["issuedAt"] = now
        log = "OCE_BIND_READY:" + json.dumps(proof, separators=(",", ":")) + "\n"
        with mock.patch.object(recovery.journal, "command", return_value=log):
            observed = recovery.proof_from_pod("openclaw-system", pod, SHA,
                                               job["metadata"]["name"], JOB_UID,
                                               "100", "ins_one", False)
        self.assertEqual(observed[1], hashlib.sha256(log.encode()).hexdigest())
        for changed in ({"alreadyBound": True}, {"installationId": "ins_other"},
                        {"secretResourceVersion": "101"}, {"jobName": "foreign"},
                        {"issuedAt": 1}):
            other = {**proof, **changed}
            raw = "OCE_BIND_READY:" + json.dumps(other) + "\n"
            with self.subTest(changed=changed), \
                 mock.patch.object(recovery.journal, "command", return_value=raw), \
                 self.assertRaises(recovery.journal.Blocked):
                recovery.proof_from_pod("openclaw-system", pod, SHA,
                                        job["metadata"]["name"], JOB_UID,
                                        "100", "ins_one", False)
        with mock.patch.object(recovery.journal, "command", return_value=log * 2), \
             self.assertRaises(recovery.journal.Blocked):
            recovery.proof_from_pod("openclaw-system", pod, SHA,
                                    job["metadata"]["name"], JOB_UID,
                                    "100", "ins_one", False)
        with mock.patch.object(recovery.journal, "command", return_value=log), \
             self.assertRaises(recovery.journal.Blocked):
            recovery.proof_from_pod("openclaw-system", pod, SHA,
                                    job["metadata"]["name"], JOB_UID,
                                    "100", "ins_one", True)

    def test_bound_secret_requires_original_uid_new_exact_rv_and_annotation(self):
        operator, job, _, _, secret, _ = fixtures.binding_objects()
        original = job["spec"]["template"]["metadata"]["annotations"]
        bound = copy.deepcopy(secret)
        bound["metadata"]["resourceVersion"] = "101"
        bound["metadata"]["annotations"]["openclaw.dev/installation-id"] = "ins_one"
        observed = {**original, recovery.journal.BINDING_VERSION: "101"}
        with mock.patch.object(recovery.journal, "binding_secret_baseline",
                               return_value=observed), \
             mock.patch.object(recovery.journal, "kubectl_json", return_value=bound):
            self.assertEqual(recovery.prove_bound_secret(operator, original,
                                                         JOB_UID, "101", "ins_one"),
                             observed)
        for change in ("old_version", "uid", "id", "extra_annotation", "deleting"):
            altered = copy.deepcopy(bound)
            if change == "old_version":
                altered["metadata"]["resourceVersion"] = "100"
            elif change == "uid":
                altered["metadata"]["uid"] = OTHER_UID
            elif change == "id":
                altered["metadata"]["annotations"]["openclaw.dev/installation-id"] = "ins_other"
            elif change == "extra_annotation":
                altered["metadata"]["annotations"]["foreign"] = "value"
            else:
                altered["metadata"]["deletionTimestamp"] = "now"
            with self.subTest(change=change), \
                 mock.patch.object(recovery.journal, "binding_secret_baseline",
                                   return_value=observed), \
                 mock.patch.object(recovery.journal, "kubectl_json", return_value=altered), \
                 self.assertRaises(recovery.journal.Blocked):
                recovery.prove_bound_secret(operator, original, JOB_UID, "101", "ins_one")

    def test_lost_verifier_create_response_reconciles_without_any_cas(self):
        operator, _, _, _, _, _ = fixtures.binding_objects()
        config = fixtures.ready_operator()
        projection = fixtures.projection(config)
        baseline = {recovery.journal.BINDING_UID: JOB_UID,
                    recovery.journal.BINDING_VERSION: "101",
                    recovery.journal.BINDING_DIGEST:
                        hashlib.sha256((ROOT / "clusters/homelab/apps/openclaw-enterprise/installation.yaml").read_bytes()).hexdigest(),
                    recovery.journal.BINDING_IMMUTABLE: "true"}
        intended = recovery.journal.build_job("bind-installation", SHA, "67890",
                                              operator, projection, "1", baseline=baseline)
        actual = copy.deepcopy(intended)
        actual["metadata"]["uid"] = OTHER_UID
        actual["status"] = {"succeeded": 1,
                            "conditions": [{"type": "Complete", "status": "True"}]}
        pod = {"metadata": {"name": intended["metadata"]["name"] + "-abcde",
                            "uid": POD_UID}}
        commands = []

        def command(args, **_):
            commands.append(args)
            if "create" in args:
                raise recovery.journal.Blocked("lost response")
            return ""

        def kubectl(*args):
            if "jobs" in args:
                return {"items": [{"metadata": {"name": "old"}}]}
            if "job" in args:
                return actual
            if "pods" in args:
                return {"items": [pod]}
            self.fail(args)

        with mock.patch.object(recovery.journal, "config_projection", return_value=projection), \
             mock.patch.object(recovery.journal, "binding_secret_baseline", return_value=baseline), \
             mock.patch.object(recovery.journal, "kubectl_json", side_effect=kubectl), \
             mock.patch.object(recovery.journal, "command", side_effect=command), \
             mock.patch.object(recovery.journal, "exact_main"), \
             mock.patch.object(recovery.journal, "prove_or_create_projection"), \
             mock.patch.object(recovery.cleanup, "prove_projection"), \
             mock.patch.object(recovery.cleanup, "prove_jobs"), \
             mock.patch.object(recovery.cleanup, "prove_pod"), \
             mock.patch.object(recovery, "proof_from_pod", return_value=("proof", "log")), \
             mock.patch.object(recovery.journal, "bind_proof_and_patch",
                               side_effect=AssertionError("CAS callback called")):
            result = recovery.verify_without_cas(SHA, "67890", "1", "old", JOB_UID,
                                                 JOB_UID, "101", "ins_one", config,
                                                 operator, {})
        self.assertEqual(result["jobUid"], OTHER_UID)
        self.assertTrue(any("create" in command for command in commands))
        self.assertFalse(any("patch" in command for command in commands))

    def test_receipt_lost_create_response_requires_exact_immutable_readback(self):
        receipt = {"apiVersion": "v1", "kind": "ConfigMap", "immutable": True,
                   "metadata": {"name": "oce-bound-bind-abc-123", "namespace": "openclaw-system",
                                "labels": {"app.kubernetes.io/part-of": "openclaw-enterprise"}},
                   "data": {"receipt.json": "{}"}}
        actual = copy.deepcopy(receipt)
        actual["metadata"].update({"uid": JOB_UID, "resourceVersion": "202"})
        with mock.patch.object(recovery.journal, "exact_main"), \
             mock.patch.object(recovery.journal, "command",
                               side_effect=recovery.journal.Blocked("lost response")), \
             mock.patch.object(recovery.journal, "kubectl_json", return_value=actual):
            self.assertEqual(recovery.save_receipt(SHA, {}, receipt, "openclaw-system"),
                             (JOB_UID, "202"))
        actual["data"]["receipt.json"] = "forged"
        with mock.patch.object(recovery.journal, "exact_main"), \
             mock.patch.object(recovery.journal, "command",
                               side_effect=recovery.journal.Blocked("lost response")), \
             mock.patch.object(recovery.journal, "kubectl_json", return_value=actual), \
             self.assertRaises(recovery.journal.Blocked):
            recovery.save_receipt(SHA, {}, receipt, "openclaw-system")

    def test_replayed_workflow_attempt_gets_distinct_receipt_name(self):
        old = {"jobRv": "202", "jobHash": "a" * 64, "podHash": "b" * 64,
               "proofHash": "c" * 64, "logHash": "d" * 64,
               "projectionId": (JOB_UID, "99"), "storage": "e" * 64,
               "baseline": {recovery.journal.BINDING_VERSION: "100",
                            recovery.journal.BINDING_DIGEST: "e" * 64}}
        args = (SHA, old, {"jobUid": OTHER_UID}, SHA, "12345", "1",
                JOB_UID, POD_UID, JOB_UID, "101", "ins_one", "openclaw-system", "67890")
        first = recovery.receipt_object(*args, "1")
        second = recovery.receipt_object(*args, "2")
        self.assertNotEqual(first["metadata"]["name"], second["metadata"]["name"])
        self.assertLessEqual(len(second["metadata"]["name"]), 63)

    def test_completed_receipt_required_and_bound_to_failed_identity(self):
        intended, actual, _ = receipt_fixture()
        def read(*args):
            return {"items": [actual]} if "configmaps" in args else actual
        with mock.patch.object(recovery.journal, "kubectl_json", side_effect=read):
            receipts = recovery.completed_receipts("openclaw-system", SHA, "12345", "1",
                                                   JOB_UID, POD_UID, JOB_UID, "101",
                                                   "ins_one")
        self.assertEqual(receipts[0][1], intended)
        for change in ("missing", "wrong_id", "wrong_uid", "wrong_verifier",
                       "mutable", "foreign_labels"):
            candidate = copy.deepcopy(actual)
            if change == "wrong_id":
                data = json.loads(candidate["data"]["receipt.json"])
                data["binding"]["installationId"] = "ins_other"
                candidate["data"]["receipt.json"] = json.dumps(data)
            elif change == "wrong_uid":
                data = json.loads(candidate["data"]["receipt.json"])
                data["failed"]["jobUid"] = OTHER_UID
                candidate["data"]["receipt.json"] = json.dumps(data)
            elif change == "wrong_verifier":
                data = json.loads(candidate["data"]["receipt.json"])
                data["verifier"]["name"] = "oce-journal-bind-installation-99999-1"
                candidate["data"]["receipt.json"] = json.dumps(data)
            elif change == "mutable":
                candidate["immutable"] = False
            elif change == "foreign_labels":
                candidate["metadata"]["labels"]["foreign"] = "value"
            with self.subTest(change=change), \
                 mock.patch.object(recovery.journal, "kubectl_json",
                                   return_value={"items": []} if change == "missing"
                                   else {"items": [candidate]}), \
                 self.assertRaises(recovery.journal.Blocked):
                recovery.completed_receipts("openclaw-system", SHA, "12345", "1",
                                            JOB_UID, POD_UID, JOB_UID, "101", "ins_one")

    def test_completed_path_rejects_replacement_job_or_old_pod(self):
        old_name = "oce-journal-bind-installation-12345-1"
        for change in ("old_job", "replacement_job", "old_pod", "replacement_pod"):
            jobs, pods = [], []
            if change in ("old_job", "replacement_job"):
                jobs = [{"metadata": {"name": old_name,
                                       "uid": JOB_UID if change == "old_job" else OTHER_UID}}]
            if change in ("old_pod", "replacement_pod"):
                pods = [{"metadata": {"name": old_name + "-abcde",
                                       "uid": POD_UID if change == "old_pod" else OTHER_UID}}]
            def read(*args):
                return {"items": jobs if "jobs" in args else pods}
            with self.subTest(change=change), \
                 mock.patch.object(recovery.journal, "kubectl_json", side_effect=read), \
                 self.assertRaises(recovery.journal.Blocked):
                recovery.prove_old_absent("openclaw-system", old_name, JOB_UID, POD_UID)

    def test_completed_path_reproves_verifier_and_never_writes(self):
        intended_receipt, _, verifier = receipt_fixture()
        receipt = json.loads(intended_receipt["data"]["receipt.json"])
        config = fixtures.ready_operator()
        operator = config["journalOperator"]
        projection = fixtures.projection(config)
        baseline = {recovery.journal.BINDING_UID: JOB_UID,
                    recovery.journal.BINDING_VERSION: "101",
                    recovery.journal.BINDING_DIGEST: receipt["binding"]["candidateSha256"],
                    recovery.journal.BINDING_IMMUTABLE: "true"}
        desired = recovery.journal.build_job("bind-installation", SHA, "67890",
                                             operator, projection, "1", baseline=baseline)
        actual = copy.deepcopy(desired)
        actual["metadata"]["uid"] = OTHER_UID
        actual["status"] = {"succeeded": 1,
                            "conditions": [{"type": "Complete", "status": "True"}]}
        pod = {"metadata": {"name": verifier["name"] + "-abcde",
                            "uid": VERIFIER_POD_UID}}
        verifier["jobHash"] = recovery.digest(actual)
        verifier["podHash"] = recovery.digest(pod)
        receipt["verifier"] = verifier
        intended_receipt["data"]["receipt.json"] = json.dumps(
            receipt, sort_keys=True, separators=(",", ":"))

        def read(*args):
            return actual if "job" in args else {"items": [pod]}

        common = [mock.patch.object(recovery, "completed_receipts",
                                    return_value=[(receipt, intended_receipt,
                                                   (OTHER_UID, "303"))]),
                  mock.patch.object(recovery.cleanup, "source_contract"),
                  mock.patch.object(recovery, "prove_old_absent"),
                  mock.patch.object(recovery, "prove_bound_secret"),
                  mock.patch.object(recovery.cleanup, "prove_retained_storage",
                                    return_value=receipt["failed"]["storageHash"]),
                  mock.patch.object(recovery.journal, "config_projection",
                                    return_value=projection),
                  mock.patch.object(recovery.cleanup, "prove_projection",
                                    return_value=(JOB_UID, "99")),
                  mock.patch.object(recovery.journal, "kubectl_json", side_effect=read),
                  mock.patch.object(recovery.cleanup, "prove_pod"),
                  mock.patch.object(recovery, "proof_from_pod",
                                    return_value=(verifier["proofHash"],
                                                  verifier["logHash"])),
                  mock.patch.object(recovery, "prove_receipt",
                                    return_value=(OTHER_UID, "303")),
                  mock.patch.object(recovery.journal, "exact_main"),
                  mock.patch.object(recovery.journal, "command",
                                    side_effect=AssertionError("read-only path ran command")),
                  mock.patch.object(recovery, "save_receipt",
                                    side_effect=AssertionError("receipt rewrite")),
                  mock.patch.object(recovery.cleanup, "delete_once",
                                    side_effect=AssertionError("second DELETE"))]
        for patcher in common:
            patcher.start()
        try:
            recovery.prove_completed_recovery(SHA, SHA, "12345", "1", JOB_UID,
                                              POD_UID, JOB_UID, "101", "ins_one",
                                              config, operator, {})
            self.assertEqual(recovery.completed_receipts.call_count, 2)
        finally:
            for patcher in reversed(common):
                patcher.stop()

    def test_completed_path_blocks_secret_or_storage_drift(self):
        intended, _, verifier = receipt_fixture()
        receipt = json.loads(intended["data"]["receipt.json"])
        config = fixtures.ready_operator()
        operator = config["journalOperator"]
        for drift in ("secret", "storage", "projection"):
            with self.subTest(drift=drift), \
                 mock.patch.object(recovery, "prove_old_absent"), \
                 mock.patch.object(recovery, "completed_receipts",
                                   return_value=[(receipt, intended, (OTHER_UID, "303"))]), \
                 mock.patch.object(recovery.cleanup, "source_contract"), \
                 mock.patch.object(recovery, "prove_bound_secret",
                                   side_effect=(recovery.journal.Blocked("secret drift")
                                                if drift == "secret" else None)), \
                 mock.patch.object(recovery.cleanup, "prove_retained_storage",
                                   return_value="wrong" if drift == "storage" else
                                   receipt["failed"]["storageHash"]), \
                 mock.patch.object(recovery.journal, "config_projection",
                                   return_value=fixtures.projection(config)), \
                 mock.patch.object(recovery.cleanup, "prove_projection",
                                   return_value=(OTHER_UID, "99") if drift == "projection"
                                   else (JOB_UID, "99")), \
                 self.assertRaises(recovery.journal.Blocked):
                recovery.prove_completed_recovery(SHA, SHA, "12345", "1", JOB_UID,
                                                  POD_UID, JOB_UID, "101", "ins_one",
                                                  config, operator, {})

    def test_cancel_after_delete_uses_only_completed_read_path(self):
        own = (ROOT / "scripts/ci/openclaw-enterprise-recover-bound-bind.py").read_text()
        with mock.patch.object(recovery.journal, "exact_main"), \
             mock.patch.object(recovery.cleanup, "source_contract"), \
             mock.patch.object(recovery.journal, "command", return_value=own), \
             mock.patch.object(recovery.journal, "prove_committed_inputs"), \
             mock.patch.object(recovery.journal, "contract",
                               return_value=fixtures.ready_operator()["journalOperator"]), \
             mock.patch.object(recovery.journal, "prove_image_source"), \
             mock.patch.object(recovery.journal, "prove_claims"), \
             mock.patch.object(recovery.journal, "kubectl_json",
                               return_value={"items": []}), \
             mock.patch.object(recovery, "prove_completed_recovery") as completed, \
             mock.patch.object(recovery, "verify_without_cas",
                               side_effect=AssertionError("created another Job")), \
             mock.patch.object(recovery, "save_receipt",
                               side_effect=AssertionError("wrote another receipt")), \
             mock.patch.object(recovery.cleanup, "delete_once",
                               side_effect=AssertionError("second DELETE")):
            result = recovery.main([SHA, "12345", "1", JOB_UID, POD_UID,
                                    JOB_UID, "101", "ins_one"],
                                   {"EXPECTED_SHA": SHA, "GITHUB_RUN_ID": "67891",
                                    "GITHUB_RUN_ATTEMPT": "1"})
        self.assertEqual(result, 0)
        completed.assert_called_once()

    def test_changed_old_job_after_verifier_blocks_receipt_and_delete(self):
        old = {"name": "oce-journal-bind-installation-12345-1", "jobRv": "202",
               "baseline": {recovery.journal.BINDING_VERSION: "100",
                            recovery.journal.BINDING_DIGEST: "a" * 64},
               "projection": {}, "projectionId": (JOB_UID, "99"),
               "storage": "storage", "jobHash": "a" * 64, "podHash": "b" * 64,
               "proofHash": "c" * 64, "logHash": "d" * 64}
        changed = {**old, "jobRv": "203"}
        own = (ROOT / "scripts/ci/openclaw-enterprise-recover-bound-bind.py").read_text()
        with mock.patch.object(recovery.journal, "exact_main"), \
             mock.patch.object(recovery.cleanup, "source_contract"), \
             mock.patch.object(recovery.journal, "command", return_value=own), \
             mock.patch.object(recovery.journal, "kubectl_json",
                               return_value={"items": [{"metadata": {
                                   "name": old["name"], "uid": JOB_UID}}]}), \
             mock.patch.object(recovery.journal, "prove_committed_inputs"), \
             mock.patch.object(recovery.journal, "contract",
                               return_value=fixtures.ready_operator()["journalOperator"]), \
             mock.patch.object(recovery.journal, "prove_image_source"), \
             mock.patch.object(recovery.journal, "prove_claims"), \
             mock.patch.object(recovery, "prove_failed_source",
                               side_effect=[old, old, changed]), \
             mock.patch.object(recovery, "verify_without_cas", return_value={}), \
             mock.patch.object(recovery, "save_receipt") as receipt, \
             mock.patch.object(recovery.cleanup, "delete_once") as delete:
            result = recovery.main([SHA, "12345", "1", JOB_UID, POD_UID,
                                    JOB_UID, "101", "ins_one"],
                                   {"EXPECTED_SHA": SHA, "GITHUB_RUN_ID": "67890",
                                    "GITHUB_RUN_ATTEMPT": "1"})
        self.assertEqual(result, 1)
        receipt.assert_not_called()
        delete.assert_not_called()

    def test_old_job_change_after_receipt_still_blocks_delete(self):
        old = {"name": "oce-journal-bind-installation-12345-1", "jobRv": "202",
               "baseline": {recovery.journal.BINDING_VERSION: "100",
                            recovery.journal.BINDING_DIGEST: "a" * 64},
               "projection": {}, "projectionId": (JOB_UID, "99"),
               "storage": "storage", "jobHash": "a" * 64, "podHash": "b" * 64,
               "proofHash": "c" * 64, "logHash": "d" * 64}
        changed = {**old, "podHash": "e" * 64}
        own = (ROOT / "scripts/ci/openclaw-enterprise-recover-bound-bind.py").read_text()
        with mock.patch.object(recovery.journal, "exact_main"), \
             mock.patch.object(recovery.cleanup, "source_contract"), \
             mock.patch.object(recovery.journal, "command", return_value=own), \
             mock.patch.object(recovery.journal, "kubectl_json",
                               return_value={"items": [{"metadata": {
                                   "name": old["name"], "uid": JOB_UID}}]}), \
             mock.patch.object(recovery.journal, "prove_committed_inputs"), \
             mock.patch.object(recovery.journal, "contract",
                               return_value=fixtures.ready_operator()["journalOperator"]), \
             mock.patch.object(recovery.journal, "prove_image_source"), \
             mock.patch.object(recovery.journal, "prove_claims"), \
             mock.patch.object(recovery, "prove_failed_source",
                               side_effect=[old, old, old, changed]), \
             mock.patch.object(recovery, "verify_without_cas", return_value={}), \
             mock.patch.object(recovery, "save_receipt", return_value=(JOB_UID, "301")) as receipt, \
             mock.patch.object(recovery, "prove_receipt", return_value=(JOB_UID, "301")), \
             mock.patch.object(recovery.cleanup, "delete_once") as delete:
            result = recovery.main([SHA, "12345", "1", JOB_UID, POD_UID,
                                    JOB_UID, "101", "ins_one"],
                                   {"EXPECTED_SHA": SHA, "GITHUB_RUN_ID": "67890",
                                    "GITHUB_RUN_ATTEMPT": "1"})
        self.assertEqual(result, 1)
        receipt.assert_called_once()
        delete.assert_not_called()

    def test_workflow_hashes_and_no_cas_callback_in_recovery(self):
        workflow = (ROOT / ".github/workflows/openclaw-enterprise-operations.yml").read_text()
        lane = workflow.split("\n  recover-bound-bind:\n", 1)[1]
        source = (ROOT / "scripts/ci/openclaw-enterprise-recover-bound-bind.py").read_text()
        for name in ("openclaw-enterprise-recover-bound-bind.py",
                     "openclaw-enterprise-recover-bound-bind.sh",
                     "openclaw-enterprise-cleanup-failed-bind.py"):
            path = ROOT / "scripts/ci" / name
            self.assertIn(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
                          f"scripts/ci/{name}", lane)
        self.assertNotIn("journal.bind_proof_and_patch(", source)
        self.assertNotIn("journal.dispatch(", source)
        self.assertNotIn('"patch", "secret"', source)
        self.assertIn("name: homelab-production", lane)
        self.assertIn("private diagnostics withheld", lane)
        self.assertNotIn('cat "$private_log"', lane)


if __name__ == "__main__":
    unittest.main()
