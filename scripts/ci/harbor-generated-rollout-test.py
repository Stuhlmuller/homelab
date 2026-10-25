#!/usr/bin/env python3
"""Check the generated-Pod rollover only touches controller-owned active proxies."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "clusters/homelab/apps/octelium-enterprise/harbor-generated-rollout.py"
SPEC = importlib.util.spec_from_file_location("harbor_generated_rollout", SOURCE)
rollout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollout)


class GeneratedRolloutTests(unittest.TestCase):
    def setUp(self):
        self.deployment = {"metadata": {"name": "svc-affine-default", "generation": 3,
                                        "ownerReferences": [{"kind": "ConfigMap", "name": "svc-affine-default"}]},
                           "spec": {"replicas": 1, "selector": {"matchLabels": {"octelium.com/svc": "affine.default"}}},
                           "status": {"observedGeneration": 3, "updatedReplicas": 1, "availableReplicas": 1}}
        self.pod = {"metadata": {"labels": {"octelium.com/svc": "affine.default"}},
                    "spec": {"initContainers": [{"image": "ghcr.io/octelium/octelium-vigil:0.35.0"}],
                             "containers": [{"image": "harbor.stinkyboi.com/mirror/example@sha256:abc"}]},
                    "status": {"phase": "Running"}}

    def test_scope_and_current_images(self):
        self.assertTrue(rollout.generated(self.deployment))
        self.assertTrue(rollout.current_upstream(self.deployment, [self.pod]))
        historical = {**self.pod, "status": {"phase": "Succeeded"}}
        unrelated = {**self.pod, "metadata": {"labels": {"octelium.com/svc": "other"}}}
        self.assertFalse(rollout.current_upstream(self.deployment, [historical, unrelated]))
        self.assertFalse(rollout.generated({**self.deployment, "metadata": {"name": "emergency-octelium-login"}}))
        broad = {**self.deployment, "spec": {**self.deployment["spec"], "selector": {"matchLabels": {}}}}
        with self.assertRaisesRegex(RuntimeError, "unexpected Pod selector"):
            rollout.current_upstream(broad, [self.pod])

    def test_admission_probe_requires_pinned_harbor_result(self):
        target = ("harbor.stinkyboi.com/mirror/ghcr.io/octelium/octelium-vigil:0.35.0"
                  "@sha256:a8d60479c8d7c0e1deb63c9ef33bb3bb0701b2cf589bc709a2bdef6e5a3f2390")
        with patch.object(rollout, "api", return_value={"spec": {"containers": [{"image": target}]}}) as request:
            rollout.wait_for_admission()
        self.assertEqual(request.call_args.args[0], "POST")
        self.assertIn("dryRun=All", request.call_args.args[1])

    def test_rollout_waits_for_old_pod_to_leave(self):
        harbor_pod = {**self.pod, "spec": {"containers": [{"image": "harbor.stinkyboi.com/mirror/example@sha256:abc"}]}}
        with patch.object(rollout, "api", side_effect=[{}, self.deployment]), \
                patch.object(rollout, "list_pods", return_value=[harbor_pod]):
            rollout.rollout(self.deployment)


if __name__ == "__main__":
    unittest.main()
