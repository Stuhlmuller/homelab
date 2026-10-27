#!/usr/bin/env python3
"""Offline authenticated list/watch and continuity-gap fixtures for T051."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "oce_pod_watch", ROOT / "scripts/ci/openclaw-enterprise-pod-watch.py")
WATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WATCH)


def pod_list(rv, pods=(), **metadata):
    return {"kind": "PodList", "metadata": {"resourceVersion": rv, **metadata},
            "items": list(pods)}


def bookmark(rv):
    return {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": rv}}}


def pod_event(kind, rv, name="reader"):
    return {"type": kind, "object": {"kind": "Pod", "metadata": {
        "namespace": WATCH.NAMESPACE, "name": name,
        "uid": "55555555-5555-4555-8555-555555555555",
        "resourceVersion": rv}}}


class FakeProcess:
    def __init__(self):
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.exited = False

    def emit(self, *events):
        os.write(self.write_fd, b"\n".join(json.dumps(event).encode()
                                         for event in events) + b"\n")

    def end(self):
        os.close(self.write_fd)
        self.write_fd = None

    def poll(self):
        return 0 if self.exited else None

    def terminate(self):
        self.exited = True
        if self.write_fd is not None:
            self.end()

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        return 0


class FakeKubectl:
    def __init__(self, lists, version=("1", "35")):
        self.lists = list(lists)
        self.version = version
        self.commands = []
        self.process = FakeProcess()

    def run(self, command, **kwargs):
        self.commands.append(command)
        if "version" in command:
            value = {"serverVersion": {"major": self.version[0],
                                        "minor": self.version[1]}}
        else:
            value = self.lists.pop(0)
        return subprocess.CompletedProcess(command, 0, json.dumps(value).encode())

    def popen(self, command, **kwargs):
        self.commands.append(command)
        return self.process


class TenantPodWatch(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="oce-pod-watch-")
        self.addCleanup(temp.cleanup)
        self.kubeconfig = Path(temp.name) / "config"
        self.kubeconfig.write_text("protected test fixture")
        self.kubeconfig.chmod(0o600)

    def watch(self, lists, version=("1", "35"), timeout=0.05):
        fake = FakeKubectl(lists, version)
        adapter = WATCH.KubectlPodWatch(
            self.kubeconfig, timeout_seconds=timeout, run=fake.run,
            popen=fake.popen)
        self.addCleanup(fake.process.stdout.close)
        self.addCleanup(fake.process.terminate)
        self.addCleanup(adapter.close)
        return adapter, fake

    def start(self, adapter, fake):
        first = adapter.list_pods()
        adapter.open_from(WATCH.NAMESPACE, first["metadata"]["resourceVersion"])
        fake.process.emit(bookmark(first["metadata"]["resourceVersion"]))
        self.assertEqual(adapter.drain_until(first["metadata"]["resourceVersion"]),
                         [bookmark(first["metadata"]["resourceVersion"])])

    def test_authenticated_unfiltered_list_and_exact_watch_rv(self):
        adapter, fake = self.watch([pod_list("10"), pod_list("12")])
        self.start(adapter, fake)
        self.assertEqual(fake.commands[1][-1], WATCH.PODS_PATH)
        self.assertEqual(fake.commands[2][-1], WATCH.PODS_PATH +
                         "?watch=1&resourceVersion=10&allowWatchBookmarks=true"
                         "&timeoutSeconds=3600")
        self.assertTrue(all("--kubeconfig" in command for command in fake.commands))
        self.assertFalse(any("fieldSelector" in " ".join(command) or
                             "labelSelector" in " ".join(command) or
                             "limit=" in " ".join(command)
                             for command in fake.commands))
        later = adapter.list_pods()
        fake.process.emit(pod_event("ADDED", "11"), bookmark("12"))
        self.assertEqual(adapter.drain_until(later["metadata"]["resourceVersion"]),
                         [pod_event("ADDED", "11"), bookmark("12")])

    def test_open_requires_own_complete_list_and_secure_config(self):
        adapter, fake = self.watch([pod_list("10")])
        with self.assertRaises(WATCH.WatchGap):
            adapter.open_from(WATCH.NAMESPACE, "10")
        insecure = self.kubeconfig
        insecure.chmod(0o644)
        with self.assertRaises(WATCH.WatchGap):
            WATCH.KubectlPodWatch(insecure)
        insecure.chmod(0o600)

        adapter, fake = self.watch([pod_list("10")])
        adapter.list_pods()
        with self.assertRaises(WATCH.WatchGap):
            adapter.open_from(WATCH.NAMESPACE, "11")

    def test_rejects_partial_or_filtered_looking_list_and_old_server(self):
        for listing in (pod_list("10", **{"continue": "cursor"}),
                        pod_list("10", shardInfo={"count": 2}),
                        pod_list("10", remainingItemCount=1),
                        pod_list("0"),
                        pod_list("10", [{"kind": "Pod", "metadata": {
                            "namespace": "other"}}])):
            with self.subTest(listing=listing):
                adapter, fake = self.watch([listing])
                with self.assertRaises(WATCH.WatchGap):
                    adapter.list_pods()
        adapter, fake = self.watch([pod_list("10")], version=("1", "34"))
        with self.assertRaises(WATCH.WatchGap):
            adapter.list_pods()

    def test_changed_kubeconfig_between_barriers_poisoned(self):
        adapter, fake = self.watch([pod_list("10"), pod_list("12")])
        self.start(adapter, fake)
        self.kubeconfig.write_text("different protected test fixture")
        with self.assertRaisesRegex(WATCH.WatchGap, "kubeconfig changed"):
            adapter.list_pods()
        with self.assertRaises(WATCH.WatchGap):
            adapter.drain_until("12")

    def test_410_eof_timeout_and_reconnect_all_poison(self):
        for events, end in (([{"type": "ERROR", "object": {"kind": "Status",
                               "code": 410}}], False), ([], True), ([], False)):
            with self.subTest(events=events, end=end):
                adapter, fake = self.watch([pod_list("10")])
                first = adapter.list_pods()
                adapter.open_from(WATCH.NAMESPACE, "10")
                if events:
                    fake.process.emit(*events)
                if end:
                    fake.process.end()
                with self.assertRaises(WATCH.WatchGap):
                    adapter.drain_until(first["metadata"]["resourceVersion"])
                with self.assertRaises(WATCH.WatchGap):
                    adapter.open_from(WATCH.NAMESPACE, "10")

    def test_out_of_order_missing_bookmark_and_stale_checkpoint_fail(self):
        adapter, fake = self.watch([pod_list("10"), pod_list("12")])
        self.start(adapter, fake)
        later = adapter.list_pods()
        fake.process.emit(pod_event("ADDED", "11"), pod_event("MODIFIED", "10"))
        with self.assertRaises(WATCH.WatchGap):
            adapter.drain_until(later["metadata"]["resourceVersion"])

        adapter, fake = self.watch([pod_list("10"), pod_list("12")])
        self.start(adapter, fake)
        later = adapter.list_pods()
        fake.process.emit(pod_event("ADDED", "12"))
        with self.assertRaises(WATCH.WatchGap):
            adapter.drain_until(later["metadata"]["resourceVersion"])

        adapter, fake = self.watch([pod_list("10"), pod_list("10")])
        self.start(adapter, fake)
        later = adapter.list_pods()
        fake.process.emit(bookmark("10"))
        with self.assertRaises(WATCH.WatchGap):
            adapter.drain_until(later["metadata"]["resourceVersion"])


if __name__ == "__main__":
    unittest.main()
