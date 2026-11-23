#!/usr/bin/env python3
"""Check the generated-Pod rollover only touches controller-owned active proxies."""
from copy import deepcopy
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
                                        "uid": "deployment-uid", "resourceVersion": "23",
                                        "ownerReferences": [{"kind": "ConfigMap", "name": "svc-affine-default"}]},
                           "spec": {"replicas": 1,
                                    "selector": {"matchLabels": {"octelium.com/svc": "affine.default"}},
                                    "template": {"metadata": {}}},
                           "status": {"observedGeneration": 3, "updatedReplicas": 1, "availableReplicas": 1}}
        self.pod = {"metadata": {"labels": {"octelium.com/svc": "affine.default"}},
                    "spec": {"initContainers": [{"image": "ghcr.io/octelium/octelium-vigil:0.35.0"}],
                             "containers": [{"image": "harbor.stinkyboi.com/mirror/example@sha256:abc"}]},
                    "status": {"phase": "Running"}}

    def marked_deployment(self):
        deployment = deepcopy(self.deployment)
        deployment["spec"]["template"]["metadata"]["annotations"] = {
            rollout.ROLLOUT_ANNOTATION: rollout.ROLLOUT_MARKER,
        }
        return deployment

    def ready_mirrored_pod(self):
        return {
            "metadata": {**self.pod["metadata"], "annotations": {
                rollout.ROLLOUT_ANNOTATION: rollout.ROLLOUT_MARKER,
            }},
            "spec": {"containers": [{"image": "harbor.stinkyboi.com/mirror/example@sha256:abc"}]},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
        }

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
        marked = self.marked_deployment()
        ready = self.ready_mirrored_pod()
        terminating = {**self.pod, "metadata": {**self.pod["metadata"], "deletionTimestamp": "terminating"}}
        with patch.object(rollout, "api", side_effect=[self.deployment, {}, marked, marked]) as request, \
                patch.object(rollout, "list_pods", side_effect=[[ready, terminating], [ready]]), \
                patch.object(rollout.time, "sleep"):
            rollout.rollout(self.deployment)
        self.assertEqual([call.args[0] for call in request.call_args_list], ["GET", "PATCH", "GET", "GET"])
        self.assertEqual(request.call_args_list[1].args[2][:2], [
            {"op": "test", "path": "/metadata/uid", "value": "deployment-uid"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "23"},
        ])

    def test_retry_waits_for_marked_replacement_without_patching_again(self):
        marked = self.marked_deployment()
        ready = self.ready_mirrored_pod()
        starting = {**ready, "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "False"}]}}
        with patch.object(rollout, "api", return_value=marked) as request, \
                patch.object(rollout, "list_pods", side_effect=[[starting], [ready]]), \
                patch.object(rollout.time, "sleep"):
            rollout.rollout(marked)
        self.assertEqual([call.args[0] for call in request.call_args_list], ["GET", "GET", "GET"])

    def test_replaced_deployment_is_never_patched(self):
        replacement = {**self.deployment, "metadata": {**self.deployment["metadata"], "uid": "replacement-uid"}}
        with patch.object(rollout, "api", return_value=replacement) as request, \
                self.assertRaisesRegex(RuntimeError, "ownership or activation changed"):
            rollout.rollout(self.deployment)
        self.assertEqual([call.args[0] for call in request.call_args_list], ["GET"])

    def test_main_resumes_the_marked_deployment_even_without_upstream_pods(self):
        marked = self.marked_deployment()
        with patch.object(rollout, "wait_for_admission"), \
                patch.object(rollout, "api", return_value={"items": [marked]}), \
                patch.object(rollout, "list_pods", return_value=[]), \
                patch.object(rollout, "rollout") as execute:
            rollout.main()
        execute.assert_called_once_with(marked)


if __name__ == "__main__":
    unittest.main()
