#!/usr/bin/env python3
"""Offline HOME-54 version/catalog checks and synthetic RBAC fixtures."""

import importlib.util
import json
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rbac", ROOT / "scripts/kubernetes-rbac-inventory.py")
RBAC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RBAC)


class PatchTests(unittest.TestCase):
    def test_target_shapes_and_catalog(self):
        control = yaml.safe_load((ROOT / ".talos/patches/kubernetes-1.34.12.yaml").read_text())
        worker = yaml.safe_load((ROOT / ".talos/patches/worker-kubernetes-1.34.12.yaml").read_text())
        expected = {"machine": {"kubelet": {"image": "ghcr.io/siderolabs/kubelet:v1.34.12"}},
                    "cluster": {key: {"image": f"registry.k8s.io/{image}:v1.34.12"} for key, image in (
                        ("apiServer", "kube-apiserver"), ("controllerManager", "kube-controller-manager"),
                        ("scheduler", "kube-scheduler"), ("proxy", "kube-proxy"))}}
        self.assertEqual(control, expected)
        self.assertEqual(worker, {"machine": expected["machine"]})
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())["images"]
        evidence = json.loads((ROOT / "docs/kubernetes-1.34.12-image-evidence.json").read_text())["images"]
        self.assertEqual(len(evidence), 5)
        for entry in evidence:
            self.assertIn({"source": entry["source"]}, catalog)
            self.assertRegex(entry["source"], r":v1\.34\.12@sha256:[a-f0-9]{64}$")
            old = entry["source"].split("@")[0].replace("1.34.12", "1.34.11") + "@"
            self.assertTrue(any(row["source"].startswith(old) for row in catalog))


class RBACTests(unittest.TestCase):
    def rule(self, groups=("apps",), resources=("statefulsets",), verbs=("create",), **kwargs):
        return dict(apiGroups=list(groups), resources=list(resources), verbs=list(verbs), **kwargs)

    def test_explicit_pair(self):
        self.assertEqual(len(RBAC.apps_write_hints([
            self.rule(resources=("statefulsets", "controllerrevisions"))])), 2)

    def test_wildcards(self):
        self.assertEqual(len(RBAC.apps_write_hints([
            self.rule(groups=("*",), resources=("*",), verbs=("*",))])), 2)

    def test_other_group_and_read_only(self):
        self.assertEqual(RBAC.apps_write_hints([
            self.rule(groups=("k8s.cni.cncf.io",), resources=("*",), verbs=("*",)),
            self.rule(verbs=("get", "list", "watch"))]), [])

    def test_subresource_is_not_parent_write(self):
        self.assertEqual(RBAC.apps_write_hints([self.rule(resources=("statefulsets/status",))]), [])

    def test_resource_names_preserved(self):
        self.assertEqual(RBAC.apps_write_hints([self.rule(resourceNames=["limited"])])[0]
                         ["resourceNames"], ["limited"])

    def test_missing_and_aggregated_roles_unresolved(self):
        role = {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
                "metadata": {"name": "aggregate"}, "aggregationRule": {"clusterRoleSelectors": []}}
        binding = {"apiVersion": role["apiVersion"], "kind": "RoleBinding",
                   "metadata": {"name": "fixture", "namespace": "test"},
                   "subjects": [{"kind": "Group", "name": "fixture-group"}],
                   "roleRef": {"kind": "ClusterRole", "name": "aggregate"}}
        for docs in ([('binding', binding)], [('role', role), ('binding', binding)]):
            row = RBAC.inventory(docs)["bindings"][0]
            self.assertTrue(row["unresolved"])
            self.assertEqual(row["scope"], "test")
            self.assertEqual(row["subjects"][0]["kind"], "Group")

    def test_role_namespace_and_cluster_binding_scope(self):
        role = {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
                "metadata": {"name": "writer"}, "rules": [self.rule()]}
        binding = {"apiVersion": role["apiVersion"], "kind": "ClusterRoleBinding",
                   "metadata": {"name": "fixture"},
                   "subjects": [{"kind": "ServiceAccount", "name": "writer", "namespace": "test"}],
                   "roleRef": {"kind": "ClusterRole", "name": "writer"}}
        row = RBAC.inventory([('role', role), ('binding', binding)])["bindings"][0]
        self.assertEqual(row["scope"], "*")
        self.assertFalse(row["unresolved"])
        self.assertEqual(row["apps_write_hints"][0]["resource"], "statefulsets")


if __name__ == "__main__":
    unittest.main()
