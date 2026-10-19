#!/usr/bin/env python3
"""Offline CAS and identity fixtures for the post-bootstrap Secret binder."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


binder = load("oce_binder_test", "scripts/openclaw-enterprise-bind-installation.py")
fixtures = load("oce_reconciler_fixtures", "scripts/ci/openclaw-enterprise-test.py")


class API:
    def __init__(self, *identities):
        self.identities = iter(identities)
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        return {"id": next(self.identities)}


class Kubernetes:
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)
        self.calls = []

    def snapshot(self, digest):
        self.calls.append(digest)
        return next(self.snapshots)


class InstallationBinding(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "scripts/config/openclaw-enterprise.json").read_text())
        self.candidate, self.digest, self.image, self.base = (
            fixtures.EnterpriseReconciliation._installation_snapshot(self))
        secret = self.base["secret"]
        secret["kind"] = "Secret"
        secret["metadata"]["labels"] = {"app.kubernetes.io/part-of": "openclaw-enterprise"}
        secret["metadata"]["annotations"] = {
            "homelab.stuhlmuller.dev/installation-sha256": self.digest}
        self.version = patch.object(binder.startup, "DIGEST", self.digest)
        self.name = patch.object(binder.startup, "NAME",
                                 "occ-installation-startup-" + self.digest[:32])
        self.reviewed = patch.object(binder.oce, "reviewed_installation",
                                     return_value=(self.candidate, self.digest, self.image))
        self.main = patch.object(binder.startup, "reviewed_main")
        for active in (self.version, self.name, self.reviewed):
            active.start()
            self.addCleanup(active.stop)
        self.main_mock = self.main.start()
        self.addCleanup(self.main.stop)

    def snapshots(self, *, bound=False):
        before = deepcopy(self.base)
        after = deepcopy(self.base)
        if bound:
            for snapshot in (before, after):
                snapshot["secret"]["metadata"]["annotations"][binder.ANNOTATION] = "ins_one"
                snapshot["secret"]["metadata"]["resourceVersion"] = "101"
        return before, after

    def run_binding(self, pre=None, post=None,
                    identities=("ins_one", "ins_one", "ins_one")):
        pre = pre or self.snapshots()
        post = post or self.snapshots(bound=True)
        kube = Kubernetes([*pre, *post])
        api = API(*identities)
        with patch.object(binder.startup, "kube") as patch_secret:
            receipt = binder.bind("a" * 40, self.config, api, kube)
        return receipt, patch_secret, kube, api

    def test_binds_only_annotation_with_uid_and_resource_version_cas(self):
        receipt, patch_secret, kube, api = self.run_binding()
        self.assertEqual(receipt, {"installationId": "ins_one", "secretUid": "secret-one",
                                   "secretResourceVersion": "101"})
        self.assertEqual(api.calls, ["/installation"] * 3)
        self.assertEqual(kube.calls, [self.digest] * 4)
        self.assertEqual(self.main_mock.call_count, 2)
        args = patch_secret.call_args.args
        self.assertEqual(args[:5], ("-n", "openclaw-system", "patch", "secret",
                                    binder.startup.NAME))
        self.assertEqual(args[5:7], ("--type=json", "-p"))
        self.assertEqual(json.loads(args[7]), [
            {"op": "test", "path": "/metadata/uid", "value": "secret-one"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "100"},
            {"op": "add", "path": binder.ANNOTATION_PATH, "value": "ins_one"},
        ])

    def test_exact_existing_binding_is_idempotent(self):
        pre = self.snapshots(bound=True)
        post = self.snapshots(bound=True)
        receipt, patch_secret, _, _ = self.run_binding(pre, post)
        patch_secret.assert_not_called()
        self.assertEqual(receipt["secretResourceVersion"], "101")

    def test_rejects_foreign_secret_before_patch(self):
        for change in ("wrong-id", "wrong-label", "owner", "wrong-bytes",
                       "wrong-digest", "mutable", "missing-version", "null-id"):
            with self.subTest(change=change):
                pre = self.snapshots()
                for snapshot in pre:
                    secret = snapshot["secret"]
                    metadata = secret["metadata"]
                    if change == "wrong-id":
                        metadata["annotations"][binder.ANNOTATION] = "ins_foreign"
                    elif change == "wrong-label":
                        metadata["labels"]["app.kubernetes.io/part-of"] = "foreign"
                    elif change == "owner":
                        metadata["ownerReferences"] = [{"kind": "Job"}]
                    elif change == "wrong-bytes":
                        secret["data"]["installation.yaml"] = "WA=="
                    elif change == "wrong-digest":
                        metadata["annotations"]["homelab.stuhlmuller.dev/installation-sha256"] = "0" * 64
                    elif change == "mutable":
                        secret["immutable"] = False
                    elif change == "missing-version":
                        metadata["resourceVersion"] = ""
                    else:
                        metadata["annotations"][binder.ANNOTATION] = None
                with patch.object(binder.startup, "kube") as patch_secret:
                    with self.assertRaises((binder.oce.Blocked, binder.startup.Blocked)):
                        binder.bind("a" * 40, self.config, API("ins_one"),
                                    Kubernetes(pre))
                    patch_secret.assert_not_called()

    def test_rejects_changed_api_identity_or_workload_before_patch(self):
        pre = self.snapshots()
        pre[1]["pods"]["worker"][0]["metadata"]["resourceVersion"] = "401"
        replaced_secret = self.snapshots()
        replaced_secret[1]["secret"]["metadata"]["uid"] = "foreign-uid"
        for snapshots, identity in ((self.snapshots(), "not-an-installation"),
                                    (pre, "ins_one"),
                                    (replaced_secret, "ins_one")):
            with patch.object(binder.startup, "kube") as patch_secret:
                with self.assertRaises(binder.oce.Blocked):
                    binder.bind("a" * 40, self.config, API(identity),
                                Kubernetes(snapshots))
                patch_secret.assert_not_called()

    def test_patch_conflict_fails_closed_and_retries_can_read_back(self):
        with patch.object(binder.startup, "kube", side_effect=binder.startup.Blocked("CAS conflict")):
            with self.assertRaises(binder.startup.Blocked):
                binder.bind("a" * 40, self.config, API("ins_one", "ins_one"),
                            Kubernetes(self.snapshots()))
        # A retry may observe the exact annotation after an uncertain response.
        pre = self.snapshots(bound=True)
        _, patch_secret, _, _ = self.run_binding(pre, self.snapshots(bound=True))
        patch_secret.assert_not_called()

    def test_post_patch_rejects_changed_identity_or_workload(self):
        with self.assertRaisesRegex(binder.oce.Blocked, "identity changed"):
            self.run_binding(identities=("ins_one", "ins_one", "ins_other"))
        post = self.snapshots(bound=True)
        post[0]["pods"]["api"][0]["metadata"]["uid"] = "new-pod"
        post[1]["pods"]["api"][0]["metadata"]["uid"] = "new-pod"
        with self.assertRaisesRegex(binder.oce.Blocked, "workload changed"):
            self.run_binding(post=post)
        with self.assertRaisesRegex(binder.oce.Blocked, "unbound"):
            self.run_binding(post=self.snapshots())
        foreign = self.snapshots(bound=True)
        for snapshot in foreign:
            snapshot["secret"]["metadata"]["uid"] = "replacement-secret"
        with self.assertRaisesRegex(binder.oce.Blocked, "workload changed"):
            self.run_binding(post=foreign)

    def test_main_must_remain_exact_immediately_before_patch(self):
        with patch.object(binder.startup, "reviewed_main",
                          side_effect=[None, binder.startup.Blocked("main advanced")]), \
             patch.object(binder.startup, "kube") as patch_secret:
            with self.assertRaises(binder.startup.Blocked):
                binder.bind("a" * 40, self.config, API("ins_one"),
                            Kubernetes(self.snapshots()))
            patch_secret.assert_not_called()

    def test_changed_identity_before_patch_keeps_secret_unbound(self):
        with patch.object(binder.startup, "kube") as patch_secret:
            with self.assertRaisesRegex(binder.oce.Blocked, "identity changed before binding"):
                binder.bind("a" * 40, self.config, API("ins_one", "ins_other"),
                            Kubernetes(self.snapshots()))
            patch_secret.assert_not_called()

    def test_exact_main_is_checked_before_private_credential(self):
        with patch.object(binder.startup, "reviewed_main",
                          side_effect=binder.startup.Blocked("main advanced")), \
             patch.object(binder.oce, "_read_key") as key:
            self.assertEqual(binder.main(["--expected-sha", "a" * 40,
                                          "--credential-file", "/private/key"]), 1)
            key.assert_not_called()


if __name__ == "__main__":
    unittest.main()
