#!/usr/bin/env python3
"""Offline regression for the stranded Cordium bootstrap identity recovery fence."""

import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib.error import HTTPError


SOURCE = Path(__file__).resolve().parents[1] / "cordium-genesis-recovery.py"
SPEC = importlib.util.spec_from_file_location("cordium_recovery", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
UIDS = tuple(f"00000000-0000-0000-0000-{n:012d}" for n in (1, 2, 3))


def fixtures():
    app = {"metadata": {"name": "cordium-bootstrap"},
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

    def test_incomplete_inventory_is_denied(self):
        for listing in ({"items": []}, {"metadata": {"continue": "next"}, "items": []}):
            with self.assertRaises(ValueError):
                MODULE.complete(listing)

    def test_delete_uses_exact_uid_precondition_and_no_proxy_environment(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

        opener = mock.Mock()
        opener.open.return_value = Response()
        with mock.patch.object(MODULE.urllib.request, "build_opener", return_value=opener) as build:
            MODULE.delete_with_uid("http://127.0.0.1:1234", MODULE.TARGETS[0][2], UIDS[0])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "DELETE")
        self.assertEqual(request.full_url, "http://127.0.0.1:1234" + MODULE.TARGETS[0][2])
        self.assertEqual(__import__("json").loads(request.data)["preconditions"], {"uid": UIDS[0]})
        self.assertEqual(build.call_args.args[0].proxies, {})

    def test_absence_verification_rejects_any_error_except_not_found(self):
        opener = mock.Mock()
        opener.open.side_effect = HTTPError("http://127.0.0.1", 404, "not found", {}, None)
        with mock.patch.object(MODULE.urllib.request, "build_opener", return_value=opener):
            MODULE.verify_absent("http://127.0.0.1:1234", MODULE.TARGETS[0][2])
        opener.open.side_effect = HTTPError("http://127.0.0.1", 403, "forbidden", {}, None)
        with mock.patch.object(MODULE.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(HTTPError):
                MODULE.verify_absent("http://127.0.0.1:1234", MODULE.TARGETS[0][2])

    def test_default_cli_is_read_only(self):
        app, pods, jobs, resources = fixtures()
        listing = lambda entries: {"metadata": {"resourceVersion": "1"}, "items": entries}
        reads = [app, listing(pods), listing(jobs), *resources]
        with (mock.patch.object(sys, "argv", ["recovery", "a" * 40, *UIDS]),
              mock.patch.object(MODULE, "source_guard"),
              mock.patch.object(MODULE, "kubectl_json", side_effect=reads),
              mock.patch.object(MODULE, "proxy_start") as proxy,
              mock.patch.object(MODULE, "delete_with_uid") as delete):
            MODULE.main()
        proxy.assert_not_called()
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
