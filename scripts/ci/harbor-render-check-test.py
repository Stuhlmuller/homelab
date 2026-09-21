#!/usr/bin/env python3
"""Fixtures exercise Kubernetes dependencies and Argo ordering, without Helm pins."""

import copy
import importlib.util
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("harbor_render_check", Path(__file__).with_name("harbor-render-check.py"))
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def resource(kind, name, wave=0, hook=None, namespace="harbor", spec=None):
    annotations = {"argocd.argoproj.io/sync-wave": str(wave)}
    if hook:
        annotations["argocd.argoproj.io/hook"] = hook
    return {"apiVersion": "fixture/v1", "kind": kind,
            "metadata": {"name": name, "namespace": namespace, "annotations": annotations},
            "spec": spec or {}}


def workload(kind="Deployment", wave=0, hook=None, pod=None):
    pod = copy.deepcopy(pod or {"containers": [{"name": "app", "image": "fixture"}]})
    if kind == "Pod":
        spec = pod
    elif kind == "CronJob":
        spec = {"jobTemplate": {"spec": {"template": {"spec": pod}}}}
    else:
        spec = {"template": {"spec": pod}}
    return resource(kind, "consumer", wave, hook, spec=spec)


def volume_pod(kind, name):
    source = {"Secret": ("secret", "secretName"),
              "ConfigMap": ("configMap", "name"),
              "PersistentVolumeClaim": ("persistentVolumeClaim", "claimName")}[kind]
    return {"containers": [{"name": "app", "image": "fixture"}],
            "volumes": [{"name": "input", source[0]: {source[1]: name}}]}


class HarborRenderPrerequisites(unittest.TestCase):
    def test_required_volume_resources_must_exist(self):
        for kind in CHECK.PREREQUISITES:
            with self.subTest(kind=kind):
                errors = CHECK.validate([workload(pod=volume_pod(kind, "missing"))])
                self.assertTrue(any(f"{kind} harbor/missing" in error for error in errors))

    def test_prerequisite_in_another_namespace_does_not_satisfy_reference(self):
        resources = [workload(pod=volume_pod("Secret", "shared")),
                     resource("Secret", "shared", namespace="another")]
        self.assertTrue(CHECK.validate(resources))

    def test_later_wave_cannot_supply_required_volume(self):
        for kind in CHECK.PREREQUISITES:
            with self.subTest(kind=kind):
                resources = [workload(wave=-2, pod=volume_pod(kind, "input")),
                             resource(kind, "input", wave=-1)]
                self.assertTrue(any("before its producer" in error for error in CHECK.validate(resources)))

    def test_same_or_earlier_wave_is_valid(self):
        for wave in (-5, 0):
            resources = [workload(pod=volume_pod("ConfigMap", "input")),
                         resource("ConfigMap", "input", wave=wave)]
            self.assertEqual(CHECK.validate(resources), [])

    def test_postsync_workload_can_use_high_wave_normal_resource(self):
        resources = [workload(kind="Job", wave=-5, hook="PostSync", pod=volume_pod("ConfigMap", "input")),
                     resource("ConfigMap", "input", wave=100)]
        self.assertEqual(CHECK.validate(resources), [])

    def test_postsync_producer_cannot_satisfy_normal_workload(self):
        resources = [workload(wave=10, pod=volume_pod("Secret", "input")),
                     resource("Secret", "input", wave=-100, hook="PostSync")]
        self.assertTrue(any("before its producer" in error for error in CHECK.validate(resources)))

    def test_controller_generated_secrets_satisfy_consumers(self):
        pod = volume_pod("Secret", "runtime-secret")
        pod["volumes"].append({"name": "signing", "secret": {"secretName": "signing-secret"}})
        resources = [workload(pod=pod),
                     resource("ExternalSecret", "runtime", wave=-5,
                              spec={"target": {"name": "runtime-secret"}}),
                     resource("Certificate", "signing", wave=-4,
                              spec={"secretName": "signing-secret"})]
        self.assertEqual(CHECK.validate(resources), [])

    def test_external_secret_default_target_name_is_supported(self):
        resources = [workload(pod=volume_pod("Secret", "runtime")),
                     resource("ExternalSecret", "runtime", wave=-1)]
        self.assertEqual(CHECK.validate(resources), [])

    def test_noncreating_external_secret_cannot_bootstrap_secret(self):
        for policy in ("Merge", "None"):
            resources = [workload(pod=volume_pod("Secret", "runtime")),
                         resource("ExternalSecret", "runtime", wave=-1,
                                  spec={"target": {"creationPolicy": policy}})]
            self.assertTrue(CHECK.validate(resources))

    def test_controller_order_must_also_precede_consumer(self):
        resources = [workload(wave=-2, pod=volume_pod("Secret", "signing-secret")),
                     resource("Certificate", "signing", wave=-1,
                              spec={"secretName": "signing-secret"})]
        self.assertTrue(any("before its producer" in error for error in CHECK.validate(resources)))

    def test_environment_references_are_checked_in_init_and_regular_containers(self):
        for container_field in ("containers", "initContainers"):
            for ref_field, kind in (("secretKeyRef", "Secret"), ("configMapKeyRef", "ConfigMap")):
                with self.subTest(container_field=container_field, ref_field=ref_field):
                    pod = {"containers": [{"name": "app", "image": "fixture"}]}
                    pod[container_field] = [{"name": "uses-input", "image": "fixture", "env": [
                        {"name": "SETTING", "valueFrom": {ref_field: {"name": "input", "key": "value"}}}
                    ]}]
                    self.assertTrue(CHECK.validate([workload(pod=pod)]))
                    self.assertEqual(CHECK.validate([workload(pod=pod), resource(kind, "input")]), [])

    def test_envfrom_and_projected_sources_are_checked(self):
        pod = {"containers": [{"name": "app", "image": "fixture", "envFrom": [
            {"secretRef": {"name": "settings"}}, {"configMapRef": {"name": "defaults"}}
        ]}], "volumes": [{"name": "bundle", "projected": {"sources": [
            {"secret": {"name": "token"}}, {"configMap": {"name": "configuration"}}
        ]}}]}
        errors = CHECK.validate([workload(pod=pod)])
        self.assertEqual(len(errors), 4)

    def test_optional_refs_do_not_block_bootstrap(self):
        pod = {"containers": [{"name": "app", "image": "fixture", "envFrom": [
            {"secretRef": {"name": "optional", "optional": True}}
        ], "env": [{"name": "SETTING", "valueFrom": {
            "configMapKeyRef": {"name": "optional", "key": "value", "optional": True}
        }}]}], "volumes": [{"name": "optional", "secret": {
            "secretName": "optional", "optional": True
        }}, {"name": "projected", "projected": {"sources": [
            {"configMap": {"name": "optional", "optional": True}}
        ]}}]}
        self.assertEqual(CHECK.validate([workload(pod=pod)]), [])

    def test_cronjob_and_statefulset_templates_are_checked(self):
        for kind in ("CronJob", "StatefulSet", "Job", "DaemonSet", "Pod"):
            with self.subTest(kind=kind):
                self.assertTrue(CHECK.validate([workload(kind=kind, pod=volume_pod("Secret", "missing"))]))

    def test_skipped_resource_is_not_a_prerequisite(self):
        resources = [workload(pod=volume_pod("ConfigMap", "input")),
                     resource("ConfigMap", "input", hook="Skip")]
        self.assertTrue(CHECK.validate(resources))

    def test_empty_render_is_not_success(self):
        self.assertTrue(CHECK.validate([]))


if __name__ == "__main__":
    unittest.main()
