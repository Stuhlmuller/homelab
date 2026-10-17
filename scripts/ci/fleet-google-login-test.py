#!/usr/bin/env python3
"""Credential isolation and recovery guards for Google-backed Fleet Mac login."""

import contextlib
import copy
import importlib.util
import io
import json
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("google_login", ROOT / "scripts/fleet-google-login.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
SECRET = "GOC" + "SPX-" + "a" * 32
VALUE = {"web": {"client_id": helper.CLIENT_ID, "client_secret": SECRET,
                 "project_id": "n8n-credentials-498013", "redirect_uris": [helper.REDIRECT],
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                 "token_uri": "https://oauth2.googleapis.com/token"}}


class GoogleLoginTest(unittest.TestCase):
    def test_rejects_wrong_client_project_endpoints_and_extra_callbacks(self):
        for key, value in (("client_id", "another.apps.googleusercontent.com"),
                           ("project_id", "wrong"), ("redirect_uris", [helper.REDIRECT, "https://evil.test"]),
                           ("token_uri", "https://evil.test"), ("auth_uri", "http://accounts.google.com"),
                           ("client_secret", "REPLACE_ME")):
            with self.subTest(key=key):
                candidate = copy.deepcopy(VALUE)
                candidate["web"][key] = value
                with self.assertRaises(helper.Failure):
                    helper.credential(candidate)

    def test_profile_preserves_local_recovery_and_domain_guard(self):
        raw, expected = helper.profile(VALUE)
        actual = plistlib.loads(raw)
        self.assertEqual(actual, expected)
        self.assertEqual(actual["PayloadScope"], "System")
        self.assertEqual(actual["TargetDeviceType"], 5)
        self.assertIs(actual["PayloadRemovalDisallowed"], False)
        settings = actual["PayloadContent"][0]
        self.assertEqual(settings["PayloadType"], "com.twocanoes.xcreds")
        self.assertEqual(settings["allowUsersClaim"], "hd")
        self.assertEqual(settings["allowedUsersArray"], ["stuhlmuller.net"])
        self.assertEqual(settings["clientID"], helper.CLIENT_ID)
        self.assertEqual(settings["clientSecret"], SECRET)
        self.assertEqual(settings["map_username"], "email")
        for key in ("CreateAdminUser", "shouldSkipFileVaultLogin", "shouldSkipFileVaultLoginAdmin", "EnableFDERekey"):
            self.assertIs(settings[key], False)
        self.assertIs(settings["shouldPromptForMigration"], True)
        self.assertIs(settings["shouldShowMacLoginButton"], True)
        self.assertNotIn("localAdminPassword", settings)
        self.assertEqual(helper.profile(VALUE)[0], raw)

    def test_private_input_and_ssm_slot_required_before_store(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(VALUE))
            path.chmod(0o644)
            with patch.object(helper, "command") as command:
                with self.assertRaises(Exception):
                    helper.store(path)
                command.assert_not_called()
            path.chmod(0o600)
            with patch.object(helper, "command", return_value='{"Parameters": []}') as command:
                with self.assertRaises(helper.Failure):
                    helper.store(path)
                self.assertEqual(command.call_count, 1)
                self.assertNotIn("put-parameter", command.call_args.args[0])

    def test_store_uses_private_payload_and_fixed_securestring(self):
        def command(args):
            if "describe-parameters" in args:
                return json.dumps({"Parameters": [{"Name": helper.PARAMETER, "Type": "SecureString",
                                                    "KeyId": "alias/aws/ssm"}]})
            self.assertIn("put-parameter", args)
            self.assertIn("us-west-2", args)
            payload_path = Path(args[args.index("--cli-input-json") + 1].removeprefix("file://"))
            self.assertEqual(payload_path.stat().st_mode & 0o777, 0o600)
            payload = json.loads(payload_path.read_text())
            self.assertEqual(payload["Name"], helper.PARAMETER)
            self.assertEqual(payload["Type"], "SecureString")
            self.assertEqual(json.loads(payload["Value"]), VALUE)
            return '{"Version": 1}'

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(VALUE))
            path.chmod(0o600)
            output = io.StringIO()
            with patch.object(helper, "command", side_effect=command), contextlib.redirect_stdout(output):
                helper.store(path)
            self.assertNotIn(SECRET, output.getvalue())

    def test_dry_run_never_reads_credentials_or_calls_live_services(self):
        with patch.object(helper, "command") as command, patch.object(helper, "read_credential") as read:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(helper.main(["install-profile"]), 0)
            command.assert_not_called()
            read.assert_not_called()

    def test_context_failure_and_errors_never_expose_secret(self):
        output = io.StringIO()
        with patch.object(helper, "validate_context", side_effect=RuntimeError(SECRET)):
            with contextlib.redirect_stderr(output):
                self.assertEqual(helper.main(["install-profile", "--execute"]), 1)
        self.assertNotIn(SECRET, output.getvalue())

    def test_rejects_unsigned_context(self):
        sha = "a" * 40
        for outputs in ([sha, "feature", "", sha + " refs/heads/main", "true"],
                        [sha, "main", " M file", sha + " refs/heads/main", "true"],
                        [sha, "main", "", "b" * 40 + " refs/heads/main", "true"],
                        [sha, "main", "", sha + " refs/heads/main", "false"]):
            with patch.object(helper, "command", side_effect=outputs), self.assertRaises(helper.Failure):
                helper.validate_context()

    def test_install_requires_delivered_profile_before_inspecting_package(self):
        with patch.object(helper, "command", side_effect=["Darwin", "wrong-client"]):
            with self.assertRaises(helper.Failure):
                helper.install_software(Path("/not-opened.pkg"))

    def test_install_rejects_unreviewed_package_before_sudo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.pkg"
            path.write_bytes(b"not the pinned installer")
            with patch.object(helper, "command", side_effect=["Darwin", helper.CLIENT_ID]) as command:
                with self.assertRaises(helper.Failure):
                    helper.install_software(path)
                self.assertEqual(command.call_count, 2)

    def test_remove_refuses_to_strip_settings_from_active_login_plugin(self):
        rights = plistlib.dumps({"mechanisms": ["XCredsLoginPlugin:LoginWindow"]}).decode()
        with patch.object(helper, "command", return_value=rights), patch.object(helper, "read_credential") as read:
            with self.assertRaises(helper.Failure):
                helper.apply_profile(remove=True)
            read.assert_not_called()

    def test_explicit_host_uses_enrollment_guard_and_revokes_session_on_failure(self):
        setup, api, mdm = Mock(), Mock(), Mock()
        api.request.return_value = {"token": "test-session"}
        setup.mac_host.side_effect = helper.Failure("Selected host is not enrolled")
        with patch.object(helper, "module", side_effect=[setup, api, mdm]):
            with patch.object(helper, "read_credential", return_value=VALUE), self.assertRaises(helper.Failure):
                helper.apply_profile(host_id=7)
        setup.mac_host.assert_called_once_with(api, mdm, "test-session", 7)
        setup.apply_profiles.assert_not_called()
        logout_path = "/api/v1/fleet/logout"
        api.request.assert_called_with("POST", logout_path, token="test-session")

    def test_remote_removal_requires_native_login_attestation_and_enrollment(self):
        with self.assertRaises(helper.Failure):
            helper.apply_profile(remove=True, host_id=7)
        setup, api, mdm = Mock(), Mock(), Mock()
        api.request.return_value = {"token": "test-session"}
        setup.mac_host.return_value = "host-uuid"
        with patch.object(helper, "module", side_effect=[setup, api, mdm]), patch.object(helper, "command") as command:
            helper.apply_profile(remove=True, host_id=7, native_login_restored=True)
        command.assert_not_called()
        setup.mac_host.assert_called_once_with(api, mdm, "test-session", 7)
        setup.apply_profiles.assert_called_once_with(api, mdm, "test-session", "host-uuid",
                                                     [(b"", {"PayloadIdentifier": helper.IDENTIFIER})], remove=True)
        api.request.assert_called_with("POST", "/api/v1/fleet/logout", token="test-session")


if __name__ == "__main__":
    unittest.main()
