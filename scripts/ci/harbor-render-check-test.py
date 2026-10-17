#!/usr/bin/env python3
"""Fixtures exercise Kubernetes dependencies and Argo ordering, without Helm pins."""

import copy
import importlib.util
import json
import tempfile
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


def workload(kind="Deployment", wave=0, hook=None, pod=None, name="consumer"):
    pod = copy.deepcopy(pod or {"containers": [{"name": "app", "image": "fixture"}]})
    if kind == "Pod":
        spec = pod
    elif kind == "CronJob":
        spec = {"jobTemplate": {"spec": {"template": {"spec": pod}}}}
    else:
        spec = {"template": {"spec": pod}}
    return resource(kind, name, wave, hook, spec=spec)


def harbor_pull_secret():
    secret = resource("ExternalSecret", CHECK.HARBOR_PULL_SECRET, wave=-5, spec={
        "refreshPolicy": "OnChange",
        "secretStoreRef": {"kind": "ClusterSecretStore", "name": "aws-ssm"},
        "target": {
            "name": CHECK.HARBOR_PULL_SECRET,
            "creationPolicy": "Owner",
            "deletionPolicy": "Retain",
            "template": {
                "engineVersion": "v2",
                "type": "kubernetes.io/dockerconfigjson",
                "data": {".dockerconfigjson": CHECK.HARBOR_PULL_TEMPLATE},
            },
        },
        "data": [{"secretKey": "password", "remoteRef": {
            "key": CHECK.HARBOR_PULL_PARAMETER,
            "conversionStrategy": "Default",
            "decodingStrategy": "None",
            "metadataPolicy": "None",
        }}],
    })
    secret["metadata"]["annotations"]["homelab.stuhlmuller.dev/generated-secret-revision"] = "v1"
    return secret


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

    def test_enrolled_harbor_image_requires_verified_receipt(self):
        resources = [workload(pod={"containers": [{
            "name": "app", "image": "harbor.stinkyboi.com/homelab/pilot:latest"
        }]})]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            state = root / "state.json"
            config.write_text(json.dumps({
                "images": [{"image_id": "pilot", "destination":
                            "harbor.stinkyboi.com/homelab/pilot:latest"}],
                "consumers": [{"image_id": "pilot", "automation_status": "enrolled"}],
            }))
            state.write_text(json.dumps({"receipts": {}}))
            self.assertTrue(CHECK.receipt_errors(resources, config, state))
            state.write_text(json.dumps({"receipts": {"pilot": {
                "destination_ref": "harbor.stinkyboi.com/homelab/pilot:latest",
                "consumer_access": True,
            }}}))
            self.assertEqual(CHECK.receipt_errors(resources, config, state), [])

    def test_harbor_pull_secret_is_scoped_and_attached_to_exporter(self):
        pod = {"containers": [{"name": "app", "image": "fixture"}],
               "imagePullSecrets": [{"name": CHECK.HARBOR_PULL_SECRET}]}
        secret = harbor_pull_secret()
        resources = [workload(name="harbor-vulnerability-exporter", pod=pod), secret]
        self.assertEqual(CHECK.harbor_pull_secret_errors(resources), [])
        secret["metadata"]["annotations"].pop("homelab.stuhlmuller.dev/generated-secret-revision")
        errors = CHECK.harbor_pull_secret_errors(resources)
        self.assertTrue(any("revision refresh" in error for error in errors))
        secret = harbor_pull_secret()
        resources[1] = secret
        secret["spec"]["data"] = []
        errors = CHECK.harbor_pull_secret_errors(resources)
        self.assertTrue(any("read only" in error for error in errors))

    def test_harbor_pull_secret_and_exporter_reference_cannot_both_disappear(self):
        resources = [workload(name="harbor-vulnerability-exporter", pod={
            "containers": [{"name": "app", "image": "fixture"}]})]
        errors = CHECK.harbor_pull_secret_errors(resources)
        self.assertTrue(any("expected one ExternalSecret" in error for error in errors))
        self.assertTrue(any("must reference harbor-pull" in error for error in errors))

    def test_harbor_pull_secret_is_never_mounted_or_injected(self):
        pod = {"containers": [{"name": "app", "image": "fixture"}],
               "imagePullSecrets": [{"name": CHECK.HARBOR_PULL_SECRET}]}
        resources = [workload(name="harbor-vulnerability-exporter", pod=pod), harbor_pull_secret()]
        cases = {
            "mount": (lambda value: value.setdefault("volumes", []).append({
                "name": "pull", "secret": {"secretName": CHECK.HARBOR_PULL_SECRET}}), "must not mount"),
            "environment": (lambda value: value["containers"][0].setdefault("envFrom", []).append({
                "secretRef": {"name": CHECK.HARBOR_PULL_SECRET}}), "must not expose"),
            "init environment": (lambda value: value.setdefault("initContainers", []).append({
                "name": "leak", "env": [{"name": "PULL", "valueFrom": {
                    "secretKeyRef": {"name": CHECK.HARBOR_PULL_SECRET, "key": ".dockerconfigjson"}}}]}), "must not expose"),
            "ephemeral environment": (lambda value: value.setdefault("ephemeralContainers", []).append({
                "name": "leak", "env": [{"name": "PULL", "valueFrom": {
                    "secretKeyRef": {"name": CHECK.HARBOR_PULL_SECRET, "key": ".dockerconfigjson"}}}]}), "must not expose"),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(resources)
                mutate(changed[0]["spec"]["template"]["spec"])
                errors = CHECK.harbor_pull_secret_errors(changed)
                self.assertTrue(any(expected in error for error in errors))

    def test_enrolled_native_harbor_image_requires_harbor_pull(self):
        image = "harbor.stinkyboi.com/homelab/chainguard-python:latest"
        pod = {"containers": [{"name": "app", "image": image}]}
        resources = [workload(name="harbor-vulnerability-exporter", pod=pod)]
        rendered_pod = resources[0]["spec"]["template"]["spec"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            state = root / "state.json"
            config.write_text(json.dumps({
                "images": [{"image_id": "chainguard-python", "source": "cgr.dev/chainguard/python:latest",
                            "destination": image}],
                "consumers": [{"image_id": "chainguard-python", "automation_status": "enrolled"}],
            }))
            state.write_text(json.dumps({"receipts": {"chainguard-python": {
                "destination_ref": image, "consumer_access": True,
            }}}))
            errors = CHECK.receipt_errors(resources, config, state)
            self.assertTrue(any("must pull native Harbor images" in error for error in errors))
            rendered_pod["imagePullSecrets"] = [{"name": "wrong"}]
            errors = CHECK.receipt_errors(resources, config, state)
            self.assertTrue(any("must pull native Harbor images" in error for error in errors))
            rendered_pod["imagePullSecrets"] = [{"name": CHECK.HARBOR_PULL_SECRET}]
            self.assertEqual(CHECK.receipt_errors(resources, config, state), [])


if __name__ == "__main__":
    unittest.main()
