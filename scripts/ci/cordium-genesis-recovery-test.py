#!/usr/bin/env python3
"""Offline regression for the stranded Cordium bootstrap identity recovery fence."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import sys
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "cordium-genesis-recovery.py"
SPEC = importlib.util.spec_from_file_location("cordium_recovery", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
UIDS = tuple(f"00000000-0000-0000-0000-{n:012d}" for n in (1, 2, 3))


def fixtures():
    app = {"metadata": {"name": "cordium-bootstrap"},
           "spec": {"syncPolicy": {"automated": {"enabled": False}}},
           "status": {"operationState": {"phase": "Failed", "finishedAt": "fixed"},
                      "sync": {"status": "Synced"}}}
    resources = []
    for (kind, name, _), uid in zip(MODULE.TARGETS, UIDS, strict=True):
        resources.append({"kind": kind, "metadata": {"name": name, "uid": uid,
                          "labels": {"app.kubernetes.io/name": "cordium"},
                          "annotations": {"argocd.argoproj.io/hook": "PostSync"}}})
    return app, [], [], resources


class RecoveryFenceTest(unittest.TestCase):
    def test_exact_finished_failure_is_eligible(self):
        MODULE.validate_snapshot(*fixtures(), UIDS)

    def test_changed_identity_or_unreviewed_resource_is_denied(self):
        for index in range(3):
            for field, value in (("uid", "different"), ("name", "other")):
                with self.subTest(index=index, field=field):
                    app, pods, jobs, resources = copy.deepcopy(fixtures())
                    resources[index]["metadata"][field] = value
                    with self.assertRaises(ValueError):
                        MODULE.validate_snapshot(app, pods, jobs, resources, UIDS)

    def test_active_operation_or_workload_is_denied(self):
        app, pods, jobs, resources = fixtures()
        app["spec"]["syncPolicy"]["automated"]["enabled"] = True
        with self.assertRaises(ValueError):
            MODULE.validate_snapshot(app, pods, jobs, resources, UIDS)
        app, pods, jobs, resources = fixtures()
        app["operation"] = {"sync": {}}
        with self.assertRaises(ValueError):
            MODULE.validate_snapshot(app, pods, jobs, resources, UIDS)
        app, pods, jobs, resources = fixtures()
        app["status"]["operationState"]["phase"] = "Running"
        with self.assertRaises(ValueError):
            MODULE.validate_snapshot(app, pods, jobs, resources, UIDS)
        app, pods, jobs, resources = fixtures()
        pods.append({"spec": {"serviceAccountName": "cordium-genesis"},
                     "status": {"phase": "Running"}})
        with self.assertRaises(ValueError):
            MODULE.validate_snapshot(app, pods, jobs, resources, UIDS)
        app, pods, jobs, resources = fixtures()
        jobs.append({"metadata": {"name": "cordium-genesis"}, "status": {"active": 1}})
        with self.assertRaises(ValueError):
            MODULE.validate_snapshot(app, pods, jobs, resources, UIDS)
        app, pods, jobs, resources = fixtures()
        jobs.append({"metadata": {"name": "renamed-job"}, "status": {"active": 1},
                     "spec": {"template": {"spec": {"serviceAccountName": "cordium-genesis"}}}})
        with self.assertRaises(ValueError):
            MODULE.validate_snapshot(app, pods, jobs, resources, UIDS)

    def test_incomplete_inventory_is_denied(self):
        for listing in ({"items": []},
                        {"kind": "PodList", "metadata": {"continue": "next", "resourceVersion": "1"}, "items": []},
                        {"kind": "PodList", "metadata": {}, "items": []},
                        {"kind": "PodList", "metadata": {"resourceVersion": "0"}, "items": []},
                        {"kind": "JobList", "metadata": {"resourceVersion": "1"}, "items": []}):
            with self.assertRaises(ValueError):
                MODULE.complete(listing, "PodList")

    def test_delete_uses_exact_uid_precondition(self):
        with mock.patch.object(MODULE, "proxy_request", return_value=200) as request:
            MODULE.delete_with_uid("/private/kubernetes.sock", MODULE.TARGETS[0][2], UIDS[0])
        socket_path, method, path, body = request.call_args.args
        self.assertEqual((socket_path, method, path),
                         ("/private/kubernetes.sock", "DELETE", MODULE.TARGETS[0][2]))
        self.assertEqual(json.loads(body)["preconditions"], {"uid": UIDS[0]})

    def test_absence_verification_rejects_any_error_except_not_found(self):
        with mock.patch.object(MODULE, "proxy_request", return_value=404):
            MODULE.verify_absent("/private/kubernetes.sock", MODULE.TARGETS[0][2])
        with mock.patch.object(MODULE, "proxy_request", return_value=403):
            with self.assertRaises(ValueError):
                MODULE.verify_absent("/private/kubernetes.sock", MODULE.TARGETS[0][2])

    def test_proxy_uses_socket_inside_private_directory(self):
        bound = []

        def fake_popen(args, **_):
            path = args[2].split("=", 1)[1]
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path)
            bound.append(server)
            process = mock.Mock()
            process.poll.return_value = None
            return process

        with mock.patch.object(MODULE.subprocess, "Popen", side_effect=fake_popen):
            _, path, directory = MODULE.proxy_start()
        try:
            self.assertTrue(path.startswith(directory + os.sep))
            self.assertEqual(stat.S_IMODE(os.stat(directory).st_mode), 0o700)
            self.assertTrue(stat.S_ISSOCK(os.stat(path).st_mode))
        finally:
            bound[0].close()
            shutil.rmtree(directory)

    def test_default_cli_is_read_only(self):
        app, pods, jobs, resources = fixtures()

        def listing(entries):
            return {"kind": "PodList" if entries is pods else "JobList",
                    "metadata": {"resourceVersion": "1"}, "items": entries}

        reads = [app, *resources]
        with (mock.patch.object(sys, "argv", ["recovery", "a" * 40, *UIDS]),
              mock.patch.object(MODULE, "source_guard"),
              mock.patch.object(MODULE, "kubectl_json", side_effect=reads),
              mock.patch.object(MODULE, "kubectl_raw_json", side_effect=[listing(pods), listing(jobs)]),
              mock.patch.object(MODULE, "proxy_start") as proxy,
              mock.patch.object(MODULE, "delete_with_uid") as delete):
            MODULE.main()
        proxy.assert_not_called()
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
