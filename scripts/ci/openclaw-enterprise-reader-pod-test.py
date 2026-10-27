#!/usr/bin/env python3
"""Offline safety fixtures for dormant Enterprise reader Pod rendering."""

import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


RENDER = module("oce_reader_pod", "scripts/ci/openclaw-enterprise-reader-pod.py")
READER = module("oce_reader_archive", "scripts/ci/openclaw-enterprise-reader-archive.py")
FIXTURE = module("oce_capture_fixture", "scripts/ci/openclaw-enterprise-capture-test.py")
CAPTURE = FIXTURE.CAPTURE
SHA = FIXTURE.SHA
UIDS = FIXTURE.UIDS
BACKUP_ID = "b" * 64
IMAGE = ("harbor.stinkyboi.com/homelab/homelab-oce-restore:homelab-" +
         SHA + "@sha256:" + "c" * 64)


class ReaderPods(unittest.TestCase):
    def setUp(self):
        self.fixture = FIXTURE.CaptureAssembler(
            "test_assembles_complete_private_tree_without_authorizing_publication")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.pods = RENDER.render(SHA, BACKUP_ID, IMAGE, self.fixture.gateway_name)

    def observation(self, kind):
        pod = copy.deepcopy(self.pods[kind])
        pod["metadata"]["uid"] = UIDS[kind + "Pod"]
        keys = ("journal", "bootstrap") if kind == "operator" else ("gateway",)
        claims = {key: self.fixture.claims[key] for key in keys}
        result = {"schemaVersion": 1, "sourceSha": SHA,
                  "readerPod": pod, "claims": claims}
        if kind == "tenant":
            result["tenantPods"] = {"kind": "PodList",
                                    "metadata": {"resourceVersion": "11"},
                                    "items": [pod]}
        return result

    def verify(self, kind, observation):
        uid = UIDS[kind + "Pod"]
        keys = ("journal", "bootstrap") if kind == "operator" else ("gateway",)
        expected = {key: UIDS[key] for key in keys}
        namespace = READER.NAMESPACES[kind]
        self.assertEqual(READER.validate_observation(
            kind, SHA, uid, expected, observation, IMAGE), namespace)
        CAPTURE._reader_pod(observation["readerPod"], namespace, uid,
                            {key: self.fixture.claims[key]["metadata"]["name"]
                             for key in keys}, SHA, IMAGE)

    def test_rendered_pods_match_both_reader_and_capture_boundaries(self):
        self.assertEqual(set(self.pods), {"operator", "tenant"})
        for kind in self.pods:
            with self.subTest(kind=kind):
                pod = self.pods[kind]
                spec = pod["spec"]
                self.assertEqual(pod["metadata"]["annotations"], {
                    "homelab.dev/source-sha": SHA,
                    "homelab.dev/backup-id": BACKUP_ID})
                self.assertEqual(spec["containers"][0]["image"], IMAGE)
                self.assertEqual(spec["containers"][0]["command"],
                                 ["/bin/sleep", "7200"])
                self.assertFalse(spec["automountServiceAccountToken"])
                self.assertFalse(spec["hostNetwork"])
                self.assertFalse(spec["hostPID"])
                self.assertFalse(spec["hostIPC"])
                self.assertNotIn("env", spec["containers"][0])
                self.assertNotIn("envFrom", spec["containers"][0])
                self.assertNotIn("args", spec["containers"][0])
                self.assertEqual(len(spec["containers"]), 1)
                self.assertTrue(all("persistentVolumeClaim" in volume
                                    for volume in spec["volumes"]))
                self.verify(kind, self.observation(kind))

    def test_foreign_identity_or_unreviewed_image_is_rejected(self):
        inputs = [
            ("a" * 39, BACKUP_ID, IMAGE, self.fixture.gateway_name),
            (SHA, "b" * 63, IMAGE, self.fixture.gateway_name),
            (SHA, BACKUP_ID, IMAGE.replace(SHA, "d" * 40), self.fixture.gateway_name),
            (SHA, BACKUP_ID, IMAGE.replace("harbor.stinkyboi.com", "docker.io"),
             self.fixture.gateway_name),
            (SHA, BACKUP_ID, IMAGE.replace("@sha256:", ":"),
             self.fixture.gateway_name),
            (SHA, BACKUP_ID, IMAGE, "gateway-state-foreign"),
        ]
        for args in inputs:
            with self.subTest(args=args):
                with self.assertRaises(RENDER.Blocked):
                    RENDER.render(*args)

    def test_namespace_claim_uid_and_added_mounts_fail_existing_validators(self):
        for kind in self.pods:
            for change in ("namespace", "claim", "uid", "extra-volume", "subpath",
                           "command", "env", "probe", "port", "image"):
                with self.subTest(kind=kind, change=change):
                    observed = self.observation(kind)
                    pod = observed["readerPod"]
                    if change == "namespace":
                        pod["metadata"]["namespace"] = "foreign"
                    elif change == "claim":
                        pod["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"] = "foreign"
                    elif change == "uid":
                        pod["metadata"]["uid"] = UIDS["gateway"]
                    elif change == "extra-volume":
                        pod["spec"]["volumes"].append({"name": "secret", "secret": {
                            "secretName": "foreign"}})
                    elif change == "subpath":
                        pod["spec"]["containers"][0]["volumeMounts"][0]["subPath"] = "partial"
                    elif change == "command":
                        pod["spec"]["containers"][0]["command"] = ["/bin/sh", "-c", "cat /source/gateway/*"]
                    elif change == "env":
                        pod["spec"]["containers"][0]["env"] = [{"name": "SECRET",
                                                                    "value": "leak"}]
                    elif change == "probe":
                        pod["spec"]["containers"][0]["livenessProbe"] = {
                            "exec": {"command": ["/bin/sh", "-c", "cat /source/gateway/*"]}}
                    elif change == "port":
                        pod["spec"]["containers"][0]["ports"] = [{"containerPort": 8080}]
                    else:
                        pod["spec"]["containers"][0]["image"] = IMAGE[:-64] + "d" * 64
                    with self.assertRaises(READER.Blocked):
                        self.verify(kind, observed)
                    with self.assertRaises(CAPTURE.Blocked):
                        self.verify_capture_only(kind, observed)

    def test_expected_publication_reference_must_match_exact_digest(self):
        foreign = IMAGE[:-64] + "d" * 64
        for kind in self.pods:
            with self.subTest(kind=kind):
                observed = self.observation(kind)
                keys = ("journal", "bootstrap") if kind == "operator" else ("gateway",)
                with self.assertRaises(READER.Blocked):
                    READER.validate_observation(
                        kind, SHA, UIDS[kind + "Pod"],
                        {key: UIDS[key] for key in keys}, observed, foreign)
                with self.assertRaises(CAPTURE.Blocked):
                    CAPTURE._reader_pod(
                        observed["readerPod"], READER.NAMESPACES[kind],
                        UIDS[kind + "Pod"],
                        {key: self.fixture.claims[key]["metadata"]["name"]
                         for key in keys}, SHA, foreign)

    def verify_capture_only(self, kind, observation):
        keys = ("journal", "bootstrap") if kind == "operator" else ("gateway",)
        CAPTURE._reader_pod(observation["readerPod"], READER.NAMESPACES[kind],
                            UIDS[kind + "Pod"],
                            {key: self.fixture.claims[key]["metadata"]["name"]
                             for key in keys}, SHA, IMAGE)


if __name__ == "__main__":
    unittest.main()
