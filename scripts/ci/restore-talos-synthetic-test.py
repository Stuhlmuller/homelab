#!/usr/bin/env python3
"""Offline admission, ownership, image identity and capacity regressions; no API access."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

SPEC = importlib.util.spec_from_file_location("talos", Path(__file__).with_name("restore-talos-synthetic.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
PIN = {"image": "registry.example/restore@sha256:" + "a" * 64}
NAME = M.NAME_PREFIX + "b" * 32
JOB_UID, CM_UID, POD_UID, OTHER_UID = (str(uuid.UUID(int=value)) for value in range(1, 5))
FILES = {"probe": b"synthetic probe", "fault": b"synthetic fault", "talos.sh": b"synthetic shell"}


def admitted_job(value):
    value["metadata"]["uid"] = JOB_UID
    value["spec"]["template"]["metadata"]["labels"].update({
        "controller-uid": JOB_UID, "job-name": NAME,
        "batch.kubernetes.io/controller-uid": JOB_UID, "batch.kubernetes.io/job-name": NAME})
    return value


def job():
    return admitted_job(M.manifest(PIN, NAME))


def pod(value=None):
    value = value or job()
    return {"metadata": {"name": NAME + "-pod", "namespace": M.PROFILE["namespace"],
                         **deepcopy(value["spec"]["template"]["metadata"]),
                         "uid": POD_UID, "resourceVersion": "123", "finalizers": ["batch.kubernetes.io/job-tracking"],
                         "ownerReferences": [
                             {"apiVersion": "batch/v1", "kind": "Job", "name": NAME, "uid": JOB_UID,
                              "controller": True, "blockOwnerDeletion": True}]},
            "spec": deepcopy(value["spec"]["template"]["spec"])}


def capacity():
    value = {"metadata": {"name": M.PROFILE["node"], "uid": OTHER_UID,
                           "labels": {"kubernetes.io/hostname": M.PROFILE["node"],
                                      "kubernetes.io/arch": "amd64", "kubernetes.io/os": "linux"}},
             "status": {"nodeInfo": {**M.PROFILE["nodeInfo"], "bootID": OTHER_UID},
                        "conditions": [{"type": key, "status": status} for key, status in
                                       (("Ready", "True"), ("MemoryPressure", "False"),
                                        ("DiskPressure", "False"), ("PIDPressure", "False"))],
                        "allocatable": {"cpu": "2", "memory": "4Gi", "ephemeral-storage": "8Gi"}}}
    description = "Allocated resources:\n  Resource Requests Limits\n cpu 100m (5%) 1 (50%)\n memory 1Gi (25%) 2Gi (50%)\n ephemeral-storage 1Gi (12%) 3Gi (37%)\nEvents:\n"
    stats = {"node": {"nodeName": M.PROFILE["node"], "fs": {
        "time": datetime.now(timezone.utc).isoformat(), "availableBytes": 4 * 1024 ** 3}}}
    return value, description, stats


class Client:
    def __init__(self, mutate_job=None, mutate_cm=None, mode=None):
        self.job = self.cm = self.pod = None
        self.mutate_job, self.mutate_cm, self.mode = mutate_job, mutate_cm, mode
        self.deleted, self.created = [], []
        self.released = False

    def get(self, kind, name):
        if kind == "namespace":
            return {"metadata": {"name": M.PROFILE["namespace"]}}
        return deepcopy({"job": self.job, "configmap": self.cm, "pod": self.pod}[kind])

    def capacity(self):
        values = capacity()
        return values[0], M.validate_capacity(*values)

    def create(self, obj):
        self.created.append(obj["kind"])
        value = deepcopy(obj)
        value["metadata"]["uid"] = JOB_UID if obj["kind"] == "Job" else CM_UID
        if obj["kind"] == "Job":
            admitted_job(value)
            if self.mutate_job:
                self.mutate_job(value)
            self.job = value
            self.pod = pod(value)
        else:
            if self.mutate_cm:
                self.mutate_cm(value)
            self.cm = value
        if self.mode == "uncertain-job" and obj["kind"] == "Job":
            raise subprocess.TimeoutExpired("synthetic create", 1)
        if self.mode == "uncertain-cm" and obj["kind"] == "ConfigMap":
            raise subprocess.TimeoutExpired("synthetic create", 1)
        if self.mode == "uncertain-cm-missing" and obj["kind"] == "ConfigMap":
            self.cm = None
            raise subprocess.TimeoutExpired("synthetic create", 1)
        return deepcopy(value)

    def pods(self, job_uid):
        values = [deepcopy(self.pod)] if self.pod else []
        if self.mode == "extra-pod" and values:
            values.append(deepcopy(values[0]))
        if self.mode == "metadata-gated" and values:
            values[0]["metadata"]["labels"]["istio.io/dataplane-mode"] = "ambient"
        return values

    def release(self, value):
        if self.mode == "stale-release":
            raise RuntimeError("stale resourceVersion")
        self.released = True
        self.pod["spec"].pop("schedulingGates")
        self.pod["spec"]["nodeName"] = M.PROFILE["node"]
        self.pod["status"] = {"containerStatuses": [{"name": "synthetic", "imageID": PIN["image"],
                              "restartCount": 0, "state": {"terminated": {"exitCode": 0}}}]}
        self.job["status"] = {"succeeded": 1, "conditions": [{"type": "Complete", "status": "True"}]}
        if self.mode == "mutated-release":
            self.pod["spec"]["containers"][0]["command"] = ["/bin/true"]
        if self.mode == "replaced-pod":
            self.pod["metadata"]["uid"] = OTHER_UID
        if self.mode == "config-imageID":
            self.pod["status"]["containerStatuses"][0]["imageID"] = "sha256:" + "c" * 64
        if self.mode == "metadata-release":
            self.pod["metadata"]["labels"]["istio.io/dataplane-mode"] = "ambient"

    def delete_uid(self, kind, name, uid):
        self.deleted.append((kind, uid))
        if kind == "jobs":
            self.job = None
            self.pod = None
        else:
            self.cm = None

    def call(self, *args):
        profile = {"uid": 65534, "gid": 65534, "capabilities": 0, "no_new_privs": 1, "seccomp": 2, "filters": 2}
        return "RESTORE_PROFILE " + json.dumps(profile) + "\nRESTORE_TALOS_SYNTHETIC_PASSED\n"


class Tests(unittest.TestCase):
    def execute(self, client):
        with patch.object(M.uuid, "uuid4", return_value=uuid.UUID(hex="b" * 32)), patch.object(M, "verify_main"):
            return M.execute(PIN, FILES, "d" * 40, client)

    def test_missing_pin_precedes_commands_import_and_network(self):
        with patch.object(M, "PIN", Path("/missing-synthetic-publication-pin")), patch.object(M, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "pin is absent"):
                M.contract("d" * 40)
            run.assert_not_called()

    def test_workflow_supplies_locked_registry_tool_for_every_pull(self):
        workflow = (M.ROOT / ".github/workflows/restore-talos-synthetic.yml").read_text()
        commands = workflow.split("run: >-")[1:]
        self.assertEqual(len(commands), 3)
        for command in commands:
            self.assertIn("nix develop --command nix shell --inputs-from . nixpkgs#skopeo --command", command)
            self.assertIn("python3 scripts/ci/restore-talos-synthetic.py", command)

    def test_credentials_never_use_inherited_config_or_symlinks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(M.Path, "home", return_value=Path(directory)), \
                patch.dict(os.environ, {"OCTELIUM_AUTH_TOKEN": "synthetic-test-only"}, clear=True):
            target = Path(directory) / ".kube/config"
            self.assertEqual(M.credential_path(), target)
            with patch.dict(os.environ, {"KUBECONFIG": "/unowned/config"}):
                with self.assertRaisesRegex(RuntimeError, "inherited KUBECONFIG"):
                    M.credential_path()
            target.parent.mkdir()
            target.write_text("synthetic existing config")
            with self.assertRaises(RuntimeError):
                M.credential_path()
            target.unlink()
            target.symlink_to(Path(directory) / "missing")
            with self.assertRaises(RuntimeError):
                M.credential_path()

    def test_mutated_job_is_never_a_trusted_pod_baseline(self):
        for key, value in (("command", ["/bin/sh", "-c", "echo unfiltered"]), ("image", "other/image"),
                           ("volumeMounts", [{"name": "host", "mountPath": "/host"}])):
            with self.subTest(key=key):
                changed = job()
                changed["spec"]["template"]["spec"]["containers"][0][key] = value
                with self.assertRaises(RuntimeError):
                    M.validate_job(changed, PIN, NAME)
                with self.assertRaises(RuntimeError):
                    M.validate_pod(pod(changed), PIN, NAME, JOB_UID, gated=True)

    def test_unsupported_job_controllers_and_bounds_fail(self):
        for key, value in (("managedBy", "example.invalid/controller"), ("suspend", True),
                           ("parallelism", 2), ("backoffLimit", 1), ("activeDeadlineSeconds", 99999)):
            with self.subTest(key=key):
                changed = job()
                changed["spec"][key] = value
                with self.assertRaises(RuntimeError):
                    M.validate_job(changed, PIN, NAME)

    def test_extra_pod_execution_and_placement_configuration_fails(self):
        for key, value in (("hostNetwork", True), ("nodeName", M.PROFILE["node"]),
                           ("initContainers", [{"name": "injected"}]), ("ephemeralContainers", [{}]),
                           ("imagePullSecrets", [{}]), ("serviceAccountName", "privileged"),
                           ("tolerations", []), ("priority", 100), ("runtimeClassName", "different")):
            with self.subTest(key=key):
                changed = pod()
                changed["spec"][key] = value
                with self.assertRaises(RuntimeError):
                    M.validate_pod(changed, PIN, NAME, JOB_UID, gated=True)

    def test_admitted_policy_metadata_must_match_local_contract(self):
        for mutation in (lambda metadata: metadata["labels"].update({"istio.io/dataplane-mode": "ambient"}),
                         lambda metadata: metadata["annotations"].update({"sidecar.istio.io/inject": "true"}),
                         lambda metadata: metadata["annotations"].update({"unexpected.example/config": "different"}),
                         lambda metadata: metadata["labels"].update({"controller-uid": OTHER_UID})):
            changed = job()
            mutation(changed["spec"]["template"]["metadata"])
            with self.assertRaises(RuntimeError):
                M.validate_job(changed, PIN, NAME)
            with self.assertRaises(RuntimeError):
                M.validate_pod(pod(changed), PIN, NAME, JOB_UID, gated=True)
        changed = pod()
        changed["metadata"]["finalizers"] = ["unexpected.example/retain"]
        with self.assertRaises(RuntimeError):
            M.validate_pod(changed, PIN, NAME, JOB_UID, gated=True)

    def test_exact_controller_metadata_is_accepted_before_and_after_release(self):
        value = job()
        generated = {"controller-uid": JOB_UID, "job-name": NAME,
                     "batch.kubernetes.io/controller-uid": JOB_UID, "batch.kubernetes.io/job-name": NAME}
        value["spec"]["template"]["metadata"]["labels"].update(generated)
        value["spec"]["template"]["metadata"]["creationTimestamp"] = None
        M.validate_job(value, PIN, NAME)
        current = pod(value)
        current["metadata"].update(generateName=NAME + "-", finalizers=["batch.kubernetes.io/job-tracking"])
        M.validate_pod(current, PIN, NAME, JOB_UID, gated=True)
        current["spec"].pop("schedulingGates")
        current["spec"]["nodeName"] = M.PROFILE["node"]
        current["metadata"].pop("finalizers")
        M.validate_pod(current, PIN, NAME, JOB_UID, gated=False)

    def test_imageID_requires_exact_repository_manifest_reference(self):
        value = pod()
        value["spec"]["nodeName"] = M.PROFILE["node"]
        value["spec"].pop("schedulingGates")
        value["status"] = {"containerStatuses": [{"name": "synthetic", "imageID": PIN["image"], "restartCount": 0}]}
        M.validate_pod(value, PIN, NAME, JOB_UID, gated=False, image_status=True)
        for image in ("", "sha256:" + "a" * 64, "docker-pullable://" + PIN["image"],
                      PIN["image"].replace("registry.example", "alias.example")):
            with self.subTest(image=image):
                value["status"]["containerStatuses"][0]["imageID"] = image
                with self.assertRaises(RuntimeError):
                    M.validate_pod(value, PIN, NAME, JOB_UID, gated=False, image_status=True)

    def test_gated_pod_must_have_no_startup_evidence(self):
        value = pod()
        value["status"] = {"phase": "Running", "containerStatuses": [{"name": "synthetic"}]}
        with self.assertRaisesRegex(RuntimeError, "startup evidence"):
            M.validate_pod(value, PIN, NAME, JOB_UID, gated=True)

    def test_success_and_uncertain_response_use_one_owned_create(self):
        for mode in (None, "uncertain-job", "uncertain-cm"):
            with self.subTest(mode=mode):
                client = Client(mode=mode)
                receipt = self.execute(client)
                self.assertEqual(receipt["imageID"], PIN["image"])
                self.assertEqual(client.created, ["Job", "ConfigMap"])
                self.assertEqual(client.deleted, [("jobs", JOB_UID), ("configmaps", CM_UID)])

    def test_successful_create_rejected_job_is_cleaned_by_returned_UID(self):
        def mutate(value):
            value["spec"]["template"]["spec"]["containers"][0]["command"] = ["/bin/true"]
        client = Client(mutate_job=mutate)
        with self.assertRaisesRegex(RuntimeError, "container profile"):
            self.execute(client)
        self.assertEqual(client.deleted, [("jobs", JOB_UID)])
        self.assertFalse(client.released)

    def test_successful_create_rejected_config_is_cleaned_by_returned_UID(self):
        for field in ("binaryData", "owner"):
            def mutate(value):
                if field == "binaryData":
                    value["binaryData"]["probe"] = "changed"
                else:
                    value["metadata"]["ownerReferences"][0]["uid"] = OTHER_UID
            client = Client(mutate_cm=mutate)
            with self.assertRaises(RuntimeError):
                self.execute(client)
            self.assertEqual(client.deleted, [("jobs", JOB_UID), ("configmaps", CM_UID)])
            self.assertFalse(client.released)

    def test_lifecycle_drift_fails_and_cleans_owned_resources(self):
        for mode in ("stale-release", "mutated-release", "metadata-gated", "metadata-release", "extra-pod", "replaced-pod", "config-imageID"):
            with self.subTest(mode=mode):
                client = Client(mode=mode)
                with self.assertRaises(RuntimeError):
                    self.execute(client)
                self.assertEqual(client.deleted, [("jobs", JOB_UID), ("configmaps", CM_UID)])
                if mode == "metadata-gated":
                    self.assertFalse(client.released)

    def test_uncertain_create_404_does_not_claim_cleanup(self):
        client = Client()
        with self.assertRaisesRegex(RuntimeError, "cleanup remains unverified"):
            M.cleanup(client, PIN, NAME, None, None, True)
        self.assertEqual(client.deleted, [])

    def test_uncertain_config_create_404_does_not_claim_cleanup(self):
        client = Client(mode="uncertain-cm-missing")
        with self.assertRaisesRegex(RuntimeError, "ConfigMap create response was uncertain; cleanup remains unverified"):
            self.execute(client)
        self.assertEqual(client.created, ["Job", "ConfigMap"])
        self.assertEqual(client.deleted, [("jobs", JOB_UID)])

    def test_replacement_UID_is_not_deleted(self):
        client = Client()
        client.job = job()
        client.job["metadata"]["uid"] = OTHER_UID
        with self.assertRaisesRegex(RuntimeError, "replaced"):
            M.cleanup(client, PIN, NAME, JOB_UID, None, False)
        self.assertEqual(client.deleted, [])

    def test_job_absence_does_not_prove_dependents_gone(self):
        client = Client()
        client.pod = pod()
        with patch.object(M.time, "monotonic", side_effect=[0, 1, 121]), patch.object(M.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "dependents remain"):
                M.cleanup(client, PIN, NAME, JOB_UID, None, False, NAME + "-pod", POD_UID)

    def test_capacity_missing_stale_and_insufficient_evidence_fails(self):
        values = capacity()
        self.assertEqual(M.validate_capacity(*values)["requestHeadroom"]["cpu"], "1.900")
        for mutation in (lambda n, s: n["status"]["nodeInfo"].pop("bootID"),
                         lambda n, s: n["status"]["allocatable"].update(memory="1Gi"),
                         lambda n, s: s["node"]["fs"].update(time="2000-01-01T00:00:00Z"),
                         lambda n, s: s["node"]["fs"].update(availableBytes=1),
                         lambda n, s: n["status"]["nodeInfo"].update(osImage="Other Linux")):
            n, d, s = capacity()
            mutation(n, s)
            with self.assertRaises(RuntimeError):
                M.validate_capacity(n, d, s)
        with self.assertRaises(RuntimeError):
            M.validate_capacity(values[0], "unavailable projection", values[2])

    def test_gate_patch_retains_uid_resourceVersion_and_gate_tests(self):
        client = M.Kubernetes()
        with patch.object(client, "call") as call:
            client.release(pod())
        body = json.loads(call.call_args.args[-1])
        self.assertEqual([item["path"] for item in body],
                         ["/metadata/uid", "/metadata/resourceVersion", "/spec/schedulingGates", "/spec/schedulingGates"])
        self.assertEqual([item["op"] for item in body], ["test", "test", "test", "remove"])


if __name__ == "__main__":
    unittest.main()
