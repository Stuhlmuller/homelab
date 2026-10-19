#!/usr/bin/env python3
"""Check the reviewed Enterprise lifecycle order before any live Argo sync."""

import json
import subprocess
import sys
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/openclaw-enterprise"
UPSTREAM = None
if len(sys.argv) == 3 and sys.argv[1] == "--upstream-root":
    UPSTREAM = Path(sys.argv[2])
    sys.argv[1:] = []


def documents(text):
    result = subprocess.run(["yq", "ea", "-o=json", "-I=0", "[.]", "-"],
                            input=text, text=True, check=True, capture_output=True)
    return [item for item in json.loads(result.stdout) if isinstance(item, dict)]


def helm_chart(*options):
    return documents(subprocess.check_output([
        "helm", "template", "oce", str(UPSTREAM / "deploy/helm/openclaw-enterprise"),
        "--namespace", "openclaw-system", "--values", str(APP / "values.yaml"),
        *options], text=True))


class LifecycleOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = documents((APP / "validation/lifecycle.yaml").read_text())[0]
        cls.local = documents(subprocess.check_output(
            ["kubectl", "kustomize", str(APP)], text=True))
        cls.chart = helm_chart() if UPSTREAM else []

    def test_fixture_tracks_required_failure_paths(self):
        self.assertEqual(self.fixture["release"], "oce")
        self.assertEqual(self.fixture["namespace"], "openclaw-system")
        self.assertEqual(self.fixture["sourceRevision"],
                         json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
                         ["source"]["revision"])
        scenarios = {item["name"]: item for item in self.fixture["scenarios"]}
        self.assertEqual(len(scenarios), len(self.fixture["scenarios"]))
        for name in ("first-install", "partial-first-install", "prior-initialization-active",
                     "prior-initialization-pod-active", "candidate-rejected", "foreign-writer",
                     "worker-scale-conflict", "pod-termination-timeout", "migration-failed",
                     "cancelled-after-quiesce", "successful-upgrade"):
            self.assertIn(name, scenarios)
        for name in ("migration-failed", "cancelled-after-quiesce"):
            self.assertEqual(scenarios[name]["replicasAfterQuiesce"], {"api": 0, "worker": 0})
        self.assertEqual(scenarios["cancelled-after-quiesce"]["expected"],
                         "retry-preflight-then-initialization")
        self.assertNotIn("previousJob", scenarios["cancelled-after-quiesce"])

    def test_preflight_rejects_nonterminal_previous_jobs_and_changed_candidate(self):
        result = subprocess.run(
            ["node", "--experimental-test-module-mocks",
             str(ROOT / "scripts/ci/openclaw-enterprise-preflight-test.mjs")],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "6 preflight fixtures passed\n")

    def test_local_hooks_follow_helm_stages_and_block_migration_on_failure(self):
        expected = {int(weight): set(names) for weight, names in
                    self.fixture["expectedHooks"].items()}
        local = self._hook_names(self.local)
        self.assertEqual(local, {weight: expected[weight] for weight in (-40, -18, -15)})
        for name in ("oce-preflight", "oce-quiesce"):
            job = next(item for item in self.local
                       if item["kind"] == "Job" and item["metadata"]["name"] == name)
            self.assertEqual(job["spec"]["backoffLimit"], 0)
            self.assertEqual(job["spec"]["template"]["spec"]["restartPolicy"], "Never")

    @unittest.skipUnless(UPSTREAM, "supply --upstream-root for pinned stock hook order")
    def test_full_chart_hook_order_and_migration_container_sequence(self):
        self.assertEqual(subprocess.check_output(["git", "rev-parse", "HEAD"],
                         cwd=UPSTREAM, text=True).strip(), self.fixture["sourceRevision"])
        expected = {int(weight): set(names) for weight, names in
                    self.fixture["expectedHooks"].items()}
        self.assertEqual(self._hook_names(self.local + self.chart), expected)
        first = next(item for item in self.chart if item["kind"] == "Job" and
                     item["metadata"]["name"] == "oce-initialization")
        upgrade = next(item for item in helm_chart("--is-upgrade") if item["kind"] == "Job" and
                       item["metadata"]["name"] == "oce-initialization")
        self.assertEqual(first["spec"]["backoffLimit"], 0)
        self.assertEqual(first["spec"]["template"]["spec"]["restartPolicy"], "Never")
        self.assertEqual([item["name"] for item in first["spec"]["template"]["spec"]["initContainers"]],
                         ["migration"])
        self.assertEqual([item["name"] for item in upgrade["spec"]["template"]["spec"]["initContainers"]],
                         ["installation-check", "migration"])
        self.assertEqual([item["name"] for item in first["spec"]["template"]["spec"]["containers"]],
                         ["bootstrap"])

    def _hook_names(self, resources):
        grouped = defaultdict(set)
        for item in resources:
            annotations = item["metadata"].get("annotations", {})
            self.assertFalse(any(key.startswith("argocd.argoproj.io/hook") for key in annotations))
            hook = annotations.get("helm.sh/hook")
            if hook is None:
                continue
            self.assertEqual(hook, "pre-install,pre-upgrade")
            self.assertEqual(annotations.get("helm.sh/hook-delete-policy"),
                             "before-hook-creation")
            grouped[int(annotations["helm.sh/hook-weight"])].add(item["metadata"]["name"])
        return dict(grouped)


if __name__ == "__main__":
    unittest.main()
