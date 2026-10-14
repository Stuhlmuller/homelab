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
    def check(self, current, previous, name="removed", readme=None):
        results = [json.dumps(current), "previous yaml", json.dumps(previous)]
        if readme is not None:
            results.append(readme)
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

    def test_legacy_scope_requires_removed_catalog_and_documented_owner(self):
        old = [{"kind": "Service", "metadata": {"name": "removed"}, "spec": {"mode": "WEB", "isPublic": True}}]
        self.assertEqual(self.check([], old, "removed.homelab", "UI targets `removed.homelab`"), "removed.homelab")
        for readme in ("", "UI targets `other.homelab`", "UI targets `removed.homelab.other`"):
            with self.assertRaises(ValueError):
                self.check([], old, "removed.homelab", readme)
        with patch.object(pathlib.Path, "exists", return_value=True), self.assertRaises(ValueError):
            self.check([], old, "removed.homelab")
        with patch.object(retire.native, "run") as run, self.assertRaises(ValueError):
            retire.removed_service("removed", "main")
        run.assert_not_called()
        with patch.object(retire.native, "run", side_effect=subprocess.CalledProcessError(1, "git")), self.assertRaises(subprocess.CalledProcessError):
            retire.removed_service("removed", "a" * 40)

    def test_live_retirement_is_exact_and_fail_closed(self):
        self.live_retirement(False)
        self.live_retirement(True)

    def live_retirement(self, legacy):
        service = {"metadata": {"name": "removed.default"}, "spec": {"mode": "WEB", "isPublic": True}}
        name = "removed.homelab" if legacy else "removed.default"
        if legacy:
            service = {"metadata": {"name": name}, "spec": {"mode": "TCP", "port": 443, "config": {"upstream": {"url": "tcp://istio-ingressgateway.istio-system.svc.cluster.local:443"}}}}
        for mode in ("present", "absent", "unavailable", "wrong", "contract", "stuck"):
            calls = []
            def command(argv, **kwargs):
                calls.append(argv[-4:])
                if "delete" in argv:
                    return subprocess.CompletedProcess(argv, 0, "", "")
                if mode == "unavailable":
                    return subprocess.CompletedProcess(argv, 1, "", "code = Unavailable")
                if mode == "absent" or (len(calls) == 3 and mode != "stuck"):
                    return subprocess.CompletedProcess(argv, 1, "gRPC error NotFound:", "")
                if mode == "contract":
                    return subprocess.CompletedProcess(argv, 0, json.dumps(dict(service, spec={"mode":"TCP", "port":444, "isPublic":True})), "")
                value = dict(service, metadata={"name": "other.default"}) if mode == "wrong" else service
                return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
            with patch.object(sys, "argv", ["retire", "--service", "removed", "--homedir", "/private/login", "--execute"]), \
                    patch.object(retire, "removed_service", return_value=name), \
                    patch.object(retire.native, "verify_reviewed_main"), patch.object(retire.native, "run"), \
                    patch.object(retire.native, "verified_client", return_value="/pinned/client"), \
                    patch.object(retire.native, "native_transport", return_value=contextlib.nullcontext({})), \
                    patch.object(retire.subprocess, "run", side_effect=command):
                if mode in ("unavailable", "wrong", "contract", "stuck"):
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
