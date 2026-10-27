#!/usr/bin/env python3
"""Require each staged firewall Application pair to match one reviewed phase."""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "IaC/homelab/us-west-2/apps/platform-network-policy/argocd"
CANARY_UNIT = ROOT / "IaC/homelab/us-west-2/apps/platform-network-policy-canary/argocd"
CLEANUP_UNIT = ROOT / "IaC/homelab/us-west-2/apps/platform-network-policy-cleanup/argocd"
POLICY_MANIFEST = ROOT / "clusters/homelab/platform/network-policy/kustomization.yaml"
CANARY_MANIFEST = ROOT / "clusters/homelab/platform/network-policy/canary/kustomization.yaml"
EMPTY = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n"
ENFORCER = ("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
            "resources:\n  - daemonset.yaml\n")
FIXTURES = ("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
            "resources:\n  - fixtures.yaml\n")


def check_phase(policy, canary, policy_manifest, canary_manifest):
    """Match complete source states; private receipts remain runtime-stage gates."""
    def automated(app):
        sync = app["spec"]["syncPolicy"]
        if sync["syncOptions"] != ["CreateNamespace=false", "ServerSideApply=true"]:
            raise ValueError("unreviewed NetworkPolicy sync options")
        values = sync["automated"]
        if (set(values) != {"enabled", "prune", "allowEmpty", "selfHeal"} or
                any(type(value) is not bool for value in values.values()) or
                values["selfHeal"] is not True):
            raise ValueError("unreviewed NetworkPolicy automation")
        return (values["enabled"], values["prune"], values["allowEmpty"])

    state = (policy_manifest, canary_manifest, automated(policy), automated(canary))
    dormant = (False, False, False)
    active = (True, True, False)
    empty_active = (True, True, True)
    phases = {
        (ENFORCER, EMPTY, dormant, dormant): "dormant",
        (ENFORCER, FIXTURES, active, active): "fixture-qualification",
        (ENFORCER, EMPTY, active, empty_active): "fixture-pruned",
        (EMPTY, EMPTY, empty_active, empty_active): "firewall-pruned",
        (EMPTY, EMPTY, empty_active, dormant): "canary-retired",
    }
    if state not in phases:
        raise ValueError("NetworkPolicy Application pair is not a reviewed GitOps phase")
    return phases[state]


def render(unit):
    result = subprocess.run(
        ["terragrunt", "--working-dir", str(unit), "--log-disable",
         "render", "--json", "--write=false", "--no-color"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)["inputs"]["manifest"]


class NetworkPolicyRegistrationTests(unittest.TestCase):
    def test_generated_application_is_registered(self):
        app = render(UNIT)
        self.assertEqual(app["metadata"]["name"], "platform-network-policy")
        self.assertEqual(app["spec"]["destination"]["namespace"], "kube-system")
        self.assertEqual(app["spec"]["sources"], [{
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": "clusters/homelab/platform/network-policy",
            "targetRevision": "main"}])

    def test_source_pair_matches_reviewed_phase(self):
        self.assertIn(
            check_phase(render(UNIT), render(CANARY_UNIT),
                        POLICY_MANIFEST.read_text(), CANARY_MANIFEST.read_text()),
            {"dormant", "fixture-qualification", "fixture-pruned",
             "firewall-pruned", "canary-retired"})

    def test_cleanup_application_is_separate_and_dormant(self):
        app = render(CLEANUP_UNIT)
        self.assertEqual(app["metadata"]["name"], "platform-network-policy-cleanup")
        self.assertEqual(app["spec"]["destination"]["namespace"], "kube-system")
        self.assertEqual(app["spec"]["sources"], [{
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": "clusters/homelab/platform/network-policy/cleanup",
            "targetRevision": "main"}])
        self.assertFalse(app["spec"]["syncPolicy"]["automated"]["enabled"])
        self.assertFalse(app["spec"]["syncPolicy"]["automated"]["prune"])

    def test_canary_application_is_separate(self):
        app = render(CANARY_UNIT)
        self.assertEqual(app["metadata"]["name"], "platform-network-policy-canary")
        self.assertEqual(app["spec"]["project"], "homelab")
        self.assertEqual(app["spec"]["destination"]["namespace"],
                         "network-policy-canary")
        self.assertEqual(app["spec"]["sources"], [{
            "repoURL": "https://github.com/Stuhlmuller/homelab.git",
            "path": "clusters/homelab/platform/network-policy/canary",
            "targetRevision": "main"}])
        project = subprocess.run(
            ["yq", "-o=json", ".", str(ROOT / "clusters/homelab/argocd/"
                                       "self-management/appproject.yaml")],
            capture_output=True, text=True, check=True, timeout=30,
        )
        self.assertIn({"server": "https://kubernetes.default.svc",
                       "namespace": "network-policy-canary"},
                      json.loads(project.stdout)["spec"]["destinations"])

    def test_only_exact_reviewed_source_phases_pass(self):
        def app(enabled, prune, allow_empty):
            return {"spec": {"syncPolicy": {
                "syncOptions": ["CreateNamespace=false", "ServerSideApply=true"],
                "automated": {"enabled": enabled, "prune": prune,
                              "allowEmpty": allow_empty, "selfHeal": True}}}}

        dormant, active, empty_active = (app(False, False, False),
                                         app(True, True, False),
                                         app(True, True, True))
        reviewed = [
            (dormant, dormant, ENFORCER, EMPTY),
            (active, active, ENFORCER, FIXTURES),
            (active, empty_active, ENFORCER, EMPTY),
            (empty_active, empty_active, EMPTY, EMPTY),
            (empty_active, dormant, EMPTY, EMPTY),
        ]
        for policy, canary, policy_source, canary_source in reviewed:
            with self.subTest(policy_source=policy_source, canary_source=canary_source):
                check_phase(policy, canary, policy_source, canary_source)
        malformed = [
            (dormant, dormant, ENFORCER, FIXTURES),
            (dormant, active, ENFORCER, FIXTURES),
            (dormant, active, ENFORCER, EMPTY),
            (dormant, empty_active, ENFORCER, EMPTY),
            (dormant, empty_active, ENFORCER, FIXTURES),
            (empty_active, empty_active, ENFORCER, EMPTY),
            (empty_active, dormant, ENFORCER, EMPTY),
            (dormant, dormant, EMPTY, EMPTY),
            (dormant, dormant, ENFORCER, EMPTY + "# unreviewed\n"),
        ]
        for policy, canary, policy_source, canary_source in malformed:
            with self.subTest(policy_source=policy_source, canary_source=canary_source):
                with self.assertRaisesRegex(ValueError, "reviewed GitOps phase"):
                    check_phase(policy, canary, policy_source, canary_source)
        malformed_automation = app(True, 1, False)
        with self.assertRaisesRegex(ValueError, "unreviewed NetworkPolicy automation"):
            check_phase(dormant, malformed_automation, ENFORCER, FIXTURES)


if __name__ == "__main__":
    unittest.main()
