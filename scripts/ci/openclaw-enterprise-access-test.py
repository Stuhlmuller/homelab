#!/usr/bin/env python3
"""Fail-closed checks for the Octelium Enterprise access reconciliation path."""
import importlib.util
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("access", ROOT / "scripts/openclaw-enterprise-access.py")
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


class EnterpriseAccess(unittest.TestCase):
    def test_catalog_has_only_reviewed_targets_and_authentication(self):
        targets = access.declared()
        self.assertEqual({(value["kind"], value["metadata"]["name"]) for value in targets}, access.TARGETS)
        self.assertFalse(targets[1]["spec"]["isAnonymous"])
        self.assertFalse(targets[2]["spec"]["isAnonymous"])
        self.assertEqual(targets[2]["spec"]["config"]["http"]["plugins"][0]["phase"], "POST_AUTH")

        for resource_name, mutate in (
            ("console.oce", lambda obj: obj["spec"].update(isAnonymous=True)),
            ("openclaw", lambda obj: obj["spec"]["config"]["http"]["plugins"][0].update(phase="PRE_AUTH")),
            ("oce", lambda obj: obj["spec"].update(authorization={})),
        ):
            with self.subTest(resource=resource_name):
                altered = json.loads(json.dumps(targets))
                mutate(next(obj for obj in altered if obj["metadata"]["name"] == resource_name))
                with patch.object(access, "run", return_value=types.SimpleNamespace(stdout=json.dumps(altered))):
                    with self.assertRaises(RuntimeError):
                        access.declared()

    def test_apply_rechecks_main_before_each_scoped_write_and_requires_convergence(self):
        expected = "a" * 40
        targets = access.declared()
        calls = []
        live_specs = {
            "oce": targets[0]["spec"], "console.oce": targets[1]["spec"],
            "openclaw.default": targets[2]["spec"]}

        def fake_run(*command, **_kwargs):
            calls.append(command)
            if "apply" in command:
                return types.SimpleNamespace(stdout="No applied changes in Cluster Core resources", stderr="")
            name = command[command.index("get") + 2]
            return types.SimpleNamespace(stdout=json.dumps({"metadata": {"name": name},
                                                             "spec": live_specs[name]}), stderr="")

        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(access, "reviewed_main") as guard, patch.object(access, "run", side_effect=fake_run):
            access.apply(["octeliumctl"], {}, pathlib.Path(temporary), targets, expected)
        self.assertEqual(guard.call_count, 2)
        guard.assert_any_call(expected)
        applies = [command for command in calls if "apply" in command]
        self.assertEqual(len(applies), 2)
        self.assertTrue(all(command[2:6] == ("--include", "Namespace", "--include", "Service")
                            for command in applies))
        self.assertTrue(all("--prune" not in command for command in applies))

        def stale_main(_expected):
            raise RuntimeError("main advanced")

        with tempfile.TemporaryDirectory() as temporary, patch.object(access, "reviewed_main", side_effect=stale_main), \
                patch.object(access, "run") as runner:
            with self.assertRaisesRegex(RuntimeError, "main advanced"):
                access.apply(["octeliumctl"], {}, pathlib.Path(temporary), targets, expected)
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
