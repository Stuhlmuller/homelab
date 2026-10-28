#!/usr/bin/env python3
"""Focused fail-closed checks for the protected Dispatcharr capture candidate."""

import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).with_name("dispatcharr-protected-capture.py")
spec = importlib.util.spec_from_file_location("dispatcharr_capture", SOURCE)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def pod(name, uid, *, owner=None, labels=None, volumes=None, phase="Pending", gate=None):
    value = {"kind": "Pod", "metadata": {"name": name, "namespace": "media",
                                      "uid": uid, "labels": labels or {}},
             "spec": {"volumes": volumes or [], "automountServiceAccountToken": False},
             "status": {"phase": phase}}
    if owner:
        value["metadata"]["ownerReferences"] = [owner]
    if gate:
        value["spec"]["schedulingGates"] = [{"name": gate}]
    return value


class FakeClient:
    def __init__(self, listings):
        self.listings = listings

    def get(self, path):
        return self.listings[path]


class ProtectedCaptureTest(unittest.TestCase):
    def setUp(self):
        self.run_id = "a" * 32
        self.barrier = pod(
            "dispatcharr-fence-a-start", "barrier-uid",
            labels={"homelab.dev/dispatcharr-fence": self.run_id,
                    "homelab.dev/fence-phase": "start"},
            gate="homelab.dev/dispatcharr-fence")
        self.job = {"uid": "job-uid", "name": capture.JOB_NAME}
        self.capture_pod = pod(
            "dispatcharr-paired-capture-abcde", "capture-uid",
            owner={"kind": "Job", "uid": "job-uid"},
            labels={"job-name": capture.JOB_NAME}, phase="Succeeded")

    def watch(self, events):
        watch = object.__new__(capture.PodWatch)
        watch.allowed = {}
        watch.capture_job = self.job
        watch.capture_pod = None
        watch.postgres_uid = None
        iterator = iter(events)
        watch.next_event = lambda deadline: next(iterator, None)
        return watch

    def test_capture_pod_then_barrier_proves_stream_order(self):
        watch = self.watch([
            {"type": "ADDED", "object": self.capture_pod},
            {"type": "ADDED", "object": self.barrier},
        ])
        self.assertTrue(watch.scan(1, self.barrier))
        self.assertEqual(watch.capture_pod, ("capture-uid", self.capture_pod["metadata"]["name"]))

    def test_unexpected_writer_event_blocks_before_barrier(self):
        rogue = pod("dispatcharr-rogue", "rogue-uid",
                    volumes=[{"persistentVolumeClaim": {"claimName": "dispatcharr"}}])
        watch = self.watch([
            {"type": "ADDED", "object": rogue},
            {"type": "ADDED", "object": self.barrier},
        ])
        with self.assertRaises(capture.Blocked):
            watch.scan(1, self.barrier)

    def test_watch_error_blocks(self):
        watch = self.watch([{"type": "ERROR", "object": {"kind": "Status", "code": 410}}])
        with self.assertRaises(capture.Blocked):
            watch.scan(1, self.barrier)

    def test_only_pinned_capture_and_barrier_specs_are_accepted(self):
        self.assertEqual(capture.spec_hash(capture._barrier(self.run_id, "start")["spec"]),
                         capture.BARRIER_SPEC_SHA256)
        rendered = capture.Kubectl.local_job(
            None, capture.ROOT /
            "clusters/homelab/apps/dispatcharr/recovery-capture-candidate")
        self.assertEqual(capture.spec_hash(rendered["spec"]),
                         capture.JOB_SPEC_SHA256)

    def test_writer_cronjob_blocks_controller_inventory(self):
        paths = {
            "Deployment": "/apis/apps/v1/namespaces/media/deployments",
            "StatefulSet": "/apis/apps/v1/namespaces/media/statefulsets",
            "DaemonSet": "/apis/apps/v1/namespaces/media/daemonsets",
            "CronJob": "/apis/batch/v1/namespaces/media/cronjobs",
            "Job": "/apis/batch/v1/namespaces/media/jobs",
        }
        values = {}
        for kind, path in paths.items():
            values[path] = {"kind": kind + "List", "metadata": {}, "items": []}
        for kind, name in (("Deployment", "dispatcharr"),
                           ("StatefulSet", "dispatcharr-postgres")):
            values[paths[kind]]["items"].append({
                "kind": kind, "metadata": {"name": name, "namespace": "media",
                                             "uid": name + "-uid", "generation": 1},
                "spec": {"template": {"spec": {"volumes": []}}}})
        self.assertEqual(len(capture._controller_inventory(FakeClient(values))), 2)
        values[paths["CronJob"]]["items"].append({
            "kind": "CronJob", "metadata": {"name": "rogue", "namespace": "media",
                                               "uid": "rogue-uid", "generation": 1},
            "spec": {"jobTemplate": {"spec": {"template": {"spec": {
                "volumes": [{"persistentVolumeClaim": {"claimName": "dispatcharr"}}]
            }}}}}})
        with self.assertRaises(capture.Blocked):
            capture._controller_inventory(FakeClient(values))


if __name__ == "__main__":
    unittest.main()
