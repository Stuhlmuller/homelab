#!/usr/bin/env python3
"""Exercise the release writer fence without Kubernetes credentials."""

import copy
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "clusters/homelab/apps/openclaw-enterprise/quiesce.py"
SPEC = importlib.util.spec_from_file_location("oce_quiesce", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def deployment(component):
    labels = {**MODULE.LABELS, "app.kubernetes.io/component": component}
    return {"metadata": {"name": MODULE.deployment_name(component),
                         "namespace": MODULE.NAMESPACE, "uid": f"uid-{component}",
                         "generation": 1, "labels": labels},
            "spec": {"replicas": 1, "selector": {"matchLabels": labels},
                     "template": {"metadata": {"labels": labels}}},
            "status": {"observedGeneration": 1}}


def pod(component, phase="Running", owner=True):
    name = MODULE.deployment_name(component) + "-abcde"
    return {"metadata": {"name": name + "-12345",
                         "labels": {**MODULE.LABELS, "app.kubernetes.io/component": component},
                         "ownerReferences": [{"controller": True, "kind": "ReplicaSet",
                                              "name": name if owner else "foreign"}]},
            "status": {"phase": phase}}


class FakeAPI:
    def __init__(self, present=("api", "worker"), conflict=None, scale_version="1"):
        self.deployments = {component: deployment(component) for component in present}
        self.conflict = conflict
        self.scale_version = scale_version
        self.updates = []

    def __call__(self, path, method="GET", body=None, missing=False):
        if "/scale" in path:
            component = next(component for component in MODULE.COMPONENTS
                             if MODULE.deployment_name(component) in path)
            current = self.deployments[component]
            if method == "GET":
                metadata = {"uid": current["metadata"]["uid"]}
                if self.scale_version is not None:
                    metadata["resourceVersion"] = self.scale_version
                return {"metadata": metadata, "spec": {"replicas": current["spec"]["replicas"]}}
            if self.conflict == component:
                raise RuntimeError("scale resourceVersion conflict")
            current["spec"]["replicas"] = body["spec"]["replicas"]
            self.updates.append(component)
            return body
        for component in MODULE.COMPONENTS:
            if path.endswith("/" + MODULE.deployment_name(component)):
                return copy.deepcopy(self.deployments.get(component))
        raise AssertionError(path)


class QuiesceContract(unittest.TestCase):
    def setUp(self):
        self.original_api, self.original_pods = MODULE.api, MODULE.pods

    def tearDown(self):
        MODULE.api, MODULE.pods = self.original_api, self.original_pods

    def test_empty_first_install_requires_zero_matching_pods(self):
        fake = FakeAPI(present=())
        MODULE.api, MODULE.pods = fake, lambda: []
        MODULE.main()
        self.assertEqual(fake.updates, [])
        MODULE.pods = lambda: [pod("api")]
        with self.assertRaisesRegex(RuntimeError, "unexpected API/worker Pods"):
            MODULE.main()

    def test_partial_deployment_and_foreign_writer_block_before_scale(self):
        fake = FakeAPI(present=("api",))
        MODULE.api, MODULE.pods = fake, lambda: []
        with self.assertRaisesRegex(RuntimeError, "only one"):
            MODULE.main()
        fake = FakeAPI()
        MODULE.api, MODULE.pods = fake, lambda: [pod("api", owner=False)]
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            MODULE.main()
        self.assertEqual(fake.updates, [])

    def test_both_exact_writers_reach_zero_before_migration(self):
        fake = FakeAPI()
        MODULE.api = fake
        MODULE.pods = lambda: [pod(component) for component in MODULE.COMPONENTS
                               if fake.deployments[component]["spec"]["replicas"]]
        MODULE.main()
        self.assertEqual(fake.updates, ["api", "worker"])
        self.assertEqual({component: fake.deployments[component]["spec"]["replicas"]
                          for component in MODULE.COMPONENTS}, {"api": 0, "worker": 0})

    def test_conflict_blocks_migration_even_if_first_writer_stopped(self):
        fake = FakeAPI(conflict="worker")
        MODULE.api, MODULE.pods = fake, lambda: []
        with self.assertRaisesRegex(RuntimeError, "conflict"):
            MODULE.main()
        self.assertEqual(fake.updates, ["api"])
        self.assertEqual(fake.deployments["worker"]["spec"]["replicas"], 1)

    def test_missing_scale_resource_version_blocks_before_writes(self):
        for version in (None, "", "0"):
            with self.subTest(version=version):
                fake = FakeAPI(scale_version=version)
                MODULE.api, MODULE.pods = fake, lambda: []
                with self.assertRaisesRegex(RuntimeError, "resourceVersion"):
                    MODULE.main()
                self.assertEqual(fake.updates, [])

    def test_retry_after_partial_scale_finishes_fence(self):
        fake = FakeAPI(conflict="worker")
        MODULE.api = fake
        MODULE.pods = lambda: [pod(component) for component in MODULE.COMPONENTS
                               if fake.deployments[component]["spec"]["replicas"]]
        with self.assertRaisesRegex(RuntimeError, "conflict"):
            MODULE.main()
        fake.conflict = None
        MODULE.main()
        self.assertEqual(fake.updates, ["api", "worker"])
        self.assertEqual({component: fake.deployments[component]["spec"]["replicas"]
                          for component in MODULE.COMPONENTS}, {"api": 0, "worker": 0})

    def test_pod_timeout_leaves_writers_stopped_and_retry_is_idempotent(self):
        fake = FakeAPI()
        MODULE.api, MODULE.pods = fake, lambda: [pod("api")]
        with patch.object(MODULE.time, "monotonic", side_effect=[0, 1, 180]), \
             patch.object(MODULE.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "did not terminate"):
                MODULE.main()
        self.assertEqual(fake.updates, ["api", "worker"])
        self.assertEqual({component: fake.deployments[component]["spec"]["replicas"]
                          for component in MODULE.COMPONENTS}, {"api": 0, "worker": 0})
        MODULE.pods = lambda: []
        MODULE.main()
        self.assertEqual(fake.updates, ["api", "worker"])

    def test_unknown_writer_state_blocks_before_scale(self):
        fake = FakeAPI()
        MODULE.api, MODULE.pods = fake, lambda: [pod("api", phase="Unknown")]
        with self.assertRaisesRegex(RuntimeError, "unknown writer state"):
            MODULE.main()
        self.assertEqual(fake.updates, [])


if __name__ == "__main__":
    unittest.main()
