#!/usr/bin/env python3
"""Require the staged firewall Application to stay dormant until admission."""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "IaC/live/argocd-apps/platform-network-policy"
CANARY_UNIT = ROOT / "IaC/live/argocd-apps/platform-network-policy-canary"
CLEANUP_UNIT = ROOT / "IaC/live/argocd-apps/platform-network-policy-cleanup"


class NetworkPolicyRegistrationTests(unittest.TestCase):
    def test_generated_application_is_dormant(self):
        result = subprocess.run(
            ["terragrunt", "--working-dir", str(UNIT), "--log-disable",
             "render", "--json", "--write=false", "--no-color"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        app = json.loads(result.stdout)["inputs"]["manifest"]
        self.assertEqual(app["metadata"]["name"], "platform-network-policy")
        self.assertEqual(app["spec"]["destination"]["namespace"], "kube-system")
        self.assertEqual(app["spec"]["sources"], [{
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": "clusters/homelab/platform/network-policy",
            "targetRevision": "main"}])
        sync = app["spec"]["syncPolicy"]
        self.assertFalse(sync["automated"]["enabled"])
        self.assertFalse(sync["automated"]["prune"])
        self.assertIn("ServerSideApply=true", sync["syncOptions"])

    def test_cleanup_application_is_separate_and_dormant(self):
        result = subprocess.run(
            ["terragrunt", "--working-dir", str(CLEANUP_UNIT), "--log-disable",
             "render", "--json", "--write=false", "--no-color"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        app = json.loads(result.stdout)["inputs"]["manifest"]
        self.assertEqual(app["metadata"]["name"], "platform-network-policy-cleanup")
        self.assertEqual(app["spec"]["destination"]["namespace"], "kube-system")
        self.assertEqual(app["spec"]["sources"], [{
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": "clusters/homelab/platform/network-policy/cleanup",
            "targetRevision": "main"}])
        self.assertFalse(app["spec"]["syncPolicy"]["automated"]["enabled"])
        self.assertFalse(app["spec"]["syncPolicy"]["automated"]["prune"])

    def test_canary_application_is_separate_dormant_and_empty(self):
        result = subprocess.run(
            ["terragrunt", "--working-dir", str(CANARY_UNIT), "--log-disable",
             "render", "--json", "--write=false", "--no-color"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        app = json.loads(result.stdout)["inputs"]["manifest"]
        self.assertEqual(app["metadata"]["name"], "platform-network-policy-canary")
        self.assertEqual(app["spec"]["project"], "homelab")
        self.assertEqual(app["spec"]["destination"]["namespace"],
                         "network-policy-canary")
        self.assertEqual(app["spec"]["sources"], [{
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": "clusters/homelab/platform/network-policy/canary",
            "targetRevision": "main"}])
        automated = app["spec"]["syncPolicy"]["automated"]
        self.assertFalse(automated["enabled"])
        self.assertFalse(automated["prune"])
        self.assertFalse(automated["allowEmpty"])
        project = subprocess.run(
            ["yq", "-o=json", ".", str(ROOT / "clusters/homelab/argocd/"
                                       "self-management/appproject.yaml")],
            capture_output=True, text=True, check=True, timeout=30,
        )
        self.assertIn({"server": "https://kubernetes.default.svc",
                       "namespace": "network-policy-canary"},
                      json.loads(project.stdout)["spec"]["destinations"])


if __name__ == "__main__":
    unittest.main()
