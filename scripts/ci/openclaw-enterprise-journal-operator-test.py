#!/usr/bin/env python3
"""Offline failure and restart checks for the dormant Enterprise Job runner."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


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


def ready_operator():
    config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
    operator = config["journalOperator"]
    operator.update(enabled=True, journalClaimUid=UUID, journalVolumeUid=UUID,
                    bootstrapClaimUid=UUID, journalPath="/var/lib/openclaw-enterprise/journal",
                    node="zimaboard-2", image="harbor.stinkyboi.com/homelab/"
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


class JournalOperator(unittest.TestCase):
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

    def test_prior_image_source_must_match_current_reconciler_inputs(self):
        operator = ready_operator()["journalOperator"]
        names = ("scripts/openclaw-enterprise.py",
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
            self.assertEqual(pod["securityContext"]["runAsUser"], 10001)
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
        bootstrap_volume = {"metadata": {"name": "occ-bootstrap-admin-password"},
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
        with mock.patch.object(runner, "kubectl_json", side_effect=[
                {"items": [complete]}, complete]) as read, mock.patch.object(runner, "command") as write:
            runner.dispatch(job)
            self.assertEqual(read.call_count, 2)
            write.assert_not_called()
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

    def test_missing_prior_job_label_cannot_hide_a_running_job(self):
        config = ready_operator()
        job = runner.build_job("reconcile", SHA, "12345", config["journalOperator"],
                               projection(config))
        prior = copy.deepcopy(job)
        prior["metadata"]["name"] = "oce-journal-reconcile-999"
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
        other["metadata"]["name"] = "oce-journal-reconcile-999"
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

    def test_staged_resources_are_not_in_active_gitops_tree(self):
        operator = ROOT / "clusters/homelab/apps/openclaw-enterprise-operator"
        self.assertIn("journal.yaml", (operator / "kustomization.yaml").read_text())
        self.assertIn("reclaimPolicy: Retain", (operator / "journal.yaml").read_text())
        self.assertIn("Prune=false", (operator / "journal.yaml").read_text())
        self.assertIn("occ-installation-startup-980de11bbc688a33741a19c9093f613",
                      (operator / "rbac.yaml").read_text())
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
