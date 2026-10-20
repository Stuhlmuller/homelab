#!/usr/bin/env python3
"""Offline ownership and private-file fixtures for the bootstrap key reader."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "oce_bootstrap_key", ROOT / "scripts/openclaw-enterprise-bootstrap-key.py")
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)
POD_UID = "01234567-89ab-cdef-0123-456789abcdef"


def pod():
    return {
        "kind": "Pod",
        "metadata": {"name": reader.READER, "namespace": reader.NAMESPACE, "uid": POD_UID,
                     "labels": {"app.kubernetes.io/name": "openclaw-enterprise-bootstrap-reader",
                                "app.kubernetes.io/instance": "oce",
                                "app.kubernetes.io/part-of": "openclaw-enterprise"}},
        "spec": {"nodeSelector": {"oce-role": "control"}, "nodeName": "control-node",
                 "automountServiceAccountToken": False, "enableServiceLinks": False,
                 "restartPolicy": "Always", "securityContext": {"runAsNonRoot": True,
                    "runAsUser": 1000, "runAsGroup": 1000,
                    "seccompProfile": {"type": "RuntimeDefault"}},
                 "containers": [{"name": "reader", "image": reader.IMAGE,
                    "command": ["python3", "-I", "-c", "import time; time.sleep(1000000000)"],
                    "volumeMounts": [{"name": "bootstrap",
                        "mountPath": "/var/lib/openclaw/bootstrap", "readOnly": True}],
                    "livenessProbe": {"exec": {"command": ["python3", "-I", "-c", "import os; os.kill(1, 0)"]}},
                    "readinessProbe": {"exec": {"command": ["sh", "-c", "test -f /var/lib/openclaw/bootstrap/initial-admin-service-key.json"]}},
                    "securityContext": {"allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}}],
                 "volumes": [{"name": "bootstrap", "persistentVolumeClaim": {
                     "claimName": reader.CLAIM, "readOnly": True}}]},
        "status": {"phase": "Running", "containerStatuses": [{"name": "reader",
                   "ready": True, "state": {"running": {}}}],
                   "conditions": [{"type": "Ready", "status": "True"}]},
    }


def job():
    return {"kind": "Job", "metadata": {"name": "oce-initialization",
            "namespace": reader.NAMESPACE, "labels": {
                "app.kubernetes.io/instance": "oce",
                "app.kubernetes.io/component": "initialization"}},
            "status": {"succeeded": 1,
                       "conditions": [{"type": "Complete", "status": "True"}]}}


def policy():
    return {"kind": "NetworkPolicy", "metadata": {
        "name": "oce-bootstrap-reader-isolation", "namespace": reader.NAMESPACE},
        "spec": {"podSelector": {"matchLabels": {
            "app.kubernetes.io/name": "openclaw-enterprise-bootstrap-reader",
            "app.kubernetes.io/instance": "oce"}},
            "policyTypes": ["Ingress", "Egress"]}}


class BootstrapReader(unittest.TestCase):
    def test_fixed_ready_source_and_completed_producer(self):
        self.assertEqual(reader._ready_reader(pod()), POD_UID)
        reader._bootstrap_finished(job())
        reader._isolated(policy())

    def test_rejects_wrong_owner_mount_image_or_status(self):
        changes = [
            lambda p: p["metadata"].update(namespace="other"),
            lambda p: p["metadata"].update(uid="bad"),
            lambda p: p["metadata"].update(ownerReferences=[{"kind": "Deployment"}]),
            lambda p: p["spec"].update(automountServiceAccountToken=True),
            lambda p: p["spec"].update(hostNetwork=True),
            lambda p: p["spec"].update(hostPID=True),
            lambda p: p["spec"].update(initContainers=[{"name": "unreviewed"}]),
            lambda p: p["spec"].update(ephemeralContainers=[{"name": "unreviewed"}]),
            lambda p: p["spec"].update(shareProcessNamespace=True),
            lambda p: p["spec"]["containers"][0].update(image="unreviewed"),
            lambda p: p["spec"]["containers"][0].update(env=[{"name": "LD_PRELOAD", "value": "/tmp/preload.so"}]),
            lambda p: p["spec"]["containers"][0]["securityContext"].update(privileged=True),
            lambda p: p["spec"]["containers"][0]["securityContext"].update(runAsUser=0),
            lambda p: p["spec"]["containers"][0].update(lifecycle={"postStart": {"exec": {"command": ["sh"]}}}),
            lambda p: p["spec"]["containers"][0].update(startupProbe={"exec": {"command": ["sh", "-c", "cat /var/lib/openclaw/bootstrap/initial-admin-service-key.json"]}}),
            lambda p: p["spec"]["containers"][0].update(readinessProbe={"exec": {"command": ["sh", "-c", "cat /var/lib/openclaw/bootstrap/initial-admin-service-key.json"]}}),
            lambda p: p["spec"]["containers"][0].update(terminationMessagePath="/var/lib/openclaw/bootstrap/initial-admin-service-key.json"),
            lambda p: p["spec"]["volumes"][0]["persistentVolumeClaim"].update(readOnly=False),
            lambda p: p["status"]["containerStatuses"][0].update(ready=False),
        ]
        for change in changes:
            candidate = pod()
            change(candidate)
            with self.subTest(change=change), self.assertRaises(reader.Blocked):
                reader._ready_reader(candidate)
        unfinished = job()
        unfinished["status"]["succeeded"] = 0
        with self.assertRaises(reader.Blocked):
            reader._bootstrap_finished(unfinished)
        open_policy = policy()
        open_policy["spec"]["egress"] = [{"to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}]}]
        with self.assertRaises(reader.Blocked):
            reader._isolated(open_policy)

    def test_copies_only_to_private_file_then_rechecks_uid(self):
        key = b'{"data":{"key":"private-test-key"}}\n'
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "service-key.json"
            def copy(*args, output=None):
                self.assertEqual(args[:4], ("exec", reader.READER, "-c", "reader"))
                output.write(key)
            startup = Mock()
            with patch.object(reader, "_startup", return_value=startup), \
                 patch.object(reader, "kube_json", side_effect=[job(), policy(), pod(), pod(), policy()]), \
                 patch.object(reader, "kube", side_effect=copy):
                self.assertEqual(reader.materialize("a" * 40, destination), POD_UID)
            self.assertEqual(destination.read_bytes(), key)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(startup.reviewed_main.call_count, 2)

    def test_failed_copy_or_changed_reader_removes_partial_key(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "service-key.json"
            def partial(*args, output=None):
                output.write(b"private-partial-key")
                raise reader.Blocked("private Kubernetes read failed")
            with patch.object(reader, "_startup", return_value=Mock()), \
                 patch.object(reader, "kube_json", side_effect=[job(), policy(), pod()]), \
                 patch.object(reader, "kube", side_effect=partial):
                with self.assertRaises(reader.Blocked):
                    reader.materialize("a" * 40, destination)
            self.assertFalse(destination.exists())
            changed = deepcopy(pod())
            changed["metadata"]["uid"] = "fedcba98-7654-3210-fedc-ba9876543210"
            with patch.object(reader, "_startup", return_value=Mock()), \
                 patch.object(reader, "kube_json", side_effect=[job(), policy(), pod(), changed]), \
                 patch.object(reader, "kube", side_effect=lambda *a, output: output.write(b"key")):
                with self.assertRaises(reader.Blocked):
                    reader.materialize("a" * 40, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
