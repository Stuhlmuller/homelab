#!/usr/bin/env python3
"""Offline failure and restart checks for the dormant Enterprise Job runner."""

import base64
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import unittest.mock as mock


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/openclaw-enterprise-journal-operator.py"
spec = importlib.util.spec_from_file_location("oce_journal_operator", SOURCE)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
source_spec = importlib.util.spec_from_file_location(
    "oce_operator_source", ROOT / "scripts/openclaw-enterprise.py")
source = importlib.util.module_from_spec(source_spec)
source_spec.loader.exec_module(source)
SHA = "a" * 40
IMAGE_SHA = "c" * 40
UUID = "12345678-1234-1234-1234-123456789abc"
POD_UID = "87654321-4321-4321-4321-cba987654321"


def ready_operator():
    config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
    operator = config["journalOperator"]
    operator.update(enabled=True, journalClaimUid=UUID, journalVolumeUid=UUID,
                    bootstrapClaimUid=UUID, bootstrapVolumeUid=UUID,
                    journalPath="/var/lib/openclaw-enterprise/journal",
                    node="zimaboard-2", runAsUser=1000,
                    image="harbor.stinkyboi.com/homelab/"
                    "homelab-oce-operator@sha256:" + "b" * 64, imageSourceSha=IMAGE_SHA)
    return config


def projection(config):
    encoded = json.dumps(config, sort_keys=True)
    receipt = {"expectedSha": SHA, "imageSourceSha": IMAGE_SHA,
               "configSha256": hashlib.sha256(encoded.encode()).hexdigest()}
    return {"metadata": {"name": "oce-journal-config-" + SHA},
            "data": {"openclaw-enterprise.json": encoded,
                     "receipt.json": json.dumps(receipt)}}


def complete_job(job):
    actual = copy.deepcopy(job)
    actual["status"] = {"succeeded": 1, "conditions": [{"type": "Complete", "status": "True"}]}
    return actual


def running_job(job):
    actual = copy.deepcopy(job)
    actual["status"] = {"active": 1}
    return actual


def binding_objects():
    config = ready_operator()
    operator = config["journalOperator"]
    candidate = (ROOT / "clusters/homelab/apps/openclaw-enterprise/installation.yaml").read_bytes()
    digest = hashlib.sha256(candidate).hexdigest()
    secret = {"kind": "Secret", "type": "Opaque", "immutable": True,
              "metadata": {"name": "occ-installation-startup-" + digest[:32],
                           "namespace": "openclaw-system", "uid": UUID,
                           "resourceVersion": "100",
                           "labels": {"app.kubernetes.io/part-of": "openclaw-enterprise"},
                           "annotations": {"homelab.stuhlmuller.dev/installation-sha256":
                                           digest}},
              "data": {"installation.yaml": base64.b64encode(candidate).decode()}}
    baseline = {runner.BINDING_UID: UUID, runner.BINDING_VERSION: "100",
                runner.BINDING_DIGEST: digest, runner.BINDING_IMMUTABLE: "true"}
    job = runner.build_job("bind-installation", SHA, "12345", operator,
                           projection(config), baseline=baseline)
    actual = copy.deepcopy(job)
    actual["metadata"]["uid"] = UUID
    pod = {"metadata": {"name": job["metadata"]["name"] + "-abcde",
                        "namespace": "openclaw-system",
                        "uid": POD_UID,
                        "labels": copy.deepcopy(job["spec"]["template"]["metadata"]["labels"]),
                        "annotations": copy.deepcopy(baseline),
                        "ownerReferences": [{"controller": True, "kind": "Job",
                                             "name": job["metadata"]["name"], "uid": UUID}]},
           "spec": copy.deepcopy(job["spec"]["template"]["spec"]),
           "status": {"phase": "Running", "containerStatuses": [
               {"name": "operator", "state": {"running": {"startedAt": "now"}}}]}}
    pod["spec"]["nodeName"] = operator["node"]
    pod["metadata"]["labels"].update({
        "batch.kubernetes.io/job-name": job["metadata"]["name"],
        "batch.kubernetes.io/controller-uid": UUID})
    proof = {"schema": 1, "expectedSha": SHA, "jobName": job["metadata"]["name"],
             "installationId": "ins_one", "secretUid": UUID,
             "secretResourceVersion": "100",
             "alreadyBound": False, "issuedAt": int(time.time())}
    return operator, job, actual, pod, secret, proof


class JournalOperator(unittest.TestCase):
    def test_binding_job_reads_exact_bootstrap_claim_as_rootless_operator(self):
        operator, job, _, _, _, _ = binding_objects()
        self.assertEqual(runner.contract(ready_operator(), "bind-installation", SHA),
                         operator)
        container = job["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["command"], [
            "python3", "-I", "/opt/homelab/scripts/openclaw-enterprise-bind-installation.py"])
        self.assertIn("--job-name", container["args"])
        self.assertEqual(container["args"][-1], job["metadata"]["name"])
        self.assertEqual(container["securityContext"]["readOnlyRootFilesystem"], True)
        self.assertEqual(container["volumeMounts"][1]["readOnly"], True)
        self.assertEqual(job["spec"]["template"]["metadata"]["annotations"][
            runner.BINDING_UID], UUID)
        self.assertEqual(job["spec"]["template"]["metadata"]["annotations"][
            runner.BINDING_VERSION], "100")
        changed_job = copy.deepcopy(job)
        changed_job["spec"]["template"]["metadata"]["annotations"][
            runner.BINDING_VERSION] = "101"
        self.assertFalse(runner.job_identity(changed_job, job))
        with self.assertRaisesRegex(runner.Blocked, "baseline is incomplete"):
            runner.build_job("bind-installation", SHA, "12345", operator,
                             projection(ready_operator()))
        changed = ready_operator()
        changed["activationEnabled"] = True
        with self.assertRaisesRegex(runner.Blocked, "inactive"):
            runner.contract(changed, "bind-installation", SHA)

    def test_binding_baseline_proves_exact_immutable_reviewed_secret(self):
        _, _, _, _, secret, _ = binding_objects()
        with mock.patch.object(runner, "kubectl_json", return_value=secret) as read:
            baseline = runner.binding_secret_baseline("openclaw-system")
        self.assertEqual(baseline[runner.BINDING_UID], UUID)
        self.assertEqual(baseline[runner.BINDING_VERSION], "100")
        self.assertEqual(baseline[runner.BINDING_IMMUTABLE], "true")
        self.assertEqual(read.call_args.args[:5], (
            "-n", "openclaw-system", "get", "secret", secret["metadata"]["name"]))
        for change in ("uid", "version", "immutable", "candidate", "data", "name"):
            altered = copy.deepcopy(secret)
            if change == "uid":
                altered["metadata"]["uid"] = "wrong"
            elif change == "version":
                altered["metadata"]["resourceVersion"] = "0"
            elif change == "immutable":
                altered["immutable"] = False
            elif change == "candidate":
                altered["metadata"]["annotations"][
                    "homelab.stuhlmuller.dev/installation-sha256"] = "0" * 64
            elif change == "data":
                altered["data"]["installation.yaml"] = "Zm9yZWlnbg=="
            else:
                altered["metadata"]["name"] = "foreign"
            with self.subTest(change=change), \
                 mock.patch.object(runner, "kubectl_json", return_value=altered), \
                 self.assertRaisesRegex(runner.Blocked, "baseline"):
                runner.binding_secret_baseline("openclaw-system")

    def test_binding_dispatch_pins_secret_baseline_before_job_creation(self):
        operator, job, _, _, _, _ = binding_objects()
        baseline = job["spec"]["template"]["metadata"]["annotations"]
        events = []
        def read_baseline(namespace):
            self.assertEqual(namespace, "openclaw-system")
            events.append("baseline")
            return baseline
        def build(stage, expected, run_id, selected, projected, attempt, *, baseline):
            self.assertEqual((stage, expected, run_id, attempt),
                             ("bind-installation", SHA, "12345", "1"))
            self.assertEqual(selected, operator)
            self.assertEqual(baseline, job["spec"]["template"]["metadata"]["annotations"])
            events.append("build")
            return job
        def dispatch(_job, *, ready):
            self.assertEqual(_job, job)
            self.assertTrue(callable(ready))
            events.append("dispatch")
        with mock.patch.object(runner, "exact_main"), \
             mock.patch.object(runner, "prove_committed_inputs"), \
             mock.patch.object(runner, "contract", return_value=operator), \
             mock.patch.object(runner, "prove_image_source"), \
             mock.patch.object(runner, "prove_claims"), \
             mock.patch.object(runner, "config_projection", return_value=projection(
                 ready_operator())), \
             mock.patch.object(runner, "prove_or_create_projection"), \
             mock.patch.object(runner, "binding_secret_baseline", side_effect=read_baseline), \
             mock.patch.object(runner, "build_job", side_effect=build), \
             mock.patch.object(runner, "dispatch", side_effect=dispatch), \
             redirect_stdout(io.StringIO()):
            result = runner.main(["bind-installation"], {
                "EXPECTED_SHA": SHA, "GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1"})
        self.assertEqual(result, 0)
        self.assertEqual(events, ["baseline", "build", "dispatch"])

    def test_binding_ready_proof_rechecks_main_adjacent_to_named_cas_patch(self):
        operator, job, actual, pod, secret, proof = binding_objects()
        calls = []
        def command(argv, **_kwargs):
            if "logs" in argv:
                return "OCE_BIND_READY:" + json.dumps(proof) + "\n"
            calls.append(("patch", argv))
            return ""
        def main(_expected, _environ):
            calls.append(("main", None))
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [pod]}, secret, pod, running_job(actual)]), \
             mock.patch.object(runner, "command", side_effect=command), \
             mock.patch.object(runner, "exact_main", side_effect=main):
            runner.bind_proof_and_patch(actual, job, SHA, operator, {})
        self.assertEqual([kind for kind, _ in calls], ["main", "patch"])
        patch = calls[-1][1]
        self.assertEqual(patch[patch.index("secret") + 1], secret["metadata"]["name"])
        operations = json.loads(patch[patch.index("-p") + 1])
        self.assertEqual(operations[0]["value"], UUID)
        self.assertEqual(operations[1]["value"], "100")
        self.assertEqual(operations[2]["value"], "ins_one")

    def test_binding_rejects_foreign_pod_and_stale_receipt_before_patch(self):
        operator, job, actual, pod, secret, proof = binding_objects()
        for change in ("owner", "image", "volume", "init", "ephemeral", "host",
                       "security", "env_from", "bootstrap_mount", "baseline"):
            altered = copy.deepcopy(pod)
            if change == "owner":
                altered["metadata"]["ownerReferences"][0]["uid"] = POD_UID
            elif change == "image":
                altered["spec"]["containers"][0]["image"] = "foreign"
            elif change == "volume":
                altered["spec"]["volumes"].append({"name": "foreign", "emptyDir": {}})
            elif change == "init":
                altered["spec"]["initContainers"] = [{"name": "foreign"}]
            elif change == "ephemeral":
                altered["spec"]["ephemeralContainers"] = [{"name": "foreign"}]
            elif change == "host":
                altered["spec"]["hostNetwork"] = True
            elif change == "env_from":
                altered["spec"]["containers"][0]["envFrom"] = [
                    {"secretRef": {"name": "foreign"}}]
            elif change == "bootstrap_mount":
                altered["spec"]["containers"][0]["volumeMounts"][1]["readOnly"] = False
            elif change == "baseline":
                altered["metadata"]["annotations"][runner.BINDING_VERSION] = "101"
            else:
                altered["spec"]["securityContext"]["runAsUser"] = 0
            with self.subTest(change=change), \
                 mock.patch.object(runner, "kubectl_json", return_value={"items": [altered]}), \
                 mock.patch.object(runner, "command") as command:
                with self.assertRaisesRegex(runner.Blocked, "Pod source or owner"):
                    runner.bind_proof_and_patch(actual, job, SHA, operator, {})
                command.assert_not_called()
        proof["issuedAt"] -= 61
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [pod]}, secret, pod, running_job(actual)]), \
             mock.patch.object(runner, "command", return_value="OCE_BIND_READY:" +
                               json.dumps(proof)), \
             mock.patch.object(runner, "exact_main") as main:
            with self.assertRaisesRegex(runner.Blocked, "stale or invalid"):
                runner.bind_proof_and_patch(actual, job, SHA, operator, {})
            main.assert_not_called()

    def test_binding_rejects_secret_race_and_uncertain_patch_without_retry(self):
        operator, job, actual, pod, secret, proof = binding_objects()
        for field, value in (("uid", POD_UID), ("resourceVersion", "101")):
            altered = copy.deepcopy(secret)
            altered["metadata"][field] = value
            with self.subTest(field=field), \
                 mock.patch.object(runner, "kubectl_json", side_effect=[
                     {"items": [pod]}, altered]), \
                 mock.patch.object(runner, "command", return_value="OCE_BIND_READY:" +
                                   json.dumps(proof)), \
                 mock.patch.object(runner, "exact_main") as main:
                with self.assertRaisesRegex(runner.Blocked, "differs from binding proof"):
                    runner.bind_proof_and_patch(actual, job, SHA, operator, {})
                main.assert_not_called()
        commands = []
        def uncertain(argv, **_kwargs):
            if "logs" in argv:
                return "OCE_BIND_READY:" + json.dumps(proof)
            commands.append(argv)
            raise runner.Blocked("uncertain patch")
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [pod]}, secret, pod, running_job(actual), secret]), \
             mock.patch.object(runner, "command", side_effect=uncertain), \
             mock.patch.object(runner, "exact_main"), \
             self.assertRaisesRegex(runner.Blocked, "outcome is uncertain"):
            runner.bind_proof_and_patch(actual, job, SHA, operator, {})
        self.assertEqual(len(commands), 1)
        bound = copy.deepcopy(secret)
        bound["metadata"]["resourceVersion"] = "101"
        bound["metadata"]["annotations"]["openclaw.dev/installation-id"] = "ins_one"
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [pod]}, secret, pod, running_job(actual), bound]), \
             mock.patch.object(runner, "command", side_effect=uncertain), \
             mock.patch.object(runner, "exact_main"):
            runner.bind_proof_and_patch(actual, job, SHA, operator, {})
        self.assertEqual(len(commands), 2)

    def test_binding_rejects_secret_change_after_job_creation(self):
        operator, job, actual, pod, _, proof = binding_objects()
        proof["secretResourceVersion"] = "101"
        with mock.patch.object(runner, "kubectl_json", side_effect=[{"items": [pod]}]), \
             mock.patch.object(runner, "command", return_value="OCE_BIND_READY:" +
                               json.dumps(proof)), \
             mock.patch.object(runner, "exact_main") as main:
            with self.assertRaisesRegex(runner.Blocked, "after binding Job creation"):
                runner.bind_proof_and_patch(actual, job, SHA, operator, {})
            main.assert_not_called()

    def test_binding_rejects_stopped_job_before_current_main_guard(self):
        operator, job, actual, pod, secret, proof = binding_objects()
        stopped = complete_job(actual)
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [pod]}, secret, pod, stopped]), \
             mock.patch.object(runner, "command", return_value="OCE_BIND_READY:" +
                               json.dumps(proof)), \
             mock.patch.object(runner, "exact_main") as main:
            with self.assertRaisesRegex(runner.Blocked, "Job stopped"):
                runner.bind_proof_and_patch(actual, job, SHA, operator, {})
            main.assert_not_called()

    def test_binding_rejects_proof_that_expires_during_cluster_reads(self):
        operator, job, actual, pod, secret, proof = binding_objects()
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [pod]}, secret, pod, running_job(actual)]), \
             mock.patch.object(runner, "command", return_value="OCE_BIND_READY:" +
                               json.dumps(proof)), \
             mock.patch.object(runner.time, "time", side_effect=[
                 proof["issuedAt"] + 1, proof["issuedAt"] + 61]), \
             mock.patch.object(runner, "exact_main") as main:
            with self.assertRaisesRegex(runner.Blocked, "proof expired"):
                runner.bind_proof_and_patch(actual, job, SHA, operator, {})
            main.assert_not_called()

    def test_binding_dispatch_waits_for_runner_patch_before_job_completion(self):
        _, job, actual, _, _, _ = binding_objects()
        events = []
        def command(argv, **_kwargs):
            events.append("create" if "create" in argv else "wait")
            return ""
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": []}, actual, complete_job(job)]), \
             mock.patch.object(runner, "command", side_effect=command):
            runner.dispatch(job, ready=lambda seen, wanted: (
                self.assertEqual(seen, actual),
                self.assertEqual(wanted, job),
                events.append("patch")))
        self.assertEqual(events, ["create", "patch", "wait"])
    def test_disabled_contract_and_active_reconcile_fail_closed(self):
        config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        with self.assertRaisesRegex(runner.Blocked, "disabled"):
            runner.contract(config, "reconcile", SHA)
        config = ready_operator()
        self.assertEqual(runner.contract(config, "reconcile", SHA), config["journalOperator"])
        config["activationEnabled"] = True
        with self.assertRaisesRegex(runner.Blocked, "model credential"):
            runner.contract(config, "reconcile", SHA)
        self.assertEqual(runner.contract(config, "stop", SHA), config["journalOperator"])
        config["journalOperator"]["imageSourceSha"] = "invalid"
        with self.assertRaisesRegex(runner.Blocked, "pinned source"):
            runner.contract(config, "stop", SHA)

    def test_operator_uid_must_read_upstream_private_bootstrap_key(self):
        config = ready_operator()
        config["journalOperator"]["runAsUser"] = 10001
        with self.assertRaisesRegex(runner.Blocked, "bootstrap key owner"):
            runner.contract(config, "stop", SHA)
        config["journalOperator"]["runAsUser"] = 1000
        self.assertEqual(runner.contract(config, "stop", SHA),
                         config["journalOperator"])

    def test_bootstrap_claim_and_volume_uids_must_be_pinned(self):
        for field in ("bootstrapClaimUid", "bootstrapVolumeUid"):
            for value in (None, "", "wrong"):
                config = ready_operator()
                config["journalOperator"][field] = value
                with self.subTest(field=field, value=value), self.assertRaisesRegex(
                        runner.Blocked, "placement or pinned source"):
                    runner.contract(config, "stop", SHA)

    def test_prior_image_source_must_match_current_reconciler_inputs(self):
        operator = ready_operator()["journalOperator"]
        names = ("scripts/openclaw-enterprise.py",
                 "scripts/openclaw-enterprise-bind-installation.py",
                 "scripts/openclaw-enterprise-startup.py",
                 "clusters/homelab/apps/openclaw-enterprise/installation.yaml",
                 "clusters/homelab/apps/openclaw-enterprise/values.yaml")
        with mock.patch.object(runner, "command", side_effect=[""] + [
                (ROOT / name).read_text() for name in names]) as read:
            runner.prove_image_source(operator, SHA)
            self.assertEqual(read.call_args_list[0].args[0],
                             ["git", "merge-base", "--is-ancestor", IMAGE_SHA, SHA])
        with mock.patch.object(runner, "command", side_effect=["", "changed"]):
            with self.assertRaisesRegex(runner.Blocked, "differs"):
                runner.prove_image_source(operator, SHA)

    def test_current_inputs_must_match_exact_commit(self):
        names = ("scripts/config/openclaw-enterprise.json",
                 "scripts/openclaw-enterprise.py",
                 "clusters/homelab/apps/openclaw-enterprise/installation.yaml",
                 "clusters/homelab/apps/openclaw-enterprise/values.yaml")
        with mock.patch.object(runner, "command", side_effect=[
                (ROOT / name).read_text() for name in names]):
            runner.prove_committed_inputs(SHA)
        with mock.patch.object(runner, "command", return_value="different"):
            with self.assertRaisesRegex(runner.Blocked, "differs from checkout"):
                runner.prove_committed_inputs(SHA)

    def test_current_config_projection_is_immutable_and_source_bound(self):
        with mock.patch.object(runner, "CONFIG", ROOT / "scripts/config/openclaw-enterprise.json"):
            reviewed = json.loads(runner.CONFIG.read_text())
            projected = runner.config_projection(reviewed, SHA, reviewed["journalOperator"])
        self.assertTrue(projected["immutable"])
        self.assertEqual(projected["data"]["openclaw-enterprise.json"],
                         runner.CONFIG.read_text())
        receipt = json.loads(projected["data"]["receipt.json"])
        self.assertEqual(receipt["expectedSha"], SHA)
        self.assertEqual(receipt["configSha256"], hashlib.sha256(
            projected["data"]["openclaw-enterprise.json"].encode()).hexdigest())
        with mock.patch.object(runner, "kubectl_json", return_value={"items": [projected]}), \
                mock.patch.object(runner, "command") as write:
            runner.prove_or_create_projection(projected)
            write.assert_not_called()
        changed = copy.deepcopy(projected)
        changed["immutable"] = False
        with mock.patch.object(runner, "kubectl_json", return_value={"items": [changed]}):
            with self.assertRaisesRegex(runner.Blocked, "projection changed"):
                runner.prove_or_create_projection(projected)

    def test_job_has_direct_private_mount_and_no_automatic_token(self):
        operator = ready_operator()["journalOperator"]
        projected = projection(ready_operator())
        for stage, command in (("reconcile", "reconcile"), ("stop", "stop"),
                               ("verification", "verify")):
            job = runner.build_job(stage, SHA, "12345", operator, projected)
            self.assertEqual(job["spec"]["backoffLimit"], 0)
            self.assertNotIn("ttlSecondsAfterFinished", job["spec"])
            pod = job["spec"]["template"]["spec"]
            self.assertEqual(pod["nodeSelector"], {"kubernetes.io/hostname": "zimaboard-2"})
            self.assertNotIn("nodeName", pod)
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertEqual(pod["securityContext"]["runAsUser"], 1000)
            self.assertEqual(pod["securityContext"]["runAsGroup"], 1000)
            self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
            container = pod["containers"][0]
            self.assertEqual(container["args"][0], command)
            self.assertIn("--operator-source-sha", container["args"])
            self.assertIn("--reviewed-config-sha256", container["args"])
            self.assertNotIn("model-credential-file", " ".join(container["args"]))
            self.assertEqual(container["env"], [{"name": "KUBECONFIG",
                                                 "value": "/etc/oce-operator-kubeconfig/config"}])
            self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
            self.assertEqual(container["volumeMounts"][0]["mountPath"],
                             "/private/openclaw-enterprise")
            self.assertTrue(container["volumeMounts"][1]["readOnly"])
            self.assertTrue(all("subPath" not in mount for mount in container["volumeMounts"]))
            self.assertEqual(pod["volumes"][0]["persistentVolumeClaim"]["claimName"],
                             "occ-operator-journal")
            self.assertEqual(pod["volumes"][3]["configMap"]["name"],
                             "oce-journal-config-" + SHA)
            self.assertEqual(pod["volumes"][4]["projected"]["sources"][0]
                             ["serviceAccountToken"]["path"], "token")

    def test_retained_claim_identity_and_path_are_required(self):
        operator = ready_operator()["journalOperator"]
        pvc = {"metadata": {"uid": UUID}, "status": {"phase": "Bound"},
               "spec": {"volumeName": "occ-operator-journal",
                        "storageClassName": "openclaw-enterprise-journal-local",
                        "accessModes": ["ReadWriteOnce"]}}
        bootstrap = {"metadata": {"uid": UUID}, "status": {"phase": "Bound"},
                     "spec": {"volumeName": "occ-bootstrap-admin-password",
                              "storageClassName": "openclaw-enterprise-bootstrap-local",
                              "accessModes": ["ReadWriteOnce"]}}
        volume = {"metadata": {"uid": UUID}, "spec": {
            "claimRef": {"uid": UUID, "namespace": "openclaw-system",
                         "name": "occ-operator-journal"},
            "persistentVolumeReclaimPolicy": "Retain",
            "storageClassName": "openclaw-enterprise-journal-local",
            "hostPath": {"path": operator["journalPath"], "type": "Directory"},
            "nodeAffinity": {"required": {"nodeSelectorTerms": [{"matchExpressions": [{
                "key": "kubernetes.io/hostname", "operator": "In", "values": ["zimaboard-2"]}]}]}}}}
        bootstrap_volume = {"metadata": {"name": "occ-bootstrap-admin-password",
                                         "uid": UUID},
                            "spec": {"claimRef": {"uid": UUID, "namespace": "openclaw-system",
                                                  "name": "occ-bootstrap-admin-password"},
                                     "persistentVolumeReclaimPolicy": "Retain",
                                     "storageClassName": "openclaw-enterprise-bootstrap-local",
                                     "hostPath": {"path": "/var/lib/openclaw-enterprise/bootstrap",
                                                  "type": "Directory"},
                                     "nodeAffinity": copy.deepcopy(volume["spec"]["nodeAffinity"])}}
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                pvc, bootstrap, volume, bootstrap_volume]):
            runner.prove_claims(operator)
        for metadata in ({"name": "occ-bootstrap-admin-password"},
                         {"name": "occ-bootstrap-admin-password", "uid": "other"}):
            candidate = copy.deepcopy(bootstrap_volume)
            candidate["metadata"] = metadata
            with self.subTest(metadata=metadata), mock.patch.object(
                    runner, "kubectl_json", side_effect=[pvc, bootstrap, volume, candidate]):
                with self.assertRaisesRegex(runner.Blocked, "bootstrap volume"):
                    runner.prove_claims(operator)
        for metadata in ({}, {"uid": "other"}):
            candidate = copy.deepcopy(bootstrap)
            candidate["metadata"] = metadata
            with self.subTest(metadata=metadata), mock.patch.object(
                    runner, "kubectl_json", side_effect=[pvc, candidate, volume,
                                                             bootstrap_volume]):
                with self.assertRaisesRegex(runner.Blocked, "claim identity"):
                    runner.prove_claims(operator)
        volume["spec"]["persistentVolumeReclaimPolicy"] = "Delete"
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                pvc, bootstrap, volume, bootstrap_volume]):
            with self.assertRaisesRegex(runner.Blocked, "retained volume"):
                runner.prove_claims(operator)
        volume["spec"]["persistentVolumeReclaimPolicy"] = "Retain"
        volume["spec"]["hostPath"]["type"] = "DirectoryOrCreate"
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                pvc, bootstrap, volume, bootstrap_volume]):
            with self.assertRaisesRegex(runner.Blocked, "retained volume"):
                runner.prove_claims(operator)
        volume["spec"]["hostPath"]["type"] = "Directory"
        for key, changed in (("persistentVolumeReclaimPolicy", "Delete"),
                             ("storageClassName", "other"),
                             ("claimRef", {"uid": "other", "namespace": "openclaw-system",
                                           "name": "occ-bootstrap-admin-password"}),
                             ("nodeAffinity", {"required": {"nodeSelectorTerms": []}})):
            candidate = copy.deepcopy(bootstrap_volume)
            candidate["spec"][key] = changed
            with self.subTest(key=key), mock.patch.object(runner, "kubectl_json", side_effect=[
                    pvc, bootstrap, volume, candidate]):
                with self.assertRaisesRegex(runner.Blocked, "bootstrap volume"):
                    runner.prove_claims(operator)

    def test_restart_reuses_only_exact_completed_job(self):
        config = ready_operator()
        job = runner.build_job("verification", SHA, "12345", config["journalOperator"],
                               projection(config))
        complete = complete_job(job)
        self.assertEqual(complete["spec"]["template"]["spec"]["volumes"][4]
                         ["projected"]["defaultMode"], 420)
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [complete]}, complete]) as read, mock.patch.object(runner, "command") as write:
            runner.dispatch(job)
            self.assertEqual(read.call_count, 2)
            write.assert_not_called()
        changed = complete_job(job)
        changed["spec"]["template"]["spec"]["volumes"][4]["projected"]["defaultMode"] = 511
        self.assertFalse(runner.job_identity(changed, job))
        changed = complete_job(job)
        changed["spec"]["template"]["spec"]["containers"][0]["command"] = ["true"]
        with mock.patch.object(runner, "kubectl_json", return_value={"items": [changed]}):
            with self.assertRaisesRegex(runner.Blocked, "identity changed"):
                runner.dispatch(job)
        for location, value in (("resources", {"limits": {"memory": "8Gi"}}),
                                ("imagePullPolicy", "Always"),
                                ("terminationMessagePath", "/private/secret"),
                                ("terminationMessagePolicy", "FallbackToLogsOnError")):
            changed = complete_job(job)
            changed["spec"]["template"]["spec"]["containers"][0][location] = value
            self.assertFalse(runner.job_identity(changed, job), location)
        changed = complete_job(job)
        changed["spec"]["template"]["metadata"]["labels"][
            "homelab.stuhlmuller.dev/source-sha"] = "b" * 40
        self.assertFalse(runner.job_identity(changed, job))

    def test_rerun_attempt_creates_fresh_verification_job(self):
        config = ready_operator()
        first = runner.build_job("verification", SHA, "12345", config["journalOperator"],
                                 projection(config), "1")
        second = runner.build_job("verification", SHA, "12345", config["journalOperator"],
                                  projection(config), "2")
        self.assertNotEqual(first["metadata"]["name"], second["metadata"]["name"])
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [complete_job(first)]}, complete_job(second)]), \
                mock.patch.object(runner, "command", return_value="") as command:
            runner.dispatch(second)
            self.assertIn("create", command.call_args_list[0].args[0])
        with self.assertRaisesRegex(runner.Blocked, "attempt"):
            runner.build_job("verification", SHA, "12345", config["journalOperator"],
                             projection(config), "0")

    def test_missing_prior_job_label_cannot_hide_a_running_job(self):
        config = ready_operator()
        job = runner.build_job("reconcile", SHA, "12345", config["journalOperator"],
                               projection(config))
        prior = copy.deepcopy(job)
        prior["metadata"]["name"] = "oce-journal-reconcile-999-1"
        del prior["metadata"]["labels"]["app.kubernetes.io/name"]
        with mock.patch.object(runner, "kubectl_json", return_value={"items": [prior]}) as read, \
                mock.patch.object(runner, "command") as write:
            with self.assertRaisesRegex(runner.Blocked, "identity is ambiguous"):
                runner.dispatch(job)
            self.assertEqual(read.call_args.args, ("-n", "openclaw-system", "get",
                                                    "jobs", "-o=json"))
            write.assert_not_called()

    def test_running_exact_job_is_waited_without_a_second_create(self):
        config = ready_operator()
        job = runner.build_job("stop", SHA, "12345", config["journalOperator"],
                               projection(config))
        complete = complete_job(job)
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [copy.deepcopy(job)]}, complete]), \
                mock.patch.object(runner, "command", return_value="") as command:
            runner.dispatch(job)
            self.assertEqual(command.call_count, 1)
            self.assertIn("wait", command.call_args.args[0])
            self.assertNotIn("create", command.call_args.args[0])

    def test_new_job_is_created_once_then_read_back(self):
        config = ready_operator()
        job = runner.build_job("reconcile", SHA, "12345", config["journalOperator"],
                               projection(config))
        complete = complete_job(job)
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": []}, complete]), mock.patch.object(runner, "command",
                return_value="") as command:
            runner.dispatch(job)
            self.assertEqual(command.call_count, 2)
            create = command.call_args_list[0]
            self.assertIn("create", create.args[0])
            self.assertEqual(json.loads(create.kwargs["body"]), job)

    def test_uncertain_or_failed_previous_job_blocks_new_dispatch(self):
        config = ready_operator()
        job = runner.build_job("reconcile", SHA, "12345", config["journalOperator"],
                               projection(config))
        other = copy.deepcopy(job)
        other["metadata"]["name"] = "oce-journal-reconcile-999-1"
        with mock.patch.object(runner, "kubectl_json", return_value={"items": [other]}):
            with self.assertRaisesRegex(runner.Blocked, "still running or uncertain"):
                runner.dispatch(job)
        other["status"] = {"conditions": [{"type": "Failed", "status": "True"}]}
        with mock.patch.object(runner, "kubectl_json", return_value={"items": [other]}):
            with self.assertRaisesRegex(runner.Blocked, "prior operator Job failed"):
                runner.dispatch(job)

    def test_exact_main_rejects_stale_source(self):
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
               "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": SHA}
        with mock.patch.object(runner, "command", side_effect=[SHA, "b" * 40 + "\trefs/heads/main"]):
            with self.assertRaisesRegex(runner.Blocked, "no longer current"):
                runner.exact_main(SHA, env)

    def test_hosted_failure_never_reports_private_key_material(self):
        key = "private-bootstrap-key-fixture"
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(runner, "exact_main", side_effect=runner.Blocked(key)), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(runner.main(["stop"], {"EXPECTED_SHA": SHA}), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(),
                         "Enterprise operator blocked; private diagnostics withheld\n")
        self.assertNotIn(key, stderr.getvalue())

    def test_staged_resources_are_not_in_active_gitops_tree(self):
        operator = ROOT / "clusters/homelab/apps/openclaw-enterprise-operator"
        self.assertIn("journal.yaml", (operator / "kustomization.yaml").read_text())
        self.assertIn("reclaimPolicy: Retain", (operator / "journal.yaml").read_text())
        self.assertIn("Prune=false", (operator / "journal.yaml").read_text())
        self.assertIn("resources: [pods]\n    verbs: [list]",
                      (operator / "rbac.yaml").read_text())
        secret_name = next(line.split(":", 1)[1].strip() for line in
                           (ROOT / "clusters/homelab/apps/openclaw-enterprise/values.yaml")
                           .read_text().splitlines() if line.startswith("  secretName:"))
        self.assertIn(f"resourceNames: [{secret_name}]", (operator / "rbac.yaml").read_text())
        self.assertNotIn("openclaw-enterprise-operator",
                         (ROOT / "clusters/homelab/apps/openclaw-enterprise/kustomization.yaml")
                         .read_text())

    def test_in_cluster_context_requires_projected_token_and_ca(self):
        context = {"clusters": [{"cluster": {
            "server": source.IN_CLUSTER_KUBE_SERVER,
            "certificate-authority": "/var/run/oce-operator-api/ca.crt"}}],
            "users": [{"user": {"tokenFile": "/var/run/oce-operator-api/token"}}]}
        source.Kubernetes._trusted_context(context)
        for changed in (
                {"users": [{"user": {"tokenFile": "/other/token"}}]},
                {"clusters": [{"cluster": {"server": source.IN_CLUSTER_KUBE_SERVER,
                                               "insecure-skip-tls-verify": True}}]},
                {"clusters": [{"cluster": {"server": "https://evil.example"}}]}):
            candidate = {**context, **changed}
            with self.assertRaises(source.Blocked):
                source.Kubernetes._trusted_context(candidate)

    def test_stopped_runtime_requires_unfiltered_empty_tenant_pod_list(self):
        empty = {"kind": "PodList", "metadata": {"resourceVersion": "42"}, "items": []}
        def raw_response(command, **_kwargs):
            self.assertEqual(command, ["kubectl", "--request-timeout=15s", "get", "--raw",
                                       "/api/v1/namespaces/openclaw-agents/pods"])
            return subprocess.CompletedProcess(command, 0, json.dumps(empty), "")

        with mock.patch.object(source.subprocess, "run", side_effect=raw_response) as read:
            source.Kubernetes().tenant_pods_absent()
            read.assert_called_once()
        for changed in ({**empty, "items": [{"metadata": {"name": "unlabelled-writer"}}]},
                        {**empty, "metadata": {}}, {**empty, "items": None},
                        {**empty, "metadata": {"resourceVersion": "42", "continue": "next"}},
                        {**empty, "kind": "List", "metadata": {"resourceVersion": ""}}):
            with self.subTest(changed=changed), mock.patch.object(
                    source.Kubernetes, "_json", return_value=changed):
                with self.assertRaisesRegex(source.Blocked, "tenant still has Pods"):
                    source.Kubernetes().tenant_pods_absent()

    def test_verification_enters_journal_lock_before_readback(self):
        config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        events = []
        class Lock:
            def __init__(self, *_args, **kwargs):
                events.append("read-only" if kwargs["create_lock"] is False else "write")
            def __enter__(self):
                events.append("lock")
            def __exit__(self, *_args):
                events.append("unlock")
        with mock.patch.object(source, "ProtectedJournal", Lock), \
                mock.patch.object(source, "_verify_locked", side_effect=lambda *_: events.append("read")):
            source.verify(config, None, None)
        self.assertEqual(events, ["read-only", "lock", "read", "unlock"])

    def test_read_only_lock_refuses_missing_lock_without_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            journal = Path(directory).resolve() / "journal.json"
            journal.write_text("{}")
            journal.chmod(0o600)
            with self.assertRaisesRegex(source.Blocked, "lock is missing"):
                with source.ProtectedJournal(journal, SHA, "b" * 64,
                                             create_lock=False):
                    pass
            self.assertFalse(journal.with_name("journal.json.lock").exists())


if __name__ == "__main__":
    unittest.main()
