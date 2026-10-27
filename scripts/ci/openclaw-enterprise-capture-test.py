#!/usr/bin/env python3
"""Offline fixtures for the dormant cross-namespace recovery tree assembler."""

import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr
import uuid


ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


OCE = module("oce_capture_base", "scripts/openclaw-enterprise.py")
CAPTURE = module("oce_capture", "scripts/ci/openclaw-enterprise-capture.py")
SHA = "a" * 40
UIDS = {
    "journal": "11111111-1111-4111-8111-111111111111",
    "bootstrap": "22222222-2222-4222-8222-222222222222",
    "gateway": "33333333-3333-4333-8333-333333333333",
    "operatorPod": "44444444-4444-4444-8444-444444444444",
    "tenantPod": "55555555-5555-4555-8555-555555555555",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def secret(namespace, name, values, *, uid=None, labels=None, annotations=None):
    return {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
            "metadata": {"name": name, "namespace": namespace,
                         "uid": uid or str(uuid.uuid5(uuid.NAMESPACE_DNS, namespace + "/" + name)),
                         "resourceVersion": "11",
                         "labels": labels or {}, "annotations": annotations or {}},
            "data": {key: base64.b64encode(value.encode()).decode()
                     for key, value in values.items()}}


def pvc(namespace, name, claim_uid, storage_class):
    return {"metadata": {"name": name, "namespace": namespace,
                         "uid": claim_uid, "resourceVersion": "12"},
            "spec": {"volumeName": "pv-" + name,
                     "storageClassName": storage_class,
                     "accessModes": ["ReadWriteOnce"]},
            "status": {"phase": "Bound"}}


def pv(namespace, name, claim_uid, storage_class):
    return {"metadata": {"name": "pv-" + name, "uid": claim_uid,
                         "resourceVersion": "12"},
            "spec": {"claimRef": {"name": name, "namespace": namespace,
                                  "uid": claim_uid},
                     "storageClassName": storage_class,
                     "persistentVolumeReclaimPolicy": "Retain"}}


def pod(namespace, name, uid, claims):
    return {"metadata": {"name": name, "namespace": namespace, "uid": uid},
            "spec": {"automountServiceAccountToken": False,
                     "hostNetwork": False, "restartPolicy": "Never",
                     "securityContext": {"runAsUser": 1000, "runAsNonRoot": True,
                                         "seccompProfile": {"type": "RuntimeDefault"}},
                     "volumes": [{"name": key, "persistentVolumeClaim": {
                         "claimName": value, "readOnly": True}}
                         for key, value in claims.items()],
                     "containers": [{"name": "reader", "volumeMounts": [
                         {"name": key, "mountPath": "/source/" + key,
                          "readOnly": True} for key in claims],
                         "securityContext": {"allowPrivilegeEscalation": False,
                                             "readOnlyRootFilesystem": True,
                                             "capabilities": {"drop": ["ALL"]}}}]}}


class CaptureAssembler(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-capture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.config["journalOperator"].update({
            "enabled": True, "journalClaimUid": UIDS["journal"],
            "journalVolumeUid": UIDS["journal"],
            "bootstrapClaimUid": UIDS["bootstrap"]})
        self.state = {"installationId": "ins_one", "namespaceId": "ns_one",
                      "agentId": "agt_one", "configurationId": "cfg_one",
                      "configurationGeneration": 2, "firstRevisionId": "rev_one",
                      "revisionId": "rev_two", "servicePrincipalId": "sp_one",
                      "secretId": "sec_one"}
        private = self.root / "private"
        private.mkdir(mode=0o700)
        journal = private / "journal.json"
        with OCE.ProtectedJournal(journal, self.config["source"]["revision"],
                                  OCE._identity_hash(self.config)) as protected:
            protected.save(self.state)
        self.journal_bytes = journal.read_bytes()
        suffix = hashlib.sha256(self.state["agentId"].encode()).hexdigest()[:12]
        self.gateway_name = "gateway-state-" + suffix
        self.transport_name = "openclaw-agent-transport-" + suffix
        self.password_name = "gateway-password-" + suffix
        self.model_name = "secret-" + hashlib.sha256(b"ns_one").hexdigest()[:12]
        self.model_name += "-" + hashlib.sha256(b"sec_one").hexdigest()[:12] + "-abcdef123456"
        self.claims = {
            "journal": pvc("openclaw-system", "occ-operator-journal", UIDS["journal"],
                           "openclaw-enterprise-journal-local"),
            "bootstrap": pvc("openclaw-system", "occ-bootstrap-admin-password", UIDS["bootstrap"],
                             "openclaw-enterprise-bootstrap-local"),
            "gateway": pvc("openclaw-agents", self.gateway_name, UIDS["gateway"],
                           "openclaw-enterprise-agent-local"),
        }
        self.claims["gateway"]["metadata"]["labels"] = {
            "app.kubernetes.io/managed-by": "openclaw-enterprise",
            "openclaw.dev/namespace": "ns_one", "openclaw.dev/agent": "agt_one"}
        self.claims["gateway"]["metadata"]["annotations"] = {
            "openclaw.dev/namespace-id": "ns_one", "openclaw.dev/agent-id": "agt_one"}
        self.claims["gateway"]["spec"].update({
            "volumeMode": "Filesystem", "resources": {"requests": {"storage": "10Gi"}}})
        self.volumes = {key: pv(value["metadata"]["namespace"], value["metadata"]["name"],
                                value["metadata"]["uid"], value["spec"]["storageClassName"])
                        for key, value in self.claims.items()}
        system_names = {
            "occ-postgres-root": {"tls.crt": "root-cert", "tls.key": "root-key"},
            "occ-postgres-admin": {"password": "AdminPassword1"},
            "occ-postgres-migrator": {"password": "MigratorPassword1"},
            "occ-postgres-app": {"password": "AppPassword1"},
            "occ-postgres-backup": {"password": "BackupPassword1"},
            "occ-auth": {"secret": "session-auth"},
            "occ-private-gateway-key": {"occ": "gateway-key"},
            "occ-gateway-654a256bceae-root": {"tls.crt": "gateway-root-cert",
                                         "tls.key": "gateway-root-key"},
        }
        system = [secret("openclaw-system", name, values)
                  for name, values in system_names.items()]
        model_labels = {"app.kubernetes.io/managed-by": "openclaw-enterprise",
                        "openclaw.dev/namespace": "ns_one", "openclaw.dev/secret": "sec_one"}
        model_annotations = {"openclaw.dev/namespace-id": "ns_one",
                             "openclaw.dev/secret-id": "sec_one",
                             "openclaw.dev/secret-driver-id": "secret-kubernetes"}
        tenant = [
            secret("openclaw-agents", "occ-model-api-key", {"api-key": "model-key"}),
            secret("openclaw-agents", self.transport_name,
                   {"app-server-token": "transport-token"}),
            secret("openclaw-agents", self.password_name,
                   {"gateway-password": "gateway-password"}),
            secret("openclaw-agents", self.model_name, {"value": "model-key"},
                   labels=model_labels, annotations=model_annotations),
        ]
        self.operator_pod = pod("openclaw-system", "oce-capture-operator", UIDS["operatorPod"],
                                {"journal": "occ-operator-journal",
                                 "bootstrap": "occ-bootstrap-admin-password"})
        self.tenant_pod = pod("openclaw-agents", "oce-capture-tenant", UIDS["tenantPod"],
                              {"gateway": self.gateway_name})
        snapshot = {
            "claims": self.claims, "volumes": self.volumes,
            "journalSha256": hashlib.sha256(self.journal_bytes).hexdigest(),
            "tenantPods": {"kind": "PodList", "metadata": {"resourceVersion": "15"},
                           "items": []},
            "systemSecrets": {"kind": "SecretList", "metadata": {"resourceVersion": "20"},
                              "items": system},
            "tenantSecrets": {"kind": "SecretList", "metadata": {"resourceVersion": "21"},
                              "items": tenant},
            "agent": {"id": "agt_one", "namespaceId": "ns_one",
                      "configurationId": "cfg_one", "desiredRuntimeState": "stopped",
                      "activeRevisionId": None},
            "deployment": {"deploymentId": "rev_two", "namespaceId": "ns_one",
                           "agentId": "agt_one", "status": "succeeded"},
            "runtime": {"revisionId": "rev_two", "observedAt": "2026-10-27T00:00:00Z",
                        "pods": []},
        }
        self.observations = {"schemaVersion": 1, "sourceSha": SHA,
                             "identity": {key: self.state[key] for key in
                                          ("installationId", "namespaceId", "agentId",
                                           "revisionId")},
                             "before": copy.deepcopy(snapshot), "after": copy.deepcopy(snapshot),
                             "readers": {"operator": self.operator_pod,
                                         "tenant": self.tenant_pod},
                             "duringTenantPods": {"kind": "PodList",
                                                  "metadata": {"resourceVersion": "16"},
                                                  "items": [self.tenant_pod]}}
        self.operator_files = {"journal/journal.json": self.journal_bytes,
                               "bootstrap/output.json": b'{"bootstrap":true}\n',
                               "bootstrap/initial-admin-password": b"BootstrapPassword1",
                               "bootstrap/initial-admin-service-key.json": b'{"key":"private"}\n'}
        self.tenant_files = {"state/state/openclaw.sqlite": b"SQLite fixture",
                             "state/state/openclaw.sqlite-wal": b"WAL fixture",
                             "state/state/openclaw.sqlite-shm": b"SHM fixture",
                             "state/workspace/.hidden/note": b"Workspace fixture"}
        self.output = self.root / "material"

    def archive(self, name, files, namespace, pod_uid, claims, directories=()):
        payload = CAPTURE.payload_digest(files, directories)
        manifest = {"schemaVersion": 1, "sourceSha": SHA,
                    "namespace": namespace, "readerPodUid": pod_uid,
                    "claimUids": claims, "payloadSha256": payload}
        archive = self.root / name
        with tarfile.open(archive, "w") as tar:
            for directory in directories:
                info = tarfile.TarInfo(directory + "/")
                info.type = tarfile.DIRTYPE
                info.mode = 0o700
                tar.addfile(info)
            for path, data in {"manifest.json": canonical(manifest), **files}.items():
                info = tarfile.TarInfo(path)
                info.mode = 0o600
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        archive.chmod(0o600)
        return archive

    def run_assemble(self):
        operator = self.archive("operator.tar", self.operator_files, "openclaw-system",
                                UIDS["operatorPod"], {"journal": UIDS["journal"],
                                                      "bootstrap": UIDS["bootstrap"]})
        tenant = self.archive("tenant.tar", self.tenant_files, "openclaw-agents",
                              UIDS["tenantPod"], {"gateway": UIDS["gateway"]},
                              directories=("state/workspace/empty",))
        return CAPTURE.assemble(self.config, SHA, self.observations,
                                operator, tenant, self.output)

    def test_assembles_complete_private_tree_without_authorizing_publication(self):
        marker = self.run_assemble()
        self.assertFalse(marker["continuousFenceVerified"])
        self.assertTrue(marker["writerStopped"])
        self.assertEqual(marker["claimUid"], UIDS["gateway"])
        self.assertEqual(marker["sourceSha"], SHA)
        self.assertEqual(marker["revisionId"], "rev_two")
        self.assertEqual((self.output / "journal/journal.json").read_bytes(),
                         self.journal_bytes)
        self.assertEqual((self.output / "bootstrap/initial-admin-password").read_bytes(),
                         b"BootstrapPassword1")
        self.assertEqual((self.output / "agent/state/state/openclaw.sqlite").read_bytes(),
                         b"SQLite fixture")
        for path, expected in self.tenant_files.items():
            self.assertEqual((self.output / "agent" / path).read_bytes(), expected)
        self.assertTrue((self.output / "agent/state/workspace/empty").is_dir())
        self.assertEqual((self.output / "postgres-backup/password").read_text(),
                         "BackupPassword1")
        self.assertEqual((self.output / "gateway-ca/tls.key").read_text(),
                         "gateway-root-key")
        self.assertEqual(len(list((self.output / "tenant/secrets").glob("*.json"))), 4)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.output / "recovery.json").stat().st_mode & 0o777, 0o600)

    def test_claim_uid_or_pv_binding_change_blocks_without_output(self):
        self.observations["after"]["claims"]["gateway"]["metadata"]["uid"] = UIDS["bootstrap"]
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())
        self.observations["after"] = copy.deepcopy(self.observations["before"])
        for snapshot in (self.observations["before"], self.observations["after"]):
            snapshot["claims"]["gateway"]["metadata"]["labels"]["openclaw.dev/agent"] = "agt_foreign"
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())

    def test_insufficient_private_scratch_blocks_before_extracting(self):
        with patch.object(CAPTURE.os, "statvfs", return_value=SimpleNamespace(
                f_bavail=1, f_frsize=1)):
            with self.assertRaisesRegex(CAPTURE.Blocked, "scratch capacity"):
                self.run_assemble()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob(".oce-capture-*")))

    def test_secret_value_change_or_missing_canonical_source_blocks(self):
        self.observations["after"]["tenantSecrets"]["items"][0]["data"]["api-key"] = "Zm9yZWlnbg=="
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())
        self.observations["after"] = copy.deepcopy(self.observations["before"])
        self.observations["before"]["tenantSecrets"]["items"].pop()
        self.observations["after"]["tenantSecrets"]["items"].pop()
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())

    def test_missing_gateway_ca_or_bootstrap_credential_blocks(self):
        for snapshot in (self.observations["before"], self.observations["after"]):
            snapshot["systemSecrets"]["items"] = [item for item in
                snapshot["systemSecrets"]["items"]
                if item["metadata"]["name"] != "occ-gateway-654a256bceae-root"]
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())
        self.observations["before"]["systemSecrets"]["items"].append(
            secret("openclaw-system", "occ-gateway-654a256bceae-root",
                   {"tls.crt": "gateway-root-cert", "tls.key": "gateway-root-key"}))
        self.observations["after"] = copy.deepcopy(self.observations["before"])
        del self.operator_files["bootstrap/initial-admin-service-key.json"]
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())

    def test_duplicate_secret_uid_or_foreign_runtime_projection_blocks(self):
        secrets = self.observations["before"]["tenantSecrets"]["items"]
        duplicate_uid = secrets[0]["metadata"]["uid"]
        secrets[1]["metadata"]["uid"] = duplicate_uid
        self.observations["after"] = copy.deepcopy(self.observations["before"])
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())
        secrets[1]["metadata"]["uid"] = str(uuid.uuid5(uuid.NAMESPACE_DNS,
                                                         "openclaw-agents/" + self.transport_name))
        self.observations["before"]["tenantSecrets"]["items"].append(
            secret("openclaw-agents", "harness-secrets-foreign", {"model": "private"}))
        self.observations["after"] = copy.deepcopy(self.observations["before"])
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())

    def test_foreign_tenant_pod_or_running_agent_blocks(self):
        self.observations["duringTenantPods"]["items"].append(
            pod("openclaw-agents", "foreign", UIDS["journal"], {}))
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())

    def test_reader_subpath_mount_blocks_without_output(self):
        for kind in ("operator", "tenant"):
            for field in ("subPath", "subPathExpr"):
                with self.subTest(kind=kind, field=field):
                    mount = self.observations["readers"][kind]["spec"]["containers"][0]["volumeMounts"][0]
                    mount[field] = "partial"
                    with self.assertRaises(CAPTURE.Blocked):
                        self.run_assemble()
                    self.assertFalse(self.output.exists())
                    del mount[field]
        self.observations["duringTenantPods"]["items"] = [self.tenant_pod]
        self.observations["after"]["agent"]["desiredRuntimeState"] = "running"
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())

    def test_agent_or_journal_drift_blocks_without_output(self):
        self.observations["after"]["agent"]["harnessAuth"] = {"method": "foreign"}
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())
        self.observations["after"] = copy.deepcopy(self.observations["before"])
        self.observations["after"]["journalSha256"] = "b" * 64
        with self.assertRaises(CAPTURE.Blocked):
            self.run_assemble()
        self.assertFalse(self.output.exists())

    def test_reader_archive_rejects_path_escape_and_link_entries(self):
        for member in ("../escape", "/absolute", "state/../../escape"):
            with self.subTest(member=member):
                archive = self.archive("tenant.tar", self.tenant_files,
                                       "openclaw-agents", UIDS["tenantPod"],
                                       {"gateway": UIDS["gateway"]})
                with tarfile.open(archive, "a") as tar:
                    info = tarfile.TarInfo(member)
                    info.size = 1
                    tar.addfile(info, io.BytesIO(b"x"))
                operator = self.archive("operator.tar", self.operator_files,
                                        "openclaw-system", UIDS["operatorPod"],
                                        {"journal": UIDS["journal"],
                                         "bootstrap": UIDS["bootstrap"]})
                with self.assertRaises(CAPTURE.Blocked):
                    CAPTURE.assemble(self.config, SHA, self.observations,
                                     operator, archive, self.output)
                self.assertFalse(self.output.exists())
        operator = self.archive("operator.tar", self.operator_files,
                                "openclaw-system", UIDS["operatorPod"],
                                {"journal": UIDS["journal"],
                                 "bootstrap": UIDS["bootstrap"]})
        for link_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            archive = self.archive("tenant.tar", self.tenant_files, "openclaw-agents",
                                   UIDS["tenantPod"], {"gateway": UIDS["gateway"]})
            with tarfile.open(archive, "a") as tar:
                info = tarfile.TarInfo("state/link")
                info.type = link_type
                info.linkname = "/tmp/target"
                tar.addfile(info)
            with self.subTest(link_type=link_type), self.assertRaises(CAPTURE.Blocked):
                CAPTURE.assemble(self.config, SHA, self.observations,
                                 operator, archive, self.output)
            self.assertFalse(self.output.exists())
        archive = self.archive("tenant.tar", self.tenant_files, "openclaw-agents",
                               UIDS["tenantPod"], {"gateway": UIDS["gateway"]})
        with tarfile.open(archive, "a", format=tarfile.PAX_FORMAT) as tar:
            info = tarfile.TarInfo("state/sparse")
            info.size = 1
            info.pax_headers = {"GNU.sparse.map": "0,1"}
            tar.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(CAPTURE.Blocked):
            CAPTURE.assemble(self.config, SHA, self.observations,
                             operator, archive, self.output)
        self.assertFalse(self.output.exists())

    def test_reader_manifest_mismatch_blocks_without_output(self):
        self.tenant_files["state/state/openclaw.sqlite"] = b"different from manifest fixture"
        archive = self.archive("tenant.tar", self.tenant_files,
                               "openclaw-agents", UIDS["tenantPod"],
                               {"gateway": UIDS["gateway"]})
        self.tenant_files["state/state/openclaw.sqlite"] = b"SQLite fixture"
        with tarfile.open(archive, "a") as tar:
            info = tarfile.TarInfo("state/extra.sqlite")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        operator = self.archive("operator.tar", self.operator_files,
                                "openclaw-system", UIDS["operatorPod"],
                                {"journal": UIDS["journal"],
                                 "bootstrap": UIDS["bootstrap"]})
        with self.assertRaises(CAPTURE.Blocked):
            CAPTURE.assemble(self.config, SHA, self.observations,
                             operator, archive, self.output)
        self.assertFalse(self.output.exists())

    def test_unmanifested_empty_directory_blocks_without_output(self):
        operator = self.archive("operator.tar", self.operator_files,
                                "openclaw-system", UIDS["operatorPod"],
                                {"journal": UIDS["journal"],
                                 "bootstrap": UIDS["bootstrap"]})
        tenant = self.archive("tenant.tar", self.tenant_files,
                              "openclaw-agents", UIDS["tenantPod"],
                              {"gateway": UIDS["gateway"]},
                              directories=("state/workspace/empty",))
        with tarfile.open(tenant, "a") as tar:
            info = tarfile.TarInfo("state/workspace/unchecked-empty/")
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
        with self.assertRaises(CAPTURE.Blocked):
            CAPTURE.assemble(self.config, SHA, self.observations,
                             operator, tenant, self.output)
        self.assertFalse(self.output.exists())

    def test_cli_failure_does_not_print_private_diagnostics(self):
        observations = self.root / "observations.json"
        observations.write_bytes(canonical(self.observations))
        observations.chmod(0o600)
        operator = self.archive("operator.tar", self.operator_files, "openclaw-system",
                                UIDS["operatorPod"], {"journal": UIDS["journal"],
                                                      "bootstrap": UIDS["bootstrap"]})
        tenant = self.archive("tenant.tar", self.tenant_files, "openclaw-agents",
                              UIDS["tenantPod"], {"gateway": UIDS["gateway"]})
        stderr = io.StringIO()
        argv = ["--expected-sha", SHA, "--observations", str(observations),
                "--operator-archive", str(operator), "--tenant-archive", str(tenant),
                "--output", str(self.output)]
        with patch.object(CAPTURE, "assemble", side_effect=CAPTURE.Blocked("private-secret")), \
             redirect_stderr(stderr):
            self.assertEqual(CAPTURE.main(argv), 1)
        self.assertEqual(stderr.getvalue(), "Enterprise private capture assembly blocked\n")
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
