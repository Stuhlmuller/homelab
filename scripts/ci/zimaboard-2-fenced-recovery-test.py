"""Check the fenced-node recovery guards without contacting production."""

import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "recovery", Path(__file__).resolve().parents[1] / "zimaboard-2-fenced-recovery.py")
RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECOVERY)
SHA = "a" * 40


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.pods = {}
        for namespace, name, uid, kind, owner, claim in RECOVERY.TARGETS:
            volumes = ([{"persistentVolumeClaim": {"claimName": claim}}] if claim else [])
            self.pods[(namespace, name)] = {"metadata": {"uid": uid,
                "deletionTimestamp": "2026-10-10T21:00:00Z",
                "ownerReferences": [{"kind": kind, "name": owner}]},
                "spec": {"nodeName": RECOVERY.NODE, "volumes": volumes}}
        self.nodes = [{"metadata": {"name": name, "uid": RECOVERY.NODE_UID if name == RECOVERY.NODE else name},
                       "spec": {"taints": [{"key": "node.kubernetes.io/unreachable"}] if name == RECOVERY.NODE else []},
                       "status": {"conditions": [{"type": "Ready", "status": "Unknown" if name == RECOVERY.NODE else "True"}]}}
                      for name in (RECOVERY.NODE, "acer", "zimaboard-0", "zimaboard-1")]
        self.deletes = []

    def command(self, *args, input=None):
        if args[:2] == ("git", "-C") and args[-2:] == ("rev-parse", "HEAD"):
            return SHA
        if args[:2] == ("git", "-C") and args[-2:] == ("status", "--porcelain"):
            return ""
        if args[0] == "gh":
            return SHA
        if args[:2] == ("kubectl", "config"):
            return "https://10.1.0.199:6443"
        if args[:3] == ("kubectl", "get", "nodes"):
            return json.dumps({"items": self.nodes})
        if args[:2] == ("kubectl", "-n") and args[3:5] == ("get", "pod"):
            return json.dumps(self.pods[(args[2], args[5])])
        if args[:3] == ("kubectl", "delete", "--raw"):
            self.deletes.append((args[3], json.loads(input)))
            return ""
        raise AssertionError(args)

    def test_preflight_requires_exact_pod_and_node(self):
        with patch.object(RECOVERY, "command", side_effect=self.command), patch.object(
                RECOVERY.socket, "create_connection", side_effect=OSError("fenced")):
            RECOVERY.preflight(SHA, RECOVERY.TARGETS[1])
            self.pods[("automation", "n8n-postgres-0")]["metadata"]["uid"] = "replacement"
            with self.assertRaisesRegex(ValueError, "identity changed"):
                RECOVERY.preflight(SHA, RECOVERY.TARGETS[1])
            self.pods[("automation", "n8n-postgres-0")]["metadata"]["uid"] = RECOVERY.TARGETS[1][2]
            self.pods[("argocd", "argocd-application-controller-0")]["metadata"]["uid"] = "replacement"
            RECOVERY.preflight(SHA, RECOVERY.TARGETS[1])
            self.nodes[0]["status"]["conditions"][0]["status"] = "True"
            with self.assertRaisesRegex(ValueError, "Fenced node"):
                RECOVERY.preflight(SHA, RECOVERY.TARGETS[1])
        self.assertEqual(self.deletes, [])

    def test_delete_has_uid_precondition_and_requires_confirmation(self):
        with patch.object(RECOVERY, "command", side_effect=self.command), patch.object(
                RECOVERY.socket, "create_connection", side_effect=OSError("fenced")):
            with patch.object(sys, "argv", ["recovery", "--expected-sha", SHA, "--target",
                                            "argocd/argocd-application-controller-0", "--execute"]):
                with self.assertRaises(SystemExit):
                    RECOVERY.main()
            self.assertEqual(self.deletes, [])
            for namespace, name, _, _, _, _ in RECOVERY.TARGETS:
                with patch.object(sys, "argv", ["recovery", "--expected-sha", SHA,
                                                "--target", f"{namespace}/{name}", "--execute",
                                                "--fence-confirmation", "zimaboard-2 powered off"]):
                    RECOVERY.main()
        self.assertEqual(len(self.deletes), 3)
        for (path, options), (namespace, name, uid, _, _, _) in zip(self.deletes, RECOVERY.TARGETS):
            self.assertEqual(path, f"/api/v1/namespaces/{namespace}/pods/{name}")
            self.assertEqual(options["gracePeriodSeconds"], 0)
            self.assertEqual(options["preconditions"], {"uid": uid})


if __name__ == "__main__":
    unittest.main()
