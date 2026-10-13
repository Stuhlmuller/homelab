#!/usr/bin/env python3
"""Check profile containment, idempotence and fail-closed configuration races."""
import argparse
import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("profile", ROOT / "scripts/talos-nix-builder-seccomp.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.wanted = {"name": module.NAME, "value": {"defaultAction": "SCMP_ACT_ERRNO"}}
        self.before = [{"version": "v1alpha1", "machine": {"seccompProfiles": [
            {"name": "other.json", "value": {"defaultAction": "SCMP_ACT_ERRNO"}}],
            "sysctls": {"user.max_user_namespaces": "0"}}, "cluster": {"name": "fixture"}}]

    def test_profile_changes_only_pivot_root_from_captured_runtime(self):
        declaration = json.loads((ROOT / ".talos/patches/nix-builder-seccomp.yaml").read_text())
        entries = declaration["machine"]["seccompProfiles"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], module.NAME)
        profile = entries[0]["value"]
        self.assertEqual(profile["syscalls"].pop(), {"names": ["pivot_root"], "action": "SCMP_ACT_ALLOW"})
        canonical = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), "3d7b229de5b4452a15c14823457964e593247f3d1f720f23051e56f25c830b72")

    def test_only_owned_profile_changes_and_is_idempotent(self):
        after = module.profiles(self.before, self.wanted, False)
        self.assertEqual(after[0]["machine"]["seccompProfiles"],
                         self.before[0]["machine"]["seccompProfiles"] + [self.wanted])
        self.assertEqual(after[0]["machine"]["sysctls"], self.before[0]["machine"]["sysctls"])
        self.assertEqual(after[0]["cluster"], self.before[0]["cluster"])
        self.assertEqual(module.profiles(after, self.wanted, False), after)
        self.assertEqual(module.profiles(after, self.wanted, True), self.before)
        self.assertEqual(module.profiles(self.before, self.wanted, True), self.before)

    def test_conflicting_and_duplicate_profiles_rejected(self):
        for entries in ([self.wanted, self.wanted], [{"name": module.NAME, "value": {}}]):
            before = copy.deepcopy(self.before)
            before[0]["machine"]["seccompProfiles"] = entries
            with self.assertRaises(RuntimeError):
                module.profiles(before, self.wanted, False)

    def test_stale_configuration_cannot_apply(self):
        calls = []
        args = argparse.Namespace(execute=True, expected_sha="a" * 40, rollback=False,
                                  node="10.1.0.200", talosconfig=Path("/private/fixture"))
        declaration = [{"machine": {"seccompProfiles": [self.wanted]}}]
        def run(*command):
            calls.append(command)
            return "Talos v1.11.3" if command[1:3] == ("version", "--client") else ""
        with patch.object(module.operator, "run", side_effect=run), \
                patch.object(module.operator, "verify_main"), \
                patch.object(module.operator, "documents", return_value=declaration), \
                patch.object(module, "ready", return_value="boot"), \
                patch.object(module, "capture", side_effect=[self.before, []]):
            with self.assertRaisesRegex(RuntimeError, "changed during validation"):
                module.reconcile(args)
        self.assertFalse(any("apply-config" in call for call in calls))

    def test_rollback_refuses_profile_selected_by_existing_pod(self):
        args = argparse.Namespace(execute=False, rollback=True)
        pod = {"spec": {"containers": [{"securityContext": {"seccompProfile": {
            "type": "Localhost", "localhostProfile": "profiles/" + module.NAME}}}]}}
        with patch.object(module.operator, "run", side_effect=["Talos v1.11.3", json.dumps({"items": [pod]})]):
            with self.assertRaisesRegex(RuntimeError, "Revert workload"):
                module.reconcile(args)


if __name__ == "__main__":
    unittest.main()
