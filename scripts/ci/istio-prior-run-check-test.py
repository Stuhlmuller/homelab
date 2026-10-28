#!/usr/bin/env python3
"""Failure fixtures for the Istio prior-phase PR admission check."""

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SOURCE = Path(__file__).with_name("istio-prior-run-check.py")
SPEC = importlib.util.spec_from_file_location("istio_prior_run_check", SOURCE)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
SHA = "a" * 40


def candidate(phase):
    return {"phase": phase, "priorRunId": "12345" if phase else None,
            "harborRunId": "67890" if phase else None,
            "chartRunId": "24680" if phase else None,
            "chartManifestDigests": {chart: "sha256:" + str(index + 1) * 64
                                     for index, chart in enumerate((
                                         "base", "cni", "gateway", "istiod", "ztunnel"))}
            if phase else None,
            "activationEnabled": phase > 0, "from": "1.27.3", "to": "1.28.10",
            "chartRepository": "oci://harbor.stinkyboi.com/mirror/helm",
            "components": [{"chart": "base", "releaseName": "istio-base",
                            "archiveSha256": "b" * 64}]}


def run(stage):
    return {"id": 12345, "head_sha": SHA, "event": "workflow_dispatch",
            "head_branch": "main", "status": "completed", "conclusion": "success",
            "run_attempt": 1, "name": f"Platform {stage} @ {SHA}",
            "path": ".github/workflows/platform-maintenance.yml",
            "display_title": f"Platform {stage} @ {SHA}"}


def harbor_run():
    return {"id": 67890, "head_sha": SHA, "event": "workflow_dispatch",
            "head_branch": "main", "status": "completed", "conclusion": "success",
            "run_attempt": 1, "name": f"Mirror all @ {SHA}",
            "path": ".github/workflows/harbor-mirror.yml",
            "display_title": f"Mirror all @ {SHA}", "jobs": [
                {"name": "Validate Harbor Mirror", "status": "completed", "conclusion": "success",
                 "steps": [{"name": "Validate Harbor Publication Gates", "status": "completed",
                            "conclusion": "success"}]},
                {"name": "Copy Reviewed Public Images", "status": "completed", "conclusion": "success",
                 "steps": [{"name": "Copy And Verify Fixed Public Digests", "status": "completed",
                            "conclusion": "success"}]},
            ]}


def chart_run():
    return {"id": 24680, "head_sha": SHA, "event": "workflow_dispatch",
            "head_branch": "main", "status": "completed", "conclusion": "success",
            "run_attempt": 1, "name": f"Helm charts @ {SHA}",
            "path": ".github/workflows/harbor-helm-charts.yml",
            "display_title": f"Helm charts @ {SHA}", "jobs": [
                {"name": "validate", "status": "completed", "conclusion": "success",
                 "steps": [{"name": "Validate reviewed inventory and publisher",
                            "status": "completed", "conclusion": "success"}]},
                {"name": "publish", "status": "completed", "conclusion": "success",
                 "steps": [{"name": "Upload Istio Chart Digest Receipt",
                            "status": "completed", "conclusion": "success"}]},
            ]}


class PriorRunCheckTest(unittest.TestCase):
    def verify(self, phase, previous=None, selected=None, ancestor=lambda _: True):
        GATE.checked_run(candidate(phase), previous or candidate(phase - 1),
                         selected or run("talos-1.14.4" if phase == 1 else
                                         f"istio-1.28.10-phase-{phase - 1}"), ancestor)

    def test_held_source_needs_no_prior_run(self):
        GATE.checked_run(candidate(0), None, {}, lambda _: False)
        GATE.checked_harbor(candidate(0), {}, lambda _: False, lambda _: False)
        GATE.checked_charts(candidate(0), {}, lambda _: False, lambda _: False)
        for edit in ({"priorRunId": "12345"}, {"activationEnabled": True},
                     {"harborRunId": "67890"}, {"chartRunId": "24680"},
                     {"chartManifestDigests": {}}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                GATE.verify_runs({**candidate(0), **edit}, lambda _: {},
                                 lambda _: False, lambda _: {}, lambda _: False,
                                 lambda _: False)

    def test_each_active_phase_requires_matching_prior_protected_run(self):
        for phase in range(1, 7):
            with self.subTest(phase=phase):
                self.verify(phase)

    def test_unverified_next_phase_merge_is_rejected(self):
        for edit in ({"status": "in_progress"}, {"conclusion": "failure"},
                     {"display_title": f"Platform istio-1.28.10-phase-1 @ {'b' * 40}"},
                     {"head_branch": "feature"}, {"event": "push"}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                self.verify(2, selected={**run("istio-1.28.10-phase-1"), **edit})
        with self.assertRaises(ValueError):
            self.verify(2, ancestor=lambda _: False)

    def test_run_and_source_identity_cannot_be_substituted(self):
        for edit in ({"id": 12346}, {"head_sha": "bad"},
                     {"path": ".github/workflows/other.yml"},
                     {"name": "Platform Maintenance"}, {"run_attempt": 0}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                self.verify(1, selected={**run("talos-1.14.4"), **edit})
        for edit in ({"phase": 2}, {"activationEnabled": True},
                     {"components": []}, {"chartRepository": "https://other.invalid"}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                self.verify(1, previous={**candidate(0), **edit})
        for invalid in (12345, "0", "012345", "not-a-run", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                GATE.checked_run({**candidate(1), "priorRunId": invalid},
                                 candidate(0), run("talos-1.14.4"), lambda _: True)

    def test_prior_phase_must_be_exact_previous_source(self):
        prior = copy.deepcopy(candidate(1))
        prior["components"][0]["archiveSha256"] = "c" * 64
        with self.assertRaises(ValueError):
            self.verify(2, previous=prior)

    def test_full_harbor_run_requires_both_jobs_and_same_bundle(self):
        GATE.checked_harbor(candidate(1), harbor_run(), lambda _: True, lambda _: True)
        for edit in ({"status": "in_progress"}, {"conclusion": "failure"},
                     {"display_title": f"Mirror prometheus @ {SHA}"},
                     {"name": "Harbor Mirror"}, {"head_branch": "feature"},
                     {"path": ".github/workflows/other.yml"}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                GATE.checked_harbor(candidate(1), {**harbor_run(), **edit},
                                    lambda _: True, lambda _: True)
        with self.assertRaises(ValueError):
            GATE.checked_harbor(candidate(1), harbor_run(), lambda _: True, lambda _: False)
        for edit in ({"jobs": harbor_run()["jobs"][:1]},
                     {"jobs": [{**harbor_run()["jobs"][0], "conclusion": "failure"},
                               harbor_run()["jobs"][1]]},
                     {"jobs": [{**harbor_run()["jobs"][0], "steps": []},
                               harbor_run()["jobs"][1]]}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                GATE.checked_harbor(candidate(1), {**harbor_run(), **edit},
                                    lambda _: True, lambda _: True)
        for invalid in (67890, "0", "067890", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                GATE.checked_harbor({**candidate(1), "harborRunId": invalid},
                                    harbor_run(), lambda _: True, lambda _: True)

    def test_chart_publication_needs_exact_scope_jobs_and_bundle(self):
        GATE.checked_charts(candidate(1), chart_run(), lambda _: True, lambda _: True)
        for edit in ({"conclusion": "failure"}, {"head_branch": "feature"},
                     {"path": ".github/workflows/other.yml"},
                     {"display_title": "Helm charts @ " + "b" * 40},
                     {"jobs": chart_run()["jobs"][:1]},
                     {"jobs": [chart_run()["jobs"][0], {
                         **chart_run()["jobs"][1], "steps": [{
                             "name": "Upload Istio Chart Digest Receipt",
                             "status": "completed", "conclusion": "skipped"}]}]}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                GATE.checked_charts(candidate(1), {**chart_run(), **edit},
                                    lambda _: True, lambda _: True)
        with self.assertRaises(ValueError):
            GATE.checked_charts(candidate(1), chart_run(), lambda _: True,
                                lambda _: False)
        with self.assertRaises(ValueError):
            GATE.checked_charts(candidate(1), chart_run(), lambda _: False,
                                lambda _: True)
        for edit in ({"chartRunId": "0"}, {"chartManifestDigests": {}},
                     {"chartManifestDigests": {
                         **candidate(1)["chartManifestDigests"], "base": "sha256:" + "x" * 64}}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                GATE.checked_charts({**candidate(1), **edit}, chart_run(),
                                    lambda _: True, lambda _: True)

    def test_both_prior_runs_are_required(self):
        runs = {"12345": run("talos-1.14.4"), "67890": harbor_run(),
                "24680": chart_run()}
        GATE.verify_runs(candidate(1), runs.__getitem__, lambda _: True,
                         lambda _: candidate(0), lambda _: True, lambda _: True)
        runs["67890"]["conclusion"] = "failure"
        with self.assertRaises(ValueError):
            GATE.verify_runs(candidate(1), runs.__getitem__, lambda _: True,
                             lambda _: candidate(0), lambda _: True, lambda _: True)

    def test_malformed_candidate_fails_before_fetch(self):
        for edit in ({"phase": 7}, {"priorRunId": None}, {"harborRunId": "0"},
                     {"chartRunId": "0"}, {"chartManifestDigests": {}}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                GATE.verify_runs({**candidate(1), **edit},
                                 lambda _: self.fail("run fetched before source validation"),
                                 lambda _: True, lambda _: candidate(0), lambda _: True,
                                 lambda _: True)

    def test_pull_request_base_must_contain_prior_run_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / GATE.CANDIDATE
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(candidate(1)))
            event = root / "event.json"
            event.write_text(json.dumps({"pull_request": {"base": {"sha": "b" * 40}}}))
            environment = {"GH_REPO": GATE.REPOSITORY, "GITHUB_EVENT_NAME": "pull_request",
                           "GITHUB_EVENT_PATH": str(event)}
            with (mock.patch.object(GATE, "ROOT", root),
                  mock.patch.dict(os.environ, environment, clear=True),
                  mock.patch.object(GATE, "command", return_value=json.dumps(candidate(0))) as lookup,
                  mock.patch.object(GATE, "verify_runs",
                                    side_effect=lambda _, __, ___, at, ____, _____: at(SHA)),
                  mock.patch.object(GATE.subprocess, "run",
                                    return_value=SimpleNamespace(returncode=0)) as ancestry):
                self.assertEqual(GATE.main(), 0)
                self.assertEqual(lookup.call_count, 2)
                ancestry.assert_any_call(
                    ["git", "merge-base", "--is-ancestor", SHA, "b" * 40],
                    cwd=root, capture_output=True, timeout=15)
            with (mock.patch.object(GATE, "ROOT", root),
                  mock.patch.dict(os.environ, environment, clear=True),
                  mock.patch.object(GATE, "verify_runs",
                                    side_effect=lambda _, __, ___, at, ____, _____: at(SHA)),
                  mock.patch.object(GATE.subprocess, "run",
                                    return_value=SimpleNamespace(returncode=1))):
                with self.assertRaises(ValueError):
                    GATE.main()
            with (mock.patch.object(GATE, "ROOT", root),
                  mock.patch.dict(os.environ, environment, clear=True),
                  mock.patch.object(GATE, "command", return_value=json.dumps(candidate(2))),
                  mock.patch.object(GATE.subprocess, "run",
                                    return_value=SimpleNamespace(returncode=0))):
                with self.assertRaisesRegex(ValueError, "skip or reverse"):
                    GATE.main()


if __name__ == "__main__":
    unittest.main()
