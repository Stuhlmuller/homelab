#!/usr/bin/env python3
"""Adversarial offline checks for the dormant failed-binding cleanup path."""

import copy
from contextlib import redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock
from urllib import error


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cleanup = load("oce_failed_bind_cleanup", "scripts/ci/openclaw-enterprise-cleanup-failed-bind.py")
fixtures = load("oce_binding_fixtures", "scripts/ci/openclaw-enterprise-journal-operator-test.py")
SHA = fixtures.SHA
JOB_UID = fixtures.UUID
POD_UID = fixtures.POD_UID


def failed_objects():
    operator, intended, actual, pod, secret, _ = fixtures.binding_objects()
    actual["metadata"]["resourceVersion"] = "202"
    actual["status"] = {"active": 0, "failed": 1,
                        "conditions": [{"type": "Failed", "status": "True"}]}
    pod["status"] = {"phase": "Failed", "containerStatuses": [{
        "name": "operator", "state": {"terminated": {"exitCode": 1}}}]}
    return operator, intended, actual, pod, secret


class Cleanup(unittest.TestCase):
    def test_workflow_pins_cleanup_sources_and_hides_private_output(self):
        workflow = (ROOT / ".github/workflows/openclaw-enterprise-operations.yml").read_text()
        lane = workflow.split("\n  cleanup-failed-bind:\n", 1)[1]
        self.assertIn("name: homelab-production", lane)
        self.assertIn("group: openclaw-enterprise-operations-production", lane)
        self.assertIn("fetch-depth: 0", lane)
        self.assertIn("timeout 15m nix develop --command bash "
                      "scripts/ci/openclaw-enterprise-cleanup-failed-bind.sh", lane)
        for name in ("openclaw-enterprise-cleanup-failed-bind.py",
                     "openclaw-enterprise-cleanup-failed-bind.sh",
                     "openclaw-enterprise-journal-operator.py"):
            path = ROOT / "scripts/ci" / name
            self.assertIn(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
                          f"scripts/ci/{name}", lane)
        self.assertIn("private diagnostics withheld", lane)
        self.assertNotIn('cat "$private_log"', lane)

    def test_historical_source_requires_ancestor_and_identical_relevant_bytes(self):
        seen = []
        def git(args, **_):
            seen.append(args)
            if args[1] == "merge-base":
                return ""
            _, _, ref = args
            sha, name = ref.split(":", 1)
            if name == "scripts/ci/openclaw-enterprise-cleanup-failed-bind.py":
                return (ROOT / name).read_text()
            data = (ROOT / name).read_text()
            return data if sha != SHA or name != cleanup.HISTORICAL_FILES[0] else "changed"
        with mock.patch.object(cleanup.journal, "command", side_effect=git), \
             self.assertRaisesRegex(cleanup.journal.Blocked, "source"):
            cleanup.source_contract("b" * 40, SHA)
        self.assertEqual(seen[0], ["git", "merge-base", "--is-ancestor", SHA,
                                   "b" * 40])
        with mock.patch.object(cleanup.journal, "command",
                               side_effect=cleanup.journal.Blocked("ancestor")), \
             self.assertRaises(cleanup.journal.Blocked):
            cleanup.source_contract("b" * 40, SHA)

    def test_terminal_no_ready_failure_is_source_bound_and_eligible(self):
        operator, intended, actual, pod, _ = failed_objects()
        config = fixtures.ready_operator()
        def read(*args):
            if args[3] == "jobs":
                return {"items": [actual]}
            if args[3] == "pods":
                return {"items": [pod]}
            self.fail(args)
        with mock.patch.object(cleanup.journal, "kubectl_json", side_effect=read), \
             mock.patch.object(cleanup.journal, "config_projection",
                               return_value=fixtures.projection(config)), \
             mock.patch.object(cleanup, "prove_secret") as secret_proof, \
             mock.patch.object(cleanup, "prove_retained_storage", return_value="storage"):
            observed = cleanup.prove_predelete(SHA, "12345", "1", JOB_UID, POD_UID,
                                                config, operator)
        self.assertEqual(observed, (intended["metadata"]["name"], "202",
                                    intended["spec"]["template"]["metadata"]["annotations"],
                                    "storage"))
        secret_proof.assert_called_once()

    def test_active_stale_or_foreign_binding_cannot_be_removed(self):
        operator, intended, actual, pod, _ = failed_objects()
        baseline = intended["spec"]["template"]["metadata"]["annotations"]
        for change in ("running", "no_failed_condition", "ready_expired_running",
                       "wrong_job_uid", "wrong_pod_uid", "foreign_pod", "no_pod",
                       "missing_witness", "changed_witness", "foreign_image",
                       "other_active_job", "pod_deleting", "job_deleting"):
            job = copy.deepcopy(actual)
            candidate = copy.deepcopy(pod)
            pods = [candidate]
            jobs = [job]
            if change in ("running", "ready_expired_running"):
                job["status"] = {"active": 1}
            elif change == "no_failed_condition":
                job["status"]["conditions"] = []
            elif change == "wrong_job_uid":
                job["metadata"]["uid"] = POD_UID
            elif change == "wrong_pod_uid":
                candidate["metadata"]["uid"] = JOB_UID
            elif change == "foreign_pod":
                pods.append(copy.deepcopy(candidate))
                pods[-1]["metadata"]["uid"] = JOB_UID
            elif change == "no_pod":
                pods.clear()
            elif change == "missing_witness":
                job["spec"]["template"]["metadata"]["annotations"] = {}
            elif change == "changed_witness":
                job["spec"]["template"]["metadata"]["annotations"][
                    cleanup.journal.BINDING_VERSION] = "203"
            elif change == "foreign_image":
                candidate["spec"]["containers"][0]["image"] = "foreign"
            elif change == "other_active_job":
                foreign = copy.deepcopy(job)
                foreign["metadata"]["name"] = "oce-journal-bind-installation-456-1"
                foreign["status"] = {"active": 1}
                jobs.append(foreign)
            elif change == "pod_deleting":
                candidate["metadata"]["deletionTimestamp"] = "now"
            elif change == "job_deleting":
                job["metadata"]["deletionTimestamp"] = "now"
            def read(*args):
                return {"items": jobs if args[2] == "jobs" else pods}
            with self.subTest(change=change), \
                 mock.patch.object(cleanup.journal, "kubectl_json", side_effect=read), \
                 mock.patch.object(cleanup.journal, "config_projection",
                                   return_value=fixtures.projection(fixtures.ready_operator())), \
                 mock.patch.object(cleanup, "prove_secret"), \
                 mock.patch.object(cleanup, "prove_retained_storage", return_value="storage"), \
                 self.assertRaises(cleanup.journal.Blocked):
                cleanup.prove_predelete(SHA, "12345", "1", JOB_UID, POD_UID,
                                        fixtures.ready_operator(), operator)
        self.assertEqual(baseline[cleanup.journal.BINDING_VERSION], "100")

    def test_secret_must_remain_unbound_at_pre_job_resource_version(self):
        operator, intended, _, _, original = failed_objects()
        baseline = intended["spec"]["template"]["metadata"]["annotations"]
        for change in ("bound", "resource_version", "uid", "data", "deleting"):
            secret = copy.deepcopy(original)
            if change == "bound":
                secret["metadata"]["annotations"][cleanup.INSTALLATION_ID] = "ins_bound"
            elif change == "resource_version":
                secret["metadata"]["resourceVersion"] = "101"
            elif change == "uid":
                secret["metadata"]["uid"] = POD_UID
            elif change == "data":
                secret["data"]["installation.yaml"] = "Zm9yZWlnbg=="
            else:
                secret["metadata"]["deletionTimestamp"] = "now"
            with self.subTest(change=change), \
                 mock.patch.object(cleanup.journal, "binding_secret_baseline",
                                   return_value=baseline), \
                 mock.patch.object(cleanup.journal, "kubectl_json", return_value=secret), \
                 self.assertRaises(cleanup.journal.Blocked):
                cleanup.prove_secret(operator, baseline)

    def test_storage_retention_checks_owner_and_detects_spec_drift(self):
        operator, _, _, _, _ = failed_objects()
        journal_pvc = {"metadata": {"uid": operator["journalClaimUid"]},
                       "spec": {"volumeName": operator["journalClaim"]},
                       "status": {"phase": "Bound"}}
        bootstrap_pvc = {"metadata": {"uid": operator["bootstrapClaimUid"]},
                         "spec": {"volumeName": "bootstrap-volume"},
                         "status": {"phase": "Bound"}}
        journal_pv = {"metadata": {"uid": operator["journalVolumeUid"]},
                      "spec": {"persistentVolumeReclaimPolicy": "Retain"}}
        bootstrap_pv = {"metadata": {"uid": operator["bootstrapVolumeUid"]},
                        "spec": {"persistentVolumeReclaimPolicy": "Retain"}}
        objects = {("pvc", operator["journalClaim"]): journal_pvc,
                   ("pvc", operator["bootstrapClaim"]): bootstrap_pvc,
                   ("pv", operator["journalClaim"]): journal_pv,
                   ("pv", "bootstrap-volume"): bootstrap_pv}
        def read(*args):
            kind, name = (args[3], args[4]) if args[0] == "-n" else (args[1], args[2])
            return objects[(kind, name)]
        with mock.patch.object(cleanup.journal, "prove_claims"), \
             mock.patch.object(cleanup.journal, "kubectl_json", side_effect=read):
            initial = cleanup.prove_retained_storage(operator)
            bootstrap_pv["spec"]["hostPath"] = {"path": "/foreign"}
            self.assertNotEqual(cleanup.prove_retained_storage(operator), initial)
            bootstrap_pv["metadata"]["ownerReferences"] = [{"uid": JOB_UID}]
            with self.assertRaises(cleanup.journal.Blocked):
                cleanup.prove_retained_storage(operator)

    def test_one_rest_delete_uses_both_preconditions_and_fresh_main(self):
        events = []
        class Proxy:
            stdout = io.StringIO("Starting to serve on 127.0.0.1:43210\n")
            def poll(self):
                return None
            def terminate(self):
                raise ProcessLookupError("proxy exited after write")
            def wait(self, timeout):
                return 0
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
        class Opener:
            def open(self, action, timeout):
                events.append(("delete", action, timeout))
                return Response()
        with mock.patch.object(cleanup.subprocess, "Popen", return_value=Proxy()), \
             mock.patch.object(cleanup.select, "select", return_value=([Proxy.stdout], [], [])), \
             mock.patch.object(cleanup.request, "build_opener", return_value=Opener()), \
             mock.patch.object(cleanup.journal, "exact_main",
                               side_effect=lambda *_: events.append(("main",))):
            accepted = cleanup.delete_once("openclaw-system", "oce-journal-bind-installation-12345-1",
                                           JOB_UID, "202", SHA, {})
        self.assertTrue(accepted)
        self.assertEqual([item[0] for item in events], ["main", "delete"])
        options = json.loads(events[1][1].data)
        self.assertEqual(options["preconditions"],
                         {"uid": JOB_UID, "resourceVersion": "202"})
        self.assertEqual(options["propagationPolicy"], "Foreground")
        self.assertEqual(events[1][2], 15)

    def test_lost_delete_response_is_one_write_only(self):
        calls = []
        class Proxy:
            stdout = io.StringIO("Starting to serve on 127.0.0.1:43210\n")
            def poll(self):
                return None
            def terminate(self):
                raise ProcessLookupError("proxy exited after lost response")
            def wait(self, timeout):
                return 0
        class Opener:
            def open(self, action, timeout):
                calls.append(action)
                raise error.URLError("lost response")
        with mock.patch.object(cleanup.subprocess, "Popen", return_value=Proxy()), \
             mock.patch.object(cleanup.select, "select", return_value=([Proxy.stdout], [], [])), \
             mock.patch.object(cleanup.request, "build_opener", return_value=Opener()), \
             mock.patch.object(cleanup.journal, "exact_main"):
            accepted = cleanup.delete_once("openclaw-system", "oce-journal-bind-installation-12345-1",
                                           JOB_UID, "202", SHA, {})
        self.assertFalse(accepted)
        self.assertEqual(len(calls), 1)

    def test_unknown_delete_response_requires_readback_not_retry(self):
        operator, intended, actual, pod, _ = failed_objects()
        name = intended["metadata"]["name"]
        deleting = copy.deepcopy(actual)
        deleting["metadata"]["deletionTimestamp"] = "now"
        rounds = iter([(deleting, pod), (None, None)])
        current = [None, None]
        def read(*args):
            if args[3] == "jobs":
                current[:] = next(rounds)
                return {"items": [current[0]] if current[0] else []}
            return {"items": [current[1]] if current[1] else []}
        with mock.patch.object(cleanup.journal, "kubectl_json", side_effect=read), \
             mock.patch.object(cleanup, "prove_secret"), \
             mock.patch.object(cleanup, "prove_retained_storage", return_value="storage"), \
             mock.patch.object(cleanup.time, "sleep"):
            cleanup.observe_deletion(operator["namespace"], name, JOB_UID, POD_UID,
                                     operator, {}, "storage", uncertain=True)
        with mock.patch.object(cleanup.journal, "kubectl_json",
                               side_effect=[{"items": [actual]}, {"items": [pod]}]), \
             mock.patch.object(cleanup, "prove_secret"), \
             mock.patch.object(cleanup, "prove_retained_storage", return_value="storage"), \
             self.assertRaisesRegex(cleanup.journal.Blocked, "uncertain"):
            cleanup.observe_deletion(operator["namespace"], name, JOB_UID, POD_UID,
                                     operator, {}, "storage", uncertain=True)

    def test_changed_second_snapshot_blocks_delete_and_public_output_is_generic(self):
        operator, _, _, _, _ = failed_objects()
        cleanup_shas = (SHA, "12345", "1", JOB_UID, POD_UID)
        err = io.StringIO()
        with mock.patch.object(cleanup.journal, "exact_main"), \
             mock.patch.object(cleanup, "source_contract"), \
             mock.patch.object(cleanup.journal, "prove_committed_inputs"), \
             mock.patch.object(cleanup.journal, "contract", return_value=operator), \
             mock.patch.object(cleanup.journal, "prove_image_source"), \
             mock.patch.object(cleanup, "prove_predelete", side_effect=[
                 ("job", "202", {}, "storage"), ("job", "203", {}, "storage")]), \
             mock.patch.object(cleanup, "delete_once") as write, \
             redirect_stderr(err):
            result = cleanup.main(cleanup_shas, {"EXPECTED_SHA": SHA})
        self.assertEqual(result, 1)
        write.assert_not_called()
        self.assertEqual(err.getvalue(),
                         "Failed binding cleanup blocked; private diagnostics withheld\n")


if __name__ == "__main__":
    unittest.main()
