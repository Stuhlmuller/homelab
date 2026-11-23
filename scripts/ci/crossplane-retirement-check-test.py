#!/usr/bin/env python3
"""Test the exact initial Crossplane retirement gate without a cluster."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "crossplane-retirement-check.py"
spec = importlib.util.spec_from_file_location("retirement", path)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Preflight(unittest.TestCase):
    def setUp(self):
        self.app = {
            "spec": {
                "sources": [{"repoURL": "https://charts.crossplane.io/stable",
                             "chart": "crossplane", "targetRevision": "2.3.3"}],
                "destination": {"namespace": check.NAMESPACE},
            },
            "status": {
                "sync": {"revisions": ["2.3.3"], "status": "Synced"},
                "health": {"status": "Healthy"},
                "resources": [
                    {"group": group, "kind": kind, "namespace": namespace, "name": name}
                    for group, kind, namespace, name in check.CHART_RESOURCES
                ],
            },
        }
        self.resources = {
            "crd": [{"metadata": {"name": f"{plural}.{group}"}, "spec": {"group": group}}
                    for group, plurals in check.CRDS.items() for plural in plurals],
            "deployment": [{"metadata": {"name": name}, "spec": {"replicas": 0}, "status": {}}
                           for name in ("crossplane", "crossplane-rbac-manager")],
            "daemonsets,statefulsets,jobs,cronjobs": [],
            "pod": [{"status": {"phase": "Succeeded"}}],
            "pvc": [],
            "pv": [{"spec": {"claimRef": {"namespace": "unrelated"}}}],
        }
        self.resources.update({f"{plural}.{group}": []
                               for group, plurals in check.CRDS.items() for plural in plurals})
        for kind, (name, payload) in check.DEFAULTS.items():
            self.resources[kind] = [{"metadata": {"name": name}, "spec": payload}]
        self.enterContext(patch.object(check, "kubectl", return_value=check.API_SERVER))
        self.enterContext(patch.object(check, "read", return_value=self.app))
        self.enterContext(patch.object(check, "listing", side_effect=lambda kind, *_: self.resources[kind]))

    def test_all_pinned_types_and_defaults(self):
        with patch("builtins.print") as report:
            check.preflight()
        self.assertIn("21 core CRDs", report.call_args.args[0])

    def test_unexpected_package(self):
        self.resources["providers.pkg.crossplane.io"] = [{"metadata": {"name": "unexpected"}}]
        with self.assertRaisesRegex(ValueError, "unexpected instance count"):
            check.preflight()

    def test_provider_managed_crd_in_another_group(self):
        self.resources["crd"].append(
            {"metadata": {"name": "widgets.vendor.example", "managedFields": [{"manager": "crossplane"}]},
             "spec": {"group": "vendor.example"}},
        )
        with self.assertRaisesRegex(ValueError, "differ from the pinned core set"):
            check.preflight()

    def test_core_name_does_not_excuse_a_changed_object(self):
        lock = self.resources["locks.pkg.crossplane.io"][0]
        for delta in ({"packages": [{"name": "provider"}]}, {"metadata": {"name": "lock", "finalizers": ["owned"]}}):
            with self.subTest(delta=delta):
                self.resources["locks.pkg.crossplane.io"] = [{**lock, **delta}]
                with self.assertRaisesRegex(ValueError, "differs from the built-in default"):
                    check.preflight()

    def test_argo_tracks_a_crd(self):
        self.app["status"]["resources"].append(
            {"group": "apiextensions.k8s.io", "kind": "CustomResourceDefinition"},
        )
        with self.assertRaisesRegex(ValueError, "unexpected kind"):
            check.preflight()

    def test_argo_tracks_wrong_resource_of_allowed_kind(self):
        tracked = self.app["status"]["resources"]
        role = next(resource for resource in tracked if resource["kind"] == "ClusterRole")
        role["name"] = "unexpected-crossplane-role"
        with self.assertRaisesRegex(ValueError, "resource identities differ"):
            check.preflight()

    def test_active_pod_or_existing_volume(self):
        self.resources["pod"][0]["status"]["phase"] = "Running"
        with self.assertRaisesRegex(ValueError, "non-terminal Pod"):
            check.preflight()
        self.resources["pod"] = []
        self.resources["pv"][0]["spec"]["claimRef"]["namespace"] = check.NAMESPACE
        with self.assertRaisesRegex(ValueError, "volume claims"):
            check.preflight()


if __name__ == "__main__":
    unittest.main()
