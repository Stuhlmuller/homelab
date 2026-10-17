#!/usr/bin/env python3
"""Check the controller access contract cannot read Secrets or mutate workloads."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Access(unittest.TestCase):
    def setUp(self):
        self.documents = json.loads(subprocess.check_output([
            "yq", "ea", "-o=json", "-I=0", "[.]",
            str(ROOT / "clusters/homelab/apps/cordium/runner-controller-access.yaml")], text=True))

    def test_write_scope_is_networkpolicies_in_workspace_namespace_only(self):
        writes = []
        for document in self.documents:
            if document["kind"] == "Role":
                for rule in document["rules"]:
                    self.assertNotIn("*", rule["resources"])
                    self.assertNotIn("*", rule["verbs"])
                    self.assertNotIn("secrets", rule["resources"])
                    for verb in rule["verbs"]:
                        if verb not in ("get", "list", "watch"):
                            writes.append((document["metadata"]["namespace"], rule["resources"], verb))
        self.assertEqual(writes, [("cordium", ["networkpolicies"], "create"),
                                  ("cordium", ["networkpolicies"], "delete")])
        self.assertFalse(any(document["kind"] in ("ClusterRole", "ClusterRoleBinding") for document in self.documents))

    def test_subjects_are_only_segregated_controller_and_no_automatic_token(self):
        for document in self.documents:
            if document["kind"] == "RoleBinding":
                self.assertEqual(document["subjects"], [{"kind": "ServiceAccount", "name": "cordium-runner-controller", "namespace": "cordium-runners"}])
        account = next(document for document in self.documents if document["kind"] == "ServiceAccount")
        self.assertIs(account["automountServiceAccountToken"], False)

    def test_kubeconfig_references_projected_files_without_embedded_credentials(self):
        text = next(document for document in self.documents if document["kind"] == "ConfigMap")["data"]["config"]
        config = json.loads(subprocess.check_output(["yq", "-o=json", ".", "-"], input=text, text=True))
        self.assertEqual(config["users"][0]["user"], {"tokenFile": "/var/run/cordium-runner-api/token"})
        self.assertEqual(config["clusters"][0]["cluster"]["certificate-authority"], "/var/run/cordium-runner-api/ca.crt")
        self.assertEqual(config["clusters"][0]["cluster"]["server"], "https://10.1.0.199:6443")


if __name__ == "__main__":
    unittest.main()
