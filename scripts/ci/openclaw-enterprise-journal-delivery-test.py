#!/usr/bin/env python3
"""Check dormant journal delivery and interrupted private journal writes."""

import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = ROOT / "clusters/homelab/apps/openclaw-enterprise-foundation"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OCE = load("enterprise", ROOT / "scripts/openclaw-enterprise.py")
PROBE = load("journal_probe", FOUNDATION / "journal-probe.py")


class JournalDelivery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.mount = Path(temporary.name).resolve()
        self.private = self.mount / "openclaw-enterprise"
        self.private.mkdir(mode=0o700)

    def mountinfo(self, options="rw,vers=3"):
        return f"31 22 0:37 / {self.mount} rw,relatime - nfs 10.1.0.2:/homelab {options}\n"

    def test_dormant_claim_and_probe_mount_are_explicit(self):
        rendered = subprocess.check_output(["kubectl", "kustomize", str(FOUNDATION)], text=True)
        resources = json.loads(subprocess.check_output(
            ["yq", "ea", "-o=json", "-I=0", "[.]", "-"], input=rendered, text=True))
        objects = {(item["kind"], item["metadata"]["name"]): item for item in resources}
        claim = objects["PersistentVolumeClaim", "occ-operations-journal"]
        self.assertEqual(claim["metadata"]["namespace"], "openclaw-system")
        self.assertEqual(claim["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")
        self.assertEqual(claim["spec"], {"accessModes": ["ReadWriteMany"],
                                        "storageClassName": "nfs-default",
                                        "resources": {"requests": {"storage": "1Gi"}}})
        job = objects["Job", "occ-operations-journal-probe"]["spec"]
        self.assertTrue(job["suspend"])
        self.assertEqual(job["backoffLimit"], 0)
        self.assertEqual(job["ttlSecondsAfterFinished"], 3600)
        pod = job["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["securityContext"]["runAsUser"], 1000)
        self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
        self.assertEqual(pod["volumes"][0]["persistentVolumeClaim"]["claimName"], "occ-operations-journal")
        probe = pod["containers"][0]
        config_map_name = pod["volumes"][1]["configMap"]["name"]
        self.assertIn(("ConfigMap", config_map_name), objects)
        self.assertEqual(objects["ConfigMap", config_map_name]["data"]["journal-probe.py"],
                         (FOUNDATION / "journal-probe.py").read_text())
        self.assertEqual(probe["volumeMounts"][0]["mountPath"], "/private")
        self.assertEqual(probe["command"], ["python3", "-I", "-B", "/opt/journal-probe/journal-probe.py"])
        self.assertTrue(probe["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(probe["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertNotIn("env", probe)
        self.assertNotIn("envFrom", probe)
        self.assertNotIn("imagePullSecrets", pod)
        self.assertTrue(probe["image"].startswith("harbor.stinkyboi.com/mirror/"))
        self.assertIn("@sha256:", probe["image"])

    def test_mount_probe_retries_without_erasing_journal(self):
        self.private.rmdir()
        PROBE.probe(self.mount, self.mountinfo())
        journal = self.private / "journal.json"
        journal.write_bytes(b"private-journal-marker\n")
        journal.chmod(0o600)
        PROBE.probe(self.mount, self.mountinfo())
        (self.private / ".delivery-probe").write_bytes(b"journal-mount-probe\n")
        (self.private / ".delivery-probe").chmod(0o600)
        PROBE.probe(self.mount, self.mountinfo())
        self.assertEqual(journal.read_bytes(), b"private-journal-marker\n")
        self.assertEqual(stat.S_IMODE(self.private.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.private / ".delivery.lock").stat().st_mode), 0o600)
        self.assertFalse((self.private / ".delivery-probe").exists())
        self.assertFalse(list(self.private.glob(".delivery-*")))

    def test_mount_probe_rejects_local_only_locks_and_weak_permissions(self):
        with self.assertRaisesRegex(PROBE.Blocked, "shared locking"):
            PROBE.probe(self.mount, self.mountinfo("rw,vers=3,local_lock=all"))
        with self.assertRaisesRegex(PROBE.Blocked, "one NFS mount"):
            PROBE.probe(self.mount, self.mountinfo().replace(" - nfs ", " - ext4 "))
        self.private.chmod(0o755)
        with self.assertRaisesRegex(PROBE.Blocked, "owner or mode"):
            PROBE.probe(self.mount, self.mountinfo())

    def test_pending_intent_survives_process_exit_and_retry(self):
        path = self.private / "journal.json"
        source, desired = "a" * 40, "b" * 64
        pid = os.fork()
        if pid == 0:
            with OCE.ProtectedJournal(path, source, desired) as journal:
                journal.save({"pending": {"operation": "namespace-create"}})
                os._exit(0)
        _, result = os.waitpid(pid, 0)
        self.assertTrue(os.WIFEXITED(result))
        self.assertEqual(os.WEXITSTATUS(result), 0)
        with OCE.ProtectedJournal(path, source, desired) as journal:
            self.assertEqual(journal.state, {"pending": {"operation": "namespace-create"}})
            journal.save({"namespaceId": "ns_one"})
        with OCE.ProtectedJournal(path, source, desired) as journal:
            self.assertEqual(journal.state, {"namespaceId": "ns_one"})

    def test_failed_replace_retains_prior_intent_for_recovery(self):
        path = self.private / "journal.json"
        source, desired = "a" * 40, "b" * 64
        with OCE.ProtectedJournal(path, source, desired) as journal:
            journal.save({"pending": {"operation": "namespace-create"}})
            with patch.object(OCE.os, "replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    journal.save({"namespaceId": "ns_one"})
        with OCE.ProtectedJournal(path, source, desired) as journal:
            self.assertEqual(journal.state, {"pending": {"operation": "namespace-create"}})
        self.assertFalse(list(self.private.glob(".journal-*")))


if __name__ == "__main__":
    unittest.main()
