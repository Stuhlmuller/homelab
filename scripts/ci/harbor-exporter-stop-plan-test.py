#!/usr/bin/env python3
"""Offline exclusion/selection regressions. No Argo or Kubernetes execution."""

import copy
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "stop", ROOT / "scripts/harbor-exporter-stop-plan.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class StopPlanTests(unittest.TestCase):
    def evidence(self):
        before = next(
            yaml.safe_load_all(
                (
                    ROOT / "clusters/homelab/apps/harbor/vulnerability-exporter.yaml"
                ).read_text()
            )
        )
        after = copy.deepcopy(before)
        after["spec"]["replicas"] = 0
        return {
            "before": before,
            "after": after,
            "stop_sha": "a" * 40,
            "exclusion_receipt": "synthetic-exclusive-window",
            "runtime_receipt": "unexecuted-fixture",
            "application": {
                "apiVersion": "argoproj.io/v1alpha1",
                "kind": "Application",
                "metadata": {
                    "name": "harbor",
                    "namespace": "argocd",
                    "uid": "synthetic",
                    "resourceVersion": "1",
                },
                "spec": {
                    "project": "homelab",
                    "destination": {
                        "server": "https://kubernetes.default.svc",
                        "namespace": "harbor",
                    },
                    "syncPolicy": {
                        "automated": {"enabled": False},
                        "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"],
                    },
                    "sources": [
                        {
                            "repoURL": "https://helm.goharbor.io",
                            "chart": "harbor",
                            "path": ".",
                            "targetRevision": "1.19.2",
                            "helm": {
                                "releaseName": "harbor",
                                "valueFiles": [
                                    "$values/clusters/homelab/apps/harbor/values.yaml"
                                ],
                            },
                        },
                        {
                            "repoURL": m.REPO,
                            "targetRevision": "main",
                            "ref": "values",
                            "path": ".",
                            "directory": {
                                "include": ".argocd-values-ref-placeholder.yaml"
                            },
                        },
                        {
                            "repoURL": m.REPO,
                            "targetRevision": "main",
                            "path": "clusters/homelab/apps/harbor",
                        },
                    ],
                },
            },
        }

    def test_exact_resource_only_no_prune_no_retry(self):
        result = m.plan(self.evidence())
        req = result["request_proposal"]
        self.assertEqual(
            req["resources"],
            [
                {
                    "group": "apps",
                    "kind": "Deployment",
                    "namespace": "harbor",
                    "name": m.NAME,
                }
            ],
        )
        self.assertFalse(req["prune"])
        self.assertEqual(req["retryStrategy"]["limit"], 0)
        self.assertEqual(req["revisions"], ["1.19.2", "a" * 40, "a" * 40])
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["runtime_hook_exclusion_proven"])

    def test_actual_backup_bootstrap_hooks_not_selected(self):
        req = m.plan(self.evidence())["request_proposal"]
        for filename in ("backup-job.yaml", "bootstrap-job.yaml"):
            obj = yaml.safe_load(
                (ROOT / "clusters/homelab/apps/harbor" / filename).read_text()
            )
            self.assertEqual(
                obj["metadata"]["annotations"]["argocd.argoproj.io/hook"], "PostSync"
            )
            selected = {
                "group": obj["apiVersion"].split("/")[0],
                "kind": obj["kind"],
                "namespace": obj["metadata"]["namespace"],
                "name": obj["metadata"]["name"],
            }
            self.assertNotIn(selected, req["resources"])

    def test_automated_null_true_missing_rejected(self):
        for value in (None, True, "false", 0):
            e = self.evidence()
            e["application"]["spec"]["syncPolicy"]["automated"]["enabled"] = value
            with self.assertRaises(ValueError):
                m.plan(e)

    def test_overlapping_operation_rejected(self):
        for phase in ("Running", "Terminating", "Unknown"):
            e = self.evidence()
            e["application"]["status"] = {"operationState": {"phase": phase}}
            with self.assertRaises(ValueError):
                m.plan(e)
        e = self.evidence()
        e["application"]["operation"] = {"sync": {}}
        with self.assertRaises(ValueError):
            m.plan(e)

    def test_full_overlay_wrong_kind_and_hook_annotation_rejected(self):
        for kind in ("Job", "List", "CronJob"):
            e = self.evidence()
            e["after"]["kind"] = kind
            with self.assertRaises(ValueError):
                m.plan(e)
        e = self.evidence()
        e["after"]["metadata"]["annotations"] = {"argocd.argoproj.io/hook": "Sync"}
        with self.assertRaises(ValueError):
            m.plan(e)

    def test_image_mount_and_extra_fields_rejected(self):
        for field in ("image", "volumeMounts", "command"):
            e = self.evidence()
            e["after"]["spec"]["template"]["spec"]["containers"][0][field] = (
                "unexpected"
            )
            with self.assertRaises(ValueError):
                m.plan(e)

    def test_changed_source_plugin_or_ref_rejected(self):
        for key, value in [
            ("targetRevision", "other"),
            ("plugin", {"name": "x"}),
            ("path", "candidate"),
        ]:
            e = self.evidence()
            e["application"]["spec"]["sources"][2][key] = value
            with self.assertRaises(ValueError):
                m.plan(e)

    def test_apply_out_of_sync_only_force_replace_rejected(self):
        for option in ("ApplyOutOfSyncOnly=true", "Replace=true", "Force=true"):
            e = self.evidence()
            e["application"]["spec"]["syncPolicy"]["syncOptions"].append(option)
            with self.assertRaises(ValueError):
                m.plan(e)

    def test_revisions_and_receipts_required(self):
        for key, value in [
            ("stop_sha", "main"),
            ("exclusion_receipt", ""),
            ("runtime_receipt", None),
        ]:
            e = self.evidence()
            e[key] = value
            with self.assertRaises(ValueError):
                m.plan(e)

    def test_execute_refused_before_file_read(self):
        with (
            patch("sys.argv", ["stop", "--execute", "--evidence", "/not-present"]),
            patch.object(Path, "read_text", side_effect=AssertionError),
        ):
            self.assertEqual(m.main(), 1)


if __name__ == "__main__":
    unittest.main()
