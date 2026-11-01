#!/usr/bin/env python3
"""Protect the firewall's explicit Argo sync and prune order."""

import argparse
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SUT = runpy.run_path(str(ROOT / "scripts/network-policy-manual-sync.py"))
GLOBALS = SUT["execute"].__globals__
SHA = "a" * 40


class ManualSyncTests(unittest.TestCase):
    def fixture(self, phase, *, already=False, guard_failure=False,
                ds_absent=False, tracked_failure=False):
        events = []

        def event(name):
            events.append(name)

        def traefik_guard(*_):
            event("traefik-guard")
            if guard_failure:
                raise ValueError("ingress remains on canary")

        def tracked_resources(*_, **__):
            event("tracked-resources")
            if tracked_failure:
                raise ValueError("unreviewed tracked resource")
            return set()

        cleanup = {
            "require_current_main": lambda *_: event("current-main"),
            "require_traefik_off_canary": traefik_guard,
            "command": lambda *_: "{}" if phase == "prune" and not ds_absent else "",
            "ENFORCER": "kube-router-network-policy",
        }
        platform = {
            "protected_context": lambda *_: event("protected"),
            "require_reviewed_execution_config": lambda *_: event("config"),
            "validate_config": lambda *_: {
                "activationEnabled": True,
                "canary": {"node": "zimaboard-2"}},
        }
        changes = {
            "PLATFORM": platform,
            "CLEANUP": cleanup,
            "source_phase": lambda *_: phase,
            "selected_placement": lambda *_: {"nodeUid": "node-uid", "bootID": "boot-id"},
            "require_policy_application": lambda: event("policy-app"),
            "require_canary_application": lambda *_: event("canary-app"),
            "require_isolated_node": lambda *_: event("isolated"),
            "require_live_enforcer": lambda *_: event("live-enforcer"),
            "require_reviewed_pods": lambda *_: event("reviewed-pods"),
            "require_enforcer_absent": lambda: event("enforcer-absent"),
            "require_firewall_resources_absent": lambda: event("firewall-resources-absent"),
            "require_tracked_firewall_resources": tracked_resources,
            "live_firewall_rbac": lambda: set(),
            "require_synced": lambda *_, **__: event("synced"),
            "already_synced": lambda *_, **__: already,
            "ACTIVATION": {"execute": lambda *_: event("capacity")},
        }

        def run(command, **_):
            event("argocd-sync" if command[:3] == ["argocd", "app", "sync"] else
                  "argocd-wait")
            events.append(command)

        args = argparse.Namespace(phase=phase, expected_sha=SHA, bucket="private-bucket")
        with patch.dict(GLOBALS, changes), patch.object(SUT["subprocess"], "run", side_effect=run):
            if guard_failure or tracked_failure:
                with self.assertRaisesRegex(ValueError, "ingress remains" if guard_failure
                                            else "unreviewed tracked"):
                    SUT["execute"](args)
            else:
                SUT["execute"](args)
        return events

    def test_enforcer_capacity_precedes_sync_and_never_prunes(self):
        events = self.fixture("enforcer")
        self.assertLess(events.index("capacity"), events.index("argocd-sync"))
        self.assertLess(events.index("argocd-sync"), events.index("argocd-wait"))
        command = next(item for item in events if isinstance(item, list) and item[:3] ==
                       ["argocd", "app", "sync"])
        self.assertEqual(command[5:9], ["--revisions", SHA, "--source-positions", "1"])
        self.assertNotIn("--prune", command)

    def test_enforcer_retry_with_synced_ready_daemonset_skips_capacity_and_sync(self):
        events = self.fixture("enforcer", already=True)
        self.assertIn("live-enforcer", events)
        self.assertNotIn("capacity", events)
        self.assertNotIn("argocd-sync", events)

    def test_prune_checks_live_ingress_before_argocd_and_uses_explicit_prune(self):
        events = self.fixture("prune")
        self.assertLess(events.index("traefik-guard"), events.index("argocd-sync"))
        command = next(item for item in events if isinstance(item, list) and item[:3] ==
                       ["argocd", "app", "sync"])
        self.assertIn("--prune", command)
        self.assertEqual([command[index + 1] for index, value in enumerate(command[:-1])
                          if value == "--resource"], list(SUT["PRUNE_FILTERS"]))
        self.assertNotIn("capacity", events)

    def test_prune_blocks_before_sync_when_traefik_remains_on_canary(self):
        events = self.fixture("prune", guard_failure=True)
        self.assertIn("traefik-guard", events)
        self.assertNotIn("argocd-sync", events)

    def test_prune_blocks_extra_tracked_resource_before_sync(self):
        events = self.fixture("prune", tracked_failure=True)
        self.assertIn("reviewed-pods", events)
        self.assertNotIn("argocd-sync", events)

    def test_partial_prune_retries_when_daemonset_absent(self):
        events = self.fixture("prune", ds_absent=True)
        self.assertIn("enforcer-absent", events)
        self.assertIn("reviewed-pods", events)
        self.assertIn("argocd-sync", events)

    def test_prune_retry_requires_absent_daemonset_and_keeps_taint(self):
        events = self.fixture("prune", already=True)
        self.assertIn("firewall-resources-absent", events)
        self.assertIn("isolated", events)
        self.assertNotIn("argocd-sync", events)

    def test_source_phase_rejects_unreviewed_manifest_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "policy.yaml"
            canary = root / "canary.yaml"
            policy.write_text(SUT["ENFORCER_SOURCE"])
            canary.write_text(SUT["FIXTURE_SOURCE"])
            cleanup = {"command": lambda *args: (policy if "policy.yaml" in args[-1]
                                                   else canary).read_text()}
            with patch.dict(GLOBALS, {"ROOT": root, "POLICY": policy, "CANARY": canary,
                                      "CLEANUP": cleanup}):
                self.assertEqual(SUT["source_phase"](SHA), "enforcer")
                canary.write_text(SUT["EMPTY_SOURCE"])
                with self.assertRaisesRegex(ValueError, "reviewed source phase"):
                    SUT["source_phase"](SHA)

    def test_prune_inventory_rejects_foreign_pod(self):
        placement = {"systemDaemonSetPods": [
            {"namespace": "kube-system", "name": "system-0", "uid": "system-uid"}]}
        owner = [{"kind": "DaemonSet", "controller": True, "name": "system"}]
        pods = [
            {"metadata": {"namespace": "kube-system", "name": "system-0",
                          "uid": "system-uid", "ownerReferences": owner},
             "spec": {"nodeName": "zimaboard-2"}},
            {"metadata": {"namespace": "default", "name": "foreign",
                          "uid": "foreign-uid", "ownerReferences": owner},
             "spec": {"nodeName": "zimaboard-2"}},
        ]
        cleanup = {
            "kubernetes_json": lambda *_: {"items": pods},
            "complete_items": lambda response, _: response["items"],
        }
        with patch.dict(GLOBALS, {"CLEANUP": cleanup}):
            with self.assertRaisesRegex(ValueError, "foreign Pod"):
                SUT["require_reviewed_pods"]("zimaboard-2", placement)

    def test_prune_inventory_accepts_only_reviewed_system_pod(self):
        placement = {"systemDaemonSetPods": [
            {"namespace": "kube-system", "name": "system-0", "uid": "system-uid"}]}
        pod = {"metadata": {"namespace": "kube-system", "name": "system-0",
                            "uid": "system-uid", "ownerReferences": [
                                {"kind": "DaemonSet", "controller": True,
                                 "name": "system"}]},
               "spec": {"nodeName": "zimaboard-2"}}
        cleanup = {
            "kubernetes_json": lambda *_: {"items": [pod]},
            "complete_items": lambda response, _: response["items"],
        }
        with patch.dict(GLOBALS, {"CLEANUP": cleanup}):
            SUT["require_reviewed_pods"]("zimaboard-2", placement)

    def test_prune_requires_same_node_boot_id(self):
        node = {"metadata": {"name": "zimaboard-2", "uid": "node-uid",
                             "labels": {"isolation": "true"}},
                "spec": {"taints": [{"key": "isolation", "value": "true",
                                     "effect": "NoSchedule"}]},
                "status": {"nodeInfo": {"bootID": "new-boot"}}}
        cleanup = {"kubernetes_json": lambda *_: node,
                   "CANARY": "isolation", "ready": lambda *_: True}
        with patch.dict(GLOBALS, {"CLEANUP": cleanup}):
            with self.assertRaisesRegex(ValueError, "reviewed isolation"):
                SUT["require_isolated_node"]("zimaboard-2", {
                    "nodeUid": "node-uid", "bootID": "old-boot"})

    def test_prune_rejects_extra_tracked_resource(self):
        resources = [
            {"group": group, "kind": kind, "namespace": namespace, "name": name}
            for group, kind, namespace, name in SUT["TRACKED_FIREWALL"]
        ]
        resources.append({"group": "", "kind": "ConfigMap", "namespace": "kube-system",
                          "name": "unreviewed"})
        with self.assertRaisesRegex(ValueError, "unreviewed or missing"):
            SUT["require_tracked_firewall_resources"](
                {"status": {"resources": resources}})

    def test_partial_prune_allows_only_reviewed_remaining_rbac(self):
        resources = [{"group": "rbac.authorization.k8s.io",
                      "kind": "ClusterRole", "name": "kube-router-network-policy"}]
        tracked = SUT["require_tracked_firewall_resources"](
            {"status": {"resources": resources}}, allow_partial=True)
        self.assertEqual(tracked, {
            ("rbac.authorization.k8s.io", "ClusterRole", "", "kube-router-network-policy")})


if __name__ == "__main__":
    unittest.main()
