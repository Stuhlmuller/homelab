#!/usr/bin/env python3
"""Check the catalog boundary for public Service retirement."""
import contextlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("retire", pathlib.Path(__file__).resolve().parents[1] / "octelium-service-retire.py")
retire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retire)


class Retirement(unittest.TestCase):
    def check(self, current, previous, name="removed"):
        results = [json.dumps(current), "previous yaml", json.dumps(previous)]
        with patch.object(retire.native, "run", side_effect=[subprocess.CompletedProcess([], 0, value, "") for value in results]):
            return retire.removed_service(name)

    def test_only_removed_public_web_service(self):
        old = [{"kind": "Service", "metadata": {"name": "removed"}, "spec": {"mode": "WEB", "isPublic": True}}]
        self.assertEqual(self.check([], old), "removed.default")
        for current, previous in ((old, old), ([], []), ([], old * 2)):
            with self.assertRaises(ValueError):
                self.check(current, previous)
        for spec in ({"mode": "KUBERNETES", "isPublic": True}, {"mode": "WEB", "isPublic": False}):
            with self.assertRaises(ValueError):
                self.check([], [{"kind": "Service", "metadata": {"name": "removed"}, "spec": spec}])

    def test_live_retirement_is_exact_and_fail_closed(self):
        service = {"metadata": {"name": "removed.default"}, "spec": {"mode": "WEB", "isPublic": True}}
        for mode in ("present", "absent", "unavailable", "wrong", "stuck"):
            calls = []
            def command(argv, **kwargs):
                calls.append(argv[-4:])
                if "delete" in argv:
                    return subprocess.CompletedProcess(argv, 0, "", "")
                if mode == "unavailable":
                    return subprocess.CompletedProcess(argv, 1, "", "code = Unavailable")
                if mode == "absent" or (len(calls) == 3 and mode != "stuck"):
                    return subprocess.CompletedProcess(argv, 1, "gRPC error NotFound:", "")
                value = dict(service, metadata={"name": "other.default"}) if mode == "wrong" else service
                return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
            with patch.object(sys, "argv", ["retire", "--service", "removed", "--homedir", "/private/login", "--execute"]), \
                    patch.object(retire, "removed_service", return_value="removed.default"), \
                    patch.object(retire.native, "verify_reviewed_main"), patch.object(retire.native, "run"), \
                    patch.object(retire.native, "verified_client", return_value="/pinned/client"), \
                    patch.object(retire.native, "native_transport", return_value=contextlib.nullcontext({})), \
                    patch.object(retire.subprocess, "run", side_effect=command):
                if mode in ("unavailable", "wrong", "stuck"):
                    with self.assertRaises(RuntimeError):
                        retire.main()
                else:
                    retire.main()
            self.assertEqual(sum("delete" in call for call in calls), int(mode in ("present", "stuck")))

    def test_qualified_or_option_names_rejected_before_commands(self):
        for name in ("--all", "removed.default", "../removed", ""):
            with patch.object(retire.native, "run") as run, self.assertRaises(ValueError):
                retire.removed_service(name)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
