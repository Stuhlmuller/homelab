#!/usr/bin/env python3
"""Offline guards for the dormant rscstore capture and S3 publication set."""

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAPTURE = load("octelium_rscstore_capture_test", ROOT / "scripts/octelium-rscstore-capture.py")
PUBLISHER = load("application_backup_rscstore_test", ROOT / "scripts/application-backup.py")
PVC_UID = "11111111-1111-4111-8111-111111111111"
PV_UID = "22222222-2222-4222-8222-222222222222"
DEPLOY_UID = "33333333-3333-4333-8333-333333333333"
POD_UID = "44444444-4444-4444-8444-444444444444"
SHA = "a" * 40


def archive_bytes(include_database=True):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        if include_database:
            (root / "store.db").write_bytes(b"synthetic checkpoint")
        (root / "store.db.wal").write_bytes(b"synthetic unreplayable wal")
        (root / "store.db.wal.quarantined-20260826").write_bytes(b"older wal")
        (root / ".homelab-rscstore-wal-recovery-20260826").write_bytes(b"")
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as bundle:
            bundle.add(root, arcname=".")
        return data.getvalue()


def source_fixture(workspace, tar_data):
    stamp = "20261101T000000Z"
    source = workspace / stamp
    source.mkdir(mode=0o700)
    half = (len(tar_data) + 1) // 2
    (source / CAPTURE.PARTS[0]).write_bytes(tar_data[:half])
    (source / CAPTURE.PARTS[1]).write_bytes(tar_data[half:])
    inspection = CAPTURE.inspect_archive(source)
    digest = hashlib.sha256(tar_data).hexdigest()
    record = {
        "format": 1, "capture_method": "complete-pvc-tar-v1", "captured_at": stamp,
        "writers_fenced": True, "approved_fence_reference": SHA,
        "source": {"namespace": CAPTURE.NAMESPACE, "pvc_name": CAPTURE.CLAIM,
                   "pvc_uid": PVC_UID, "pv_name": "pvc-test", "pv_uid": PV_UID,
                   "deployment_uid": DEPLOY_UID, "inspector_uid": POD_UID},
        "archive": {"parts": list(CAPTURE.PARTS), "bytes": len(tar_data),
                    "before_sha256": digest, "sha256": digest, "after_sha256": digest},
        "inspection": inspection,
    }
    (source / "capture.json").write_bytes(CAPTURE.canonical(record))
    checksum_lines = []
    for name in (*CAPTURE.PARTS, "capture.json"):
        digest = hashlib.sha256((source / name).read_bytes()).hexdigest()
        checksum_lines.append(f"{digest}  {name}\n")
    (source / "SHA256SUMS").write_text("".join(checksum_lines))
    return source


def cluster_fixture():
    deployment = {"metadata": {"namespace": "octelium", "name": CAPTURE.DEPLOYMENT,
                               "uid": DEPLOY_UID, "generation": 7},
                  "spec": {"replicas": 0}, "status": {"observedGeneration": 7}}
    pvc = {"metadata": {"namespace": "octelium", "name": CAPTURE.CLAIM, "uid": PVC_UID},
           "spec": {"volumeName": "pvc-test", "storageClassName": "nfs-default"},
           "status": {"phase": "Bound"}}
    pv = {"metadata": {"name": "pvc-test", "uid": PV_UID},
          "spec": {"claimRef": {"namespace": "octelium", "name": CAPTURE.CLAIM,
                                "uid": PVC_UID}}, "status": {"phase": "Bound"}}
    inspector = {"metadata": {"namespace": "octelium", "name": CAPTURE.INSPECTOR,
                              "uid": POD_UID, "labels": {"app.kubernetes.io/name": CAPTURE.INSPECTOR,
                                                          "app.kubernetes.io/part-of": "octelium-enterprise"}},
                 "spec": {"automountServiceAccountToken": False,
                          "enableServiceLinks": False,
                          "nodeSelector": {"octelium.com/node-mode-controlplane": ""},
                          "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
                          "containers": [{"name": "inspection", "image": CAPTURE.IMAGE,
                                          "command": ["/bin/sh", "-ec", "exec sleep infinity"],
                                          "livenessProbe": {"exec": {"command": ["/bin/sh", "-ec",
                                                                                  "test -d /source"]},
                                                            "periodSeconds": 30, "timeoutSeconds": 2},
                                          "readinessProbe": {"exec": {"command": ["/bin/sh", "-ec",
                                                                                   "test -f /source/store.db && test -r /source/store.db"]},
                                                             "periodSeconds": 10, "timeoutSeconds": 2},
                                          "securityContext": {"runAsUser": 0, "runAsGroup": 0,
                                                              "readOnlyRootFilesystem": True,
                                                              "allowPrivilegeEscalation": False,
                                                              "capabilities": {"drop": ["ALL"]}},
                                          "volumeMounts": [{"name": "source", "mountPath": "/source",
                                                            "readOnly": True}]}],
                          "volumes": [{"name": "source", "persistentVolumeClaim": {
                              "claimName": CAPTURE.CLAIM, "readOnly": True}}]},
                 "status": {"phase": "Running", "containerStatuses": [{"ready": True}]}}
    return deployment, pvc, pv, [inspector]


class RscstoreCaptureTest(unittest.TestCase):
    def test_s3_policy_examples_scope_new_prefix(self):
        prefix = "applications/octelium-rscstore/*"
        bucket = "arn:aws:s3:::homelab-application-backups-716182248480-us-east-1/"
        for filename, required in (("publisher-policy.json", "CreateChecksummedObjects"),
                                   ("reader-policy.json", "VerifyImmutableApplicationVersions")):
            with self.subTest(filename=filename):
                policy = json.loads((ROOT / "recovery/application-backups" / filename).read_text())
                statements = {item["Sid"]: item for item in policy["Statement"]}
                self.assertIn(prefix, statements["ListApplicationPrefixes"]["Condition"]
                              ["StringLike"]["s3:prefix"])
                self.assertIn(bucket + prefix, statements[required]["Resource"])

    def test_stage_is_dormant_in_active_kustomization(self):
        source = (ROOT / "clusters/homelab/apps/octelium-enterprise/kustomization.yaml").read_text()
        self.assertNotIn("capture-stage", source)

    def test_pod_list_requires_unpaginated_resource_version(self):
        deployment, pvc, pv, pods = cluster_fixture()

        def snapshot(*command):
            if "deployment" in command:
                return deployment
            if "pvc" in command:
                return pvc
            if "pv" in command:
                return pv
            return {"apiVersion": "v1", "kind": "PodList", "items": pods,
                    "metadata": {"resourceVersion": "42", "continue": "next-page"}}

        with mock.patch.object(CAPTURE, "argo_guard"), \
                mock.patch.object(CAPTURE, "json_output", side_effect=snapshot), \
                self.assertRaises(ValueError):
            CAPTURE.cluster_guard("homelab", PVC_UID, PV_UID, SHA)

    def test_inspector_requires_exact_identity_and_zero_other_mounts(self):
        deployment, pvc, pv, pods = cluster_fixture()
        identity = CAPTURE.inspector_guard(deployment, pvc, pv, pods, PVC_UID, PV_UID)
        self.assertEqual(identity["inspector_uid"], POD_UID)
        for field, value in (("pvc_uid", "55555555-5555-4555-8555-555555555555"),
                             ("pv_uid", "66666666-6666-4666-8666-666666666666")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                CAPTURE.inspector_guard(deployment, pvc, pv, pods,
                                        value if field == "pvc_uid" else PVC_UID,
                                        value if field == "pv_uid" else PV_UID)
        active = copy.deepcopy(pods[0])
        active["metadata"]["name"] = "second-writer"
        active["metadata"]["uid"] = "77777777-7777-4777-8777-777777777777"
        with self.assertRaises(ValueError):
            CAPTURE.inspector_guard(deployment, pvc, pv, [*pods, active], PVC_UID, PV_UID)
        deployment["spec"]["replicas"] = 1
        with self.assertRaises(ValueError):
            CAPTURE.inspector_guard(deployment, pvc, pv, pods, PVC_UID, PV_UID)
        deployment["spec"]["replicas"] = 0
        pods[0]["spec"]["volumes"][0]["persistentVolumeClaim"]["readOnly"] = False
        with self.assertRaises(ValueError):
            CAPTURE.inspector_guard(deployment, pvc, pv, pods, PVC_UID, PV_UID)

    def test_inspector_probe_and_uid_drift_rejected(self):
        deployment, pvc, pv, pods = cluster_fixture()
        defaulted = copy.deepcopy(pods)
        for name in ("livenessProbe", "readinessProbe"):
            defaulted[0]["spec"]["containers"][0][name].update(
                initialDelaySeconds=0, failureThreshold=3, successThreshold=1)
        CAPTURE.inspector_guard(deployment, pvc, pv, defaulted, PVC_UID, PV_UID)
        changes = (
            lambda pod: pod["spec"]["containers"][0]["readinessProbe"].update(
                initialDelaySeconds=3600),
            lambda pod: pod["spec"]["containers"][0]["readinessProbe"].update(
                grpc={"port": 443}),
            lambda pod: pod["spec"]["containers"][0]["readinessProbe"]["exec"].update(
                command=["/bin/sh", "-ec", "true"]),
            lambda pod: pod["spec"]["containers"][0]["livenessProbe"]["exec"].update(
                command=["/bin/sh", "-ec", "true"]),
            lambda pod: pod["spec"]["containers"][0]["securityContext"].update(runAsUser=1000),
            lambda pod: pod["spec"]["containers"][0]["securityContext"].update(runAsGroup=1000),
        )
        for change in changes:
            with self.subTest(change=change):
                altered = copy.deepcopy(pods)
                change(altered[0])
                with self.assertRaises(ValueError):
                    CAPTURE.inspector_guard(deployment, pvc, pv, altered, PVC_UID, PV_UID)

    def test_complete_archive_prepares_for_versioned_publisher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = source_fixture(root, archive_bytes())
            CAPTURE.validate_bundle(source)
            workspace = root / "workspace"
            workspace.mkdir(mode=0o700)
            with mock.patch.object(PUBLISHER, "fresh"):
                prepared = PUBLISHER.prepare(source, workspace, "octelium-rscstore")
            self.assertEqual(set(PUBLISHER.load(prepared)["objects"]),
                             {*CAPTURE.PARTS, "capture.json"})
            self.assertLess((prepared / CAPTURE.PARTS[0]).stat().st_size, CAPTURE.MAX_OBJECT)

    def test_partial_archive_and_changed_hash_fail_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = source_fixture(root, archive_bytes())
            record = json.loads((source / "capture.json").read_text())
            record["archive"]["after_sha256"] = "0" * 64
            (source / "capture.json").write_bytes(CAPTURE.canonical(record))
            checksum_lines = []
            for name in (*CAPTURE.PARTS, "capture.json"):
                checksum_lines.append(f"{hashlib.sha256((source / name).read_bytes()).hexdigest()}  {name}\n")
            (source / "SHA256SUMS").write_text("".join(checksum_lines))
            workspace = root / "workspace"
            workspace.mkdir(mode=0o700)
            with mock.patch.object(PUBLISHER, "fresh"), self.assertRaises(ValueError):
                PUBLISHER.prepare(source, workspace, "octelium-rscstore")
            missing = root / "missing"
            missing.mkdir(mode=0o700)
            with self.assertRaises(ValueError):
                source_fixture(missing, archive_bytes(include_database=False))

    def test_capture_requires_three_equal_streams_and_writes_receipt_last(self):
        data = archive_bytes()
        digest = hashlib.sha256(data).hexdigest()
        identity = {"pvc_uid": PVC_UID, "pv_name": "pvc-test", "pv_uid": PV_UID,
                    "deployment_uid": DEPLOY_UID, "inspector_uid": POD_UID}

        def stream(_context, _pod, sink=None):
            if sink:
                for offset in range(0, len(data), 137):
                    sink(data[offset:offset + 137])
            return {"bytes": len(data), "sha256": digest}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with mock.patch.object(CAPTURE, "private_parent", return_value=root), \
                    mock.patch.object(CAPTURE, "release_guard") as release, \
                    mock.patch.object(CAPTURE, "cluster_guard", return_value=identity), \
                    mock.patch.object(CAPTURE, "tar_stream", side_effect=stream), \
                    mock.patch.object(CAPTURE.shutil, "disk_usage", return_value=mock.Mock(free=10**12)):
                stamp = CAPTURE.capture(root, SHA, "homelab", PVC_UID, PV_UID)
            self.assertEqual(release.call_count, 2)
            source = root / stamp
            self.assertEqual(CAPTURE.validate_bundle(source)["archive"]["sha256"], digest)
            self.assertTrue((source / "SHA256SUMS").is_file())

            second = root / "second"
            second.mkdir(mode=0o700)
            calls = 0

            def drifting_stream(_context, _pod, sink=None):
                nonlocal calls
                calls += 1
                if sink:
                    sink(data)
                return {"bytes": len(data), "sha256": digest if calls == 1 else "0" * 64}

            with mock.patch.object(CAPTURE, "private_parent", return_value=second), \
                    mock.patch.object(CAPTURE, "release_guard"), \
                    mock.patch.object(CAPTURE, "cluster_guard", return_value=identity), \
                    mock.patch.object(CAPTURE, "tar_stream", side_effect=drifting_stream), \
                    mock.patch.object(CAPTURE.shutil, "disk_usage", return_value=mock.Mock(free=10**12)):
                with self.assertRaises(ValueError):
                    CAPTURE.capture(second, SHA, "homelab", PVC_UID, PV_UID)
            self.assertFalse(any(second.glob("*/SHA256SUMS")))

    def test_isolated_retrieval_extraction_records_s3_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = source_fixture(root, archive_bytes())
            retrieval = root / "retrieval-example"
            retrieval.mkdir(mode=0o700)
            objects = {}
            for name in (*CAPTURE.PARTS, "capture.json"):
                payload = (source / name).read_bytes()
                (retrieval / name).write_bytes(payload)
                objects[name] = {"digest": {"bytes": len(payload),
                                            "sha256": hashlib.sha256(payload).hexdigest()},
                                 "version_id": "version-1"}
            (retrieval / "complete.json").write_text(json.dumps({"app": "octelium-rscstore",
                                                                   "captured_at": "20261101T000000Z",
                                                                   "objects": objects}))
            (retrieval / "retrieval.json").write_text(json.dumps({"id": "20261101T000000Z-" + "a" * 64,
                                                                    "marker_version": "marker-1"}))
            proof = root / "proof"
            identifier = "20261101T000000Z-" + "a" * 64
            with mock.patch.object(CAPTURE, "private_parent", side_effect=lambda value: value), \
                    mock.patch.object(CAPTURE.subprocess, "check_output",
                                      return_value="retrieval-example\n") as download:
                CAPTURE.prove_retrieval(root, identifier, proof, Path("/usr/bin/aws"),
                                        "application-backup-reader")
            command = download.call_args.args[0]
            self.assertEqual(command[3:6], ["retrieve", "--app", "octelium-rscstore"])
            self.assertIn(identifier, command)
            self.assertEqual((proof / "restored/store.db").read_bytes(), b"synthetic checkpoint")
            self.assertEqual(json.loads((proof / "proof.json").read_text())["marker_version"],
                             "marker-1")

    def test_s3_retrieve_failure_cannot_issue_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            forged = root / "retrieval-forged"
            forged.mkdir(mode=0o700)
            (forged / "complete.json").write_text('{"app":"octelium-rscstore"}')
            (forged / "retrieval.json").write_text('{"marker_version":"fake"}')
            proof = root / "proof"
            with mock.patch.object(CAPTURE, "private_parent", side_effect=lambda value: value), \
                    mock.patch.object(CAPTURE.subprocess, "check_output",
                                      side_effect=subprocess.CalledProcessError(1, "publisher")):
                with self.assertRaises(subprocess.CalledProcessError):
                    CAPTURE.prove_retrieval(root, "20261101T000000Z-" + "a" * 64,
                                            proof, Path("/usr/bin/aws"), "application-backup-reader")
            self.assertFalse(proof.exists())

    def test_main_drift_at_final_guard_never_completes_capture(self):
        data = archive_bytes()
        digest = hashlib.sha256(data).hexdigest()
        identity = {"pvc_uid": PVC_UID, "pv_name": "pvc-test", "pv_uid": PV_UID,
                    "deployment_uid": DEPLOY_UID, "inspector_uid": POD_UID}

        def stream(_context, _pod, sink=None):
            if sink:
                sink(data)
            return {"bytes": len(data), "sha256": digest}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with mock.patch.object(CAPTURE, "private_parent", return_value=root), \
                    mock.patch.object(CAPTURE, "release_guard",
                                      side_effect=[None, ValueError("main advanced")]), \
                    mock.patch.object(CAPTURE, "cluster_guard", return_value=identity), \
                    mock.patch.object(CAPTURE, "tar_stream", side_effect=stream), \
                    mock.patch.object(CAPTURE.shutil, "disk_usage",
                                      return_value=mock.Mock(free=10**12)):
                with self.assertRaisesRegex(ValueError, "main advanced"):
                    CAPTURE.capture(root, SHA, "homelab", PVC_UID, PV_UID)
            self.assertFalse(any(root.glob("[0-9]*T[0-9]*Z")))
            self.assertTrue(any(root.glob(".partial-*/capture.json")))


if __name__ == "__main__":
    unittest.main()
