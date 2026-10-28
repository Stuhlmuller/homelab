#!/usr/bin/env python3
"""Offline failure fixtures for the held Istio 1.28 chart-source lane."""

import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("istio-upgrade-gate.py")
SPEC = importlib.util.spec_from_file_location("istio_upgrade_gate", SOURCE)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
CANDIDATE = json.loads(GATE.CANDIDATE.read_text())
BASELINE = json.loads((SOURCE.parent / "fixtures/istio-application-1.27.3.json").read_text())


def rendered(phase=0):
    manifest = copy.deepcopy(BASELINE)
    for index in range(phase):
        manifest["spec"]["sources"][index]["targetRevision"] = "1.28.10"
    return {"inputs": {"manifest": manifest}}


class IstioUpgradeGateTest(unittest.TestCase):
    def authorize(self, change, phase=0):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Path(temporary) / "istio/argocd/tfplan.json"
            plan.parent.mkdir(parents=True)
            plan.write_text(json.dumps({"resource_changes": [
                {"type": "kubernetes_manifest", "change": change},
            ]}))
            GATE.authorize_plan(Path(temporary), rendered(phase), phase)

    def test_disabled_source_and_each_ordered_prefix(self):
        for phase in range(7):
            with self.subTest(phase=phase):
                candidate = copy.deepcopy(CANDIDATE)
                candidate["phase"] = phase
                candidate["activationEnabled"] = phase > 0
                self.assertEqual(GATE.check_candidate(candidate), phase)
                GATE.check_sources(rendered(phase), phase)

    def test_candidate_rejects_pin_order_or_phase_escape(self):
        for change in (
            {"phase": True},
            {"phase": 2},
            {"activationEnabled": True},
            {"chartRepository": "https://unreviewed.invalid/charts"},
        ):
            with self.subTest(change=change):
                candidate = copy.deepcopy(CANDIDATE)
                candidate.update(change)
                with self.assertRaises(ValueError):
                    GATE.check_candidate(candidate)
        for mutation in (
            lambda value: value["components"].reverse(),
            lambda value: value["components"][0].update(archiveSha256="0" * 64),
            lambda value: value["components"].pop(),
        ):
            candidate = copy.deepcopy(CANDIDATE)
            mutation(candidate)
            with self.assertRaises(ValueError):
                GATE.check_candidate(candidate)

    def test_render_rejects_unordered_or_unpinned_sources(self):
        for mutation in (
            lambda value: value["inputs"]["manifest"]["spec"]["sources"][1].update(
                targetRevision="1.28.10"),
            lambda value: value["inputs"]["manifest"]["spec"]["sources"][0].update(
                repoURL="https://unreviewed.invalid/charts"),
            lambda value: value["inputs"]["manifest"]["spec"]["sources"][0].update(
                targetRevision="1.28.11"),
            lambda value: value["inputs"]["manifest"]["spec"]["sources"][2].update(
                helm={"releaseName": "unreviewed"}),
            lambda value: value["inputs"]["manifest"]["spec"]["sources"].pop(),
            lambda value: value["inputs"]["manifest"]["spec"]["syncPolicy"]["automated"].update(
                selfHeal=False),
            lambda value: value["inputs"]["manifest"]["spec"]["sources"][3]["helm"].update(
                parameters=[]),
            lambda value: value["inputs"]["manifest"]["spec"]["sources"].append(
                {"repoURL": "https://unreviewed.invalid/repo", "path": ".", "targetRevision": "main"}),
            lambda value: value["inputs"]["manifest"]["spec"]["sources"][0]["helm"].update(
                valueFiles=["$values/unreviewed.yaml"]),
            lambda value: value["inputs"]["manifest"]["spec"].update(project="default"),
            lambda value: value["inputs"]["manifest"]["spec"]["destination"].update(
                namespace="unreviewed"),
            lambda value: value["inputs"]["manifest"]["spec"]["syncPolicy"].update(
                syncOptions=[]),
        ):
            candidate = rendered(1)
            mutation(candidate)
            with self.assertRaises(ValueError):
                GATE.check_sources(candidate, 1)

    def test_saved_plan_allows_no_op_and_non_source_update(self):
        self.authorize({"actions": ["no-op"]})
        self.authorize({"actions": ["no-op"]}, phase=1)
        baseline = rendered()["inputs"]["manifest"]
        before = copy.deepcopy(baseline)
        before["metadata"]["labels"] = {"example": "drift"}
        self.authorize({"actions": ["update"],
                        "before": {"manifest": before}, "after": {"manifest": baseline}})
        self.authorize({"actions": ["create"], "before": None,
                        "after": {"manifest": baseline}})

    def test_saved_plan_rejects_source_change_and_unknown_state(self):
        before = rendered()["inputs"]["manifest"]
        after = rendered(1)["inputs"]["manifest"]
        for change, phase in (
            ({"actions": ["update"], "before": {"manifest": before},
              "after": {"manifest": after}}, 1),
            ({"actions": ["update"], "before": {"manifest": before},
              "after": {"manifest": before}}, 1),
            ({"actions": ["delete", "create"]}, 0),
            ({"actions": ["update"], "before": None, "after": {"manifest": before}}, 0),
            ({"actions": ["update"], "before": {"manifest": {
                **before, "spec": {**before["spec"], "project": "default"}}},
              "after": {"manifest": before}}, 0),
        ):
            with self.subTest(change=change, phase=phase):
                with self.assertRaises(ValueError):
                    self.authorize(change, phase)

    def test_active_phase_holds_git_backed_values_and_kustomize(self):
        GATE.check_referenced_content(GATE.ROOT, 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "clusters/homelab/apps/istio"
            for name in GATE.REFERENCED_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(GATE.ROOT / name, path)
            GATE.check_referenced_content(root, 1)
            (directory / "values.yaml").write_text("unreviewed values\n")
            GATE.check_referenced_content(root, 0)
            with self.assertRaises(ValueError):
                GATE.check_referenced_content(root, 1)


if __name__ == "__main__":
    unittest.main()
