#!/usr/bin/env python3
"""Offline create-only and exact-source tests for the startup Secret stage."""

import base64
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "startup", ROOT / "scripts/openclaw-enterprise-startup.py")
startup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(startup)
SHA = "a" * 40
CONTEXT = {"clusters": [{"cluster": {"server": startup.KUBE_SERVER}}]}
NAMESPACE = {"metadata": {"labels": {
    "app.kubernetes.io/part-of": "openclaw-enterprise"}}}


class StartupContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidate = startup.source_contract()
        cls.secret = startup.desired_secret(cls.candidate)

    def test_reviewed_bytes_and_immutable_versioned_secret(self):
        self.assertEqual(self.secret["metadata"]["name"], startup.NAME)
        self.assertEqual(self.secret["metadata"]["namespace"], "openclaw-system")
        self.assertEqual(self.secret["type"], "Opaque")
        self.assertIs(self.secret["immutable"], True)
        self.assertEqual(set(self.secret["data"]), {"installation.yaml"})
        self.assertEqual(base64.b64decode(self.secret["data"]["installation.yaml"]),
                         self.candidate)
        startup.verify_secret(self.secret, self.candidate)

    def test_rejects_mutation_foreign_ownership_and_extra_keys(self):
        for change in (
            {"immutable": False},
            {"metadata": {**self.secret["metadata"], "ownerReferences": [{"kind": "Job"}]}},
            {"data": {**self.secret["data"], "another-key": "WA=="}},
            {"data": {"installation.yaml": "WA=="}},
        ):
            with self.subTest(change=change):
                wrong = {**self.secret, **change}
                with self.assertRaises(startup.Blocked):
                    startup.verify_secret(wrong, self.candidate)

    def test_create_only_after_exact_context_and_namespace(self):
        with patch.object(startup, "reviewed_main") as main, \
             patch.object(startup, "kube_json", side_effect=[CONTEXT, NAMESPACE,
                                                        None, self.secret]) as read, \
             patch.object(startup, "kube") as create:
            startup.execute(SHA, self.candidate)
        main.assert_called_once_with(SHA)
        self.assertEqual(read.call_count, 4)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(create.call_args.args, ("create", "-f", "-"))
        self.assertEqual(startup.json.loads(create.call_args.kwargs["data"]), self.secret)

    def test_existing_exact_secret_is_read_only(self):
        with patch.object(startup, "reviewed_main"), \
             patch.object(startup, "kube_json", side_effect=[CONTEXT, NAMESPACE,
                                                        self.secret, self.secret]), \
             patch.object(startup, "kube") as create:
            startup.execute(SHA, self.candidate)
        create.assert_not_called()

    def test_missing_namespace_or_foreign_secret_blocks_before_create(self):
        for sequence in ([CONTEXT, None], [CONTEXT, NAMESPACE, {**self.secret,
                          "immutable": False}]):
            with self.subTest(sequence=sequence), \
                 patch.object(startup, "reviewed_main"), \
                 patch.object(startup, "kube_json", side_effect=sequence), \
                 patch.object(startup, "kube") as create:
                with self.assertRaises(startup.Blocked):
                    startup.execute(SHA, self.candidate)
                create.assert_not_called()

    def test_lost_create_response_requires_exact_readback(self):
        with patch.object(startup, "reviewed_main"), \
             patch.object(startup, "kube_json", side_effect=[CONTEXT, NAMESPACE,
                                                        None, self.secret, self.secret]), \
             patch.object(startup, "kube", side_effect=startup.Blocked("lost response")):
            startup.execute(SHA, self.candidate)

    def test_execute_requires_dispatch_main_and_clean_checkout(self):
        environment = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": SHA}
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(startup, "command", side_effect=["", SHA + "\n",
                                                        SHA + "\trefs/heads/main\n"]):
            startup.reviewed_main(SHA)
        with patch.dict(os.environ, {**environment, "GITHUB_REF": "refs/heads/feature"},
                        clear=True), patch.object(startup, "command") as command:
            with self.assertRaises(startup.Blocked):
                startup.reviewed_main(SHA)
            command.assert_not_called()
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(startup, "command", return_value="M installation.yaml\n"):
            with self.assertRaises(startup.Blocked):
                startup.reviewed_main(SHA)


if __name__ == "__main__":
    unittest.main()
