#!/usr/bin/env python3
"""Require each staged firewall Application pair to match one reviewed phase."""

import json
import runpy
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "IaC/homelab/us-west-2/apps/platform-network-policy/argocd"
CANARY_UNIT = ROOT / "IaC/homelab/us-west-2/apps/platform-network-policy-canary/argocd"
CLEANUP_UNIT = ROOT / "IaC/homelab/us-west-2/apps/platform-network-policy-cleanup/argocd"
POLICY_MANIFEST = ROOT / "clusters/homelab/platform/network-policy/kustomization.yaml"
CANARY_MANIFEST = ROOT / "clusters/homelab/platform/network-policy/canary/kustomization.yaml"
TRAEFIK_GUARD = runpy.run_path(str(ROOT / "scripts/network-policy-cleanup.py"))
EMPTY = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n"
ENFORCER = ("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
            "resources:\n  - daemonset.yaml\n")
FIXTURES = ("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
            "resources:\n  - fixtures.yaml\n")


def check_phase(policy, canary, policy_manifest, canary_manifest,
                traefik_node_selector=None, canary_node=None):
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
        (EMPTY, FIXTURES, dormant, active): "fixture-first-pull",
        # The enforcer never auto-syncs or auto-prunes. Its only mutations use
        # the protected, exact-main Argo sync after live activation/release gates.
        (ENFORCER, FIXTURES, dormant, active): "fixture-qualification",
        (ENFORCER, EMPTY, dormant, empty_active): "fixture-pruned",
        (EMPTY, EMPTY, dormant, empty_active): "firewall-pruned",
        (EMPTY, EMPTY, dormant, dormant): "canary-retired",
    }
    if state not in phases:
        raise ValueError("NetworkPolicy Application pair is not a reviewed GitOps phase")
    if (policy_manifest == EMPTY and
            (not isinstance(canary_node, str) or not canary_node or
             not isinstance(traefik_node_selector, str) or
             not traefik_node_selector or traefik_node_selector == canary_node)):
        raise ValueError("enforcer prune requires Traefik GitOps pinned off canary")
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
        selector = TRAEFIK_GUARD["traefik_node_selector"](
            (ROOT / TRAEFIK_GUARD["TRAEFIK_STACK"]).read_text(),
            ROOT / TRAEFIK_GUARD["TRAEFIK_VALUES"])
        config = json.loads((ROOT / "scripts/config/platform-maintenance.json").read_text())
        phase = check_phase(render(UNIT), render(CANARY_UNIT),
                            POLICY_MANIFEST.read_text(), CANARY_MANIFEST.read_text(),
                            selector, config.get("canary", {}).get("node"))
        self.assertIn(
            phase,
            {"dormant", "fixture-first-pull", "fixture-qualification", "fixture-pruned",
             "firewall-pruned", "canary-retired"})
        if phase in {"fixture-first-pull", "fixture-qualification"}:
            selection = config.get("activationAdmission")
            self.assertIs(config.get("activationEnabled"), True)
            self.assertIsInstance(selection, dict)
            self.assertEqual(set(selection), {"sourceSha", "runId", "versionId"})
            self.assertRegex(selection["sourceSha"], r"^[0-9a-f]{40}$")
            self.assertRegex(selection["runId"], r"^[1-9][0-9]*$")
            self.assertTrue(selection["versionId"] and selection["versionId"] != "null")
        elif phase == "dormant":
            self.assertIs(config.get("activationEnabled"), False)
            self.assertIsNone(config.get("activationAdmission"))

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
            (dormant, active, EMPTY, FIXTURES),
            (dormant, active, ENFORCER, FIXTURES),
            (dormant, empty_active, ENFORCER, EMPTY),
            (dormant, empty_active, EMPTY, EMPTY),
            (dormant, dormant, EMPTY, EMPTY),
        ]
        for policy, canary, policy_source, canary_source in reviewed:
            with self.subTest(policy_source=policy_source, canary_source=canary_source):
                check_phase(policy, canary, policy_source, canary_source,
                            "zimaboard-1", "zimaboard-2")
                if policy_source == EMPTY:
                    for selector, node in ((None, "zimaboard-2"), ("", "zimaboard-2"),
                                           ("zimaboard-2", "zimaboard-2"),
                                           ("zimaboard-1", "zimaboard-1"),
                                           ("zimaboard-1", None)):
                        with self.subTest(selector=selector, node=node), self.assertRaisesRegex(
                                ValueError, "enforcer prune"):
                            check_phase(policy, canary, policy_source, canary_source,
                                        selector, node)
        malformed = [
            (active, active, ENFORCER, FIXTURES),
            (active, empty_active, ENFORCER, EMPTY),
            (empty_active, empty_active, EMPTY, EMPTY),
            (dormant, dormant, ENFORCER, FIXTURES),
            (dormant, active, ENFORCER, EMPTY),
            (dormant, empty_active, ENFORCER, FIXTURES),
            (dormant, active, EMPTY, EMPTY),
            (empty_active, empty_active, ENFORCER, EMPTY),
            (empty_active, dormant, ENFORCER, EMPTY),
            (dormant, dormant, EMPTY, FIXTURES),
            (dormant, dormant, ENFORCER, EMPTY + "# unreviewed\n"),
        ]
        for policy, canary, policy_source, canary_source in malformed:
            with self.subTest(policy_source=policy_source, canary_source=canary_source):
                with self.assertRaisesRegex(ValueError, "reviewed GitOps phase"):
                    check_phase(policy, canary, policy_source, canary_source,
                                "zimaboard-1", "zimaboard-2")
        malformed_automation = app(True, 1, False)
        with self.assertRaisesRegex(ValueError, "unreviewed NetworkPolicy automation"):
            check_phase(dormant, malformed_automation, ENFORCER, FIXTURES)

    def test_traefik_release_wiring_change_requires_guard_review(self):
        stack = (ROOT / TRAEFIK_GUARD["TRAEFIK_STACK"]).read_text()
        with self.assertRaisesRegex(ValueError, "not the reviewed release"):
            TRAEFIK_GUARD["traefik_node_selector"](
                stack + '\n# new Helm override or source revision\n',
                ROOT / TRAEFIK_GUARD["TRAEFIK_VALUES"])


if __name__ == "__main__":
    unittest.main()
