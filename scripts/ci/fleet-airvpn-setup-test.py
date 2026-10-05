#!/usr/bin/env python3
"""Exercise AirVPN provisioning with generated keys and synthetic Fleet state."""

import base64
import contextlib
import copy
import importlib.util
import io
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("fleet_airvpn", ROOT / "scripts/fleet-airvpn-setup.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
FREE_SPEC = importlib.util.spec_from_file_location("fleet_free_test", ROOT / "scripts/fleet-free-setup.py")
setup = importlib.util.module_from_spec(FREE_SPEC)
FREE_SPEC.loader.exec_module(setup)
MDM_SPEC = importlib.util.spec_from_file_location("fleet_mdm_test", ROOT / "scripts/fleet-verify-apple-mdm.py")
mdm_helper = importlib.util.module_from_spec(MDM_SPEC)
MDM_SPEC.loader.exec_module(mdm_helper)

# Runtime fixtures, never operator credentials or real AirVPN client exports.
PRIVATE_KEY, PUBLIC_KEY, PSK = [base64.b64encode(bytes([value]) * 32).decode()
                                for value in (17, 23, 31)]
CONFIG = f"""[Interface]
PrivateKey = {PRIVATE_KEY}
Address = 10.67.1.2/32, fd00::2/128
DNS = 10.128.0.1, fd00::1
MTU = 1420

[Peer]
PublicKey = {PUBLIC_KEY}
PresharedKey = {PSK}
Endpoint = airvpn.example.test:1637
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 21
"""
PASSWORD = "PRIVATE_PASSWORD_DO_NOT_PRINT"
ROTATED_PASSWORD = "  PRIVATE_ROTATED_PASSWORD_DO_NOT_PRINT  "
TOKEN = "PRIVATE_TOKEN_DO_NOT_PRINT"
PRIVATE = "PRIVATE_DETAIL_DO_NOT_PRINT"
MAC_UUID = "11111111-1111-4111-8111-111111111111"
IOS_UUID = "00008110-0123456789ABCDEF"
UNRELATED = {"PayloadIdentifier": "com.example.existing",
             "PayloadUUID": "55555555-5555-4555-8555-555555555555"}


class FleetState:
    """Only the API routes used by this operator, backed by in-memory state."""

    def __init__(self):
        self.password = PASSWORD
        self.api = SimpleNamespace(ADMIN_EMAIL="recovery@example.test", initial_password=Mock(return_value=PASSWORD),
                                   request=Mock(side_effect=self.request))
        self.mdm = SimpleNamespace(local_host=Mock(return_value=MAC_UUID),
                                   device_identifier=mdm_helper.device_identifier,
                                   profile_identifiers=mdm_helper.profile_identifiers,
                                   command=Mock(side_effect=self.command))
        self.config = {"license": {"tier": "free"}, "mdm": {"enabled_and_configured": True}}
        self.hosts = {
            MAC_UUID: {"id": 1, "uuid": MAC_UUID, "platform": "darwin"},
            "2": {"id": 2, "uuid": IOS_UUID, "platform": "ios"},
        }
        for host in self.hosts.values():
            host["mdm"] = {"connected_to_fleet": True, "enrollment_status": "On (manual)"}
        self.device_info = {host: {"QueryResponses": {"UDID": host}} for host in (MAC_UUID, IOS_UUID)}
        self.apps = [{"Identifier": "com.wireguard.macos"}, {"Identifier": "com.wireguard.ios"}]
        self.policies, self.installed = [], [copy.deepcopy(UNRELATED)]
        self.keep_policy, self.write_error = True, None

    def request(self, method, path, body=None, token=None, **_kwargs):
        if path == "/api/v1/fleet/login" and method == "POST":
            assert body == {"email": self.api.ADMIN_EMAIL, "password": self.password}
            return {"token": TOKEN}
        assert token == TOKEN
        if path == "/api/v1/fleet/logout" and method == "POST":
            return {}
        if path == "/api/v1/fleet/config" and method == "GET":
            return copy.deepcopy(self.config)
        if path in ("/api/v1/fleet/hosts/2", "/api/v1/fleet/hosts/identifier/" + MAC_UUID) and method == "GET":
            return {"host": copy.deepcopy(self.hosts[path.rsplit("/", 1)[-1]])}
        if path.startswith("/api/v1/fleet/global/policies?") and method == "GET":
            query = parse_qs(urlparse(path).query)
            assert query["per_page"] == ["100"]
            start = int(query["page"][0]) * 100
            return {"policies": copy.deepcopy(self.policies[start:start + 100])}
        if path == "/api/v1/fleet/global/policies" and method == "POST":
            if self.keep_policy:
                self.policies.append(dict(copy.deepcopy(body), id=len(self.policies) + 1))
            return {}
        raise AssertionError("Unexpected API route")

    def command(self, api, token, host, command):
        assert api is self.api and token == TOKEN and host in (MAC_UUID, IOS_UUID)
        action = command["RequestType"]
        if action == "DeviceInformation":
            assert command == {"RequestType": action, "Queries": ["UDID"]}
            return copy.deepcopy(self.device_info[host])
        if action == "InstalledApplicationList":
            bundle = "com.wireguard." + ("macos" if host == MAC_UUID else "ios")
            assert command == {"RequestType": action, "Identifiers": [bundle], "ManagedAppsOnly": False}
            return {"InstalledApplicationList": copy.deepcopy(self.apps)}
        if action == "ProfileList":
            return {"ProfileList": copy.deepcopy(self.installed)}
        if self.write_error:
            raise self.write_error
        if action == "InstallProfile":
            profile = plistlib.loads(command["Payload"])
            self.installed = [item for item in self.installed if item["PayloadIdentifier"] != profile["PayloadIdentifier"]]
            self.installed.append(profile)
            return {}
        if action == "RemoveProfile":
            self.installed = [item for item in self.installed if item["PayloadIdentifier"] != command["Identifier"]]
            return {}
        raise AssertionError("Unexpected MDM command")


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name).resolve() / "private.conf"
        self.path.write_text(CONFIG)
        self.path.chmod(0o600)

    def test_reads_private_owner_file_without_changing_it(self):
        self.assertEqual(helper.read_config(self.path), CONFIG)
        self.assertEqual(self.path.read_text(), CONFIG)

    def test_non_private_missing_relative_directory_and_oversized_inputs_fail(self):
        for mode in (0o644, 0o640, 0o666):
            with self.subTest(mode=mode):
                self.path.chmod(mode)
                with self.assertRaises(helper.SetupError):
                    helper.read_config(self.path)
        self.path.chmod(0o600)
        for path in (Path("private.conf"), self.path.parent, self.path.parent / "missing.conf"):
            with self.subTest(kind=path.name), self.assertRaises(helper.SetupError):
                helper.read_config(path)
        self.path.write_bytes(b"x" * (64 * 1024 + 1))
        with self.assertRaises(helper.SetupError):
            helper.read_config(self.path)

    def test_resolved_symlinks_cannot_read_repository_files(self):
        with patch.object(helper, "ROOT", self.path.parent), self.assertRaises(helper.SetupError):
            helper.read_config(self.path)
        link = self.path.parent / "link.conf"
        link.symlink_to(self.path)
        self.assertEqual(helper.read_config(link), CONFIG)
        directory_link = self.path.parent / "directory-link"
        directory_link.symlink_to(self.path.parent, target_is_directory=True)
        self.assertEqual(helper.read_config(directory_link / self.path.name), CONFIG)
        repository = self.path.parent / "repository"
        repository.mkdir()
        target = repository / "private.conf"
        target.write_text(CONFIG)
        target.chmod(0o600)
        checkout_link = self.path.parent / "checkout.conf"
        checkout_link.symlink_to(target)
        with patch.object(helper, "ROOT", repository), self.assertRaises(helper.SetupError):
            helper.read_config(checkout_link)

    def test_wrong_owner_is_rejected(self):
        with patch.object(helper.os, "getuid", return_value=os.getuid() + 1), \
                self.assertRaises(helper.SetupError):
            helper.read_config(self.path)

    def test_parser_rejects_unsupported_or_malformed_configs_without_echoing_values(self):
        cases = [
            CONFIG.replace("MTU = 1420", "PostUp = " + PRIVATE),
            CONFIG.replace("MTU = 1420", "Table = off"),
            CONFIG.replace(PRIVATE_KEY, PRIVATE),
            CONFIG.replace(PRIVATE_KEY, base64.b64encode(b"too-short").decode()),
            CONFIG.replace("airvpn.example.test:1637", "https://" + PRIVATE + ":1637"),
            CONFIG.replace("airvpn.example.test:1637", "airvpn.example.test:65536"),
            CONFIG.replace("10.67.1.2/32", "999.1.2.3/32"),
            CONFIG.replace("0.0.0.0/0", "0.0.0.0/33"),
            CONFIG.replace("PersistentKeepalive = 21", "PersistentKeepalive = -1"),
            CONFIG.split("[Peer]")[0],
            CONFIG + CONFIG[CONFIG.index("[Peer]"):],
            CONFIG.replace("[Interface]", "[Interface]\nPrivateKey = " + PRIVATE_KEY),
        ]
        for index, content in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(helper.SetupError) as error:
                helper.parse_config(content)
            self.assertNotIn(PRIVATE, str(error.exception))
            self.assertNotIn(PRIVATE_KEY, str(error.exception))


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.catalog = helper.load_catalog()

    def test_both_platform_profiles_preserve_configuration_and_scope(self):
        for platform, device_type in (("macos", 5), ("ios", 1)):
            with self.subTest(platform=platform):
                raw, profile = helper.build_profile(platform, CONFIG, self.catalog)
                self.assertEqual(plistlib.loads(raw), profile)
                self.assertEqual(profile["PayloadType"], "Configuration")
                self.assertEqual(profile["PayloadScope"], "System")
                self.assertEqual(profile["TargetDeviceType"], device_type)
                self.assertIs(profile["PayloadRemovalDisallowed"], False)
                self.assertEqual(len(profile["PayloadContent"]), 1)
                vpn = profile["PayloadContent"][0]
                self.assertEqual(vpn["PayloadType"], "com.apple.vpn.managed")
                self.assertEqual(vpn["VPNType"], "VPN")
                self.assertEqual(vpn["VPNSubType"], "com.wireguard." + platform)
                self.assertEqual(vpn["VPN"]["RemoteAddress"], "airvpn.example.test:1637")
                self.assertEqual(vpn["VendorConfig"]["WgQuickConfig"], CONFIG)
                self.assertNotIn("OnDemandRules", vpn)
                self.assertNotIn("AlwaysOn", vpn)

    def test_identifiers_are_stable_and_config_updates_change_profile_uuid(self):
        for platform in ("macos", "ios"):
            with self.subTest(platform=platform):
                _, first = helper.build_profile(platform, CONFIG, self.catalog)
                _, repeated = helper.build_profile(platform, CONFIG, self.catalog)
                _, changed = helper.build_profile(platform, CONFIG.replace("1637", "1638"), self.catalog)
                self.assertEqual(first["PayloadIdentifier"], repeated["PayloadIdentifier"])
                self.assertEqual(first["PayloadUUID"], repeated["PayloadUUID"])
                self.assertEqual(first["PayloadIdentifier"], changed["PayloadIdentifier"])
                self.assertNotEqual(first["PayloadUUID"], changed["PayloadUUID"])
                raw, removal = helper.removal_profile(platform)
                self.assertEqual(raw, b"")
                self.assertEqual(removal["PayloadIdentifier"], first["PayloadIdentifier"])

    def test_plist_serialization_escapes_supplied_comments(self):
        text = "# Private comment <tag> & quotation\n" + CONFIG
        raw, profile = helper.build_profile("macos", text, self.catalog)
        self.assertEqual(plistlib.loads(raw), profile)
        self.assertEqual(profile["PayloadContent"][0]["VendorConfig"]["WgQuickConfig"], text)
        self.assertIn(b"&lt;tag&gt; &amp;", raw)


class OperatorTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name).resolve() / "private.conf"
        self.path.write_text(CONFIG)
        self.path.chmod(0o600)
        self.password_path = self.path.parent / "operator-password.txt"
        self.state = FleetState()

    def run_command(self, args):
        output = io.StringIO()

        def load(_name, filename):
            return {"fleet-download-apple-csr.py": self.state.api,
                    "fleet-verify-apple-mdm.py": self.state.mdm}[filename]

        with patch.object(helper, "load_setup", return_value=setup) as loader, \
                patch.object(setup, "module", side_effect=load), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                status = helper.main(args)
            except SystemExit as error:
                status = error.code
        text = output.getvalue()
        for secret in (PASSWORD, ROTATED_PASSWORD.strip(), TOKEN, PRIVATE, PRIVATE_KEY, PUBLIC_KEY, PSK,
                       str(self.path), str(self.password_path), MAC_UUID, IOS_UUID):
            self.assertNotIn(secret, text)
        self.assertNotIn("Traceback", text)
        return status, text, loader

    def args(self, platform="macos", *extra):
        return [platform, "--config", str(self.path)] + (["--host-id", "2"] if platform == "ios" else []) + list(extra)

    def assert_logged_out(self):
        self.assertEqual(self.state.api.request.call_args.args, ("POST", "/api/v1/fleet/logout"))
        self.assertEqual(self.state.api.request.call_args.kwargs, {"token": TOKEN})

    def profile_writes(self):
        return [call.args[3] for call in self.state.mdm.command.call_args_list
                if call.args[3]["RequestType"] in ("InstallProfile", "RemoveProfile")]

    def test_all_dry_runs_avoid_credentials_api_and_module_loading(self):
        commands = [["catalog"], ["catalog", "--execute"], ["policy"], self.args(), self.args("ios"),
                    ["macos", "--remove"], ["ios", "--host-id", "2", "--remove"]]
        for args in commands:
            with self.subTest(action=args[0]):
                if args[0] != "catalog":
                    args += ["--password-file", str(self.password_path)]
                status, _, loader = self.run_command(args)
                self.assertEqual(status, 0)
                loader.assert_not_called()
                self.state.api.initial_password.assert_not_called()
                self.state.api.request.assert_not_called()
                self.state.mdm.command.assert_not_called()

    def test_invalid_target_arguments_fail_before_credentials(self):
        commands = [["macos"], ["ios", "--config", str(self.path)], self.args("macos", "--host-id", "2"),
                    self.args("ios", "--host-id", "0"), ["policy", "--remove"],
                    ["policy", "--config", str(self.path)], self.args("macos", "--remove"),
                    ["catalog", "--password-file", str(self.password_path)],
                    [PRIVATE, "--execute"], ["ios", "--host-id", PRIVATE, "--execute"]]
        for args in commands:
            with self.subTest(case=commands.index(args)):
                status, _, loader = self.run_command(args)
                self.assertEqual(status, 2)
                loader.assert_not_called()
                self.state.api.initial_password.assert_not_called()
                self.state.api.request.assert_not_called()

    def test_rotated_password_file_is_used_for_policy_install_and_removal(self):
        commands = [["policy", "--execute"], self.args("macos", "--execute"), self.args("ios", "--execute"),
                    ["macos", "--remove", "--execute"], ["ios", "--host-id", "2", "--remove", "--execute"]]
        for index, args in enumerate(commands):
            with self.subTest(action=args[0], remove="--remove" in args):
                self.state = FleetState()
                self.state.password = ROTATED_PASSWORD
                self.password_path.write_bytes((ROTATED_PASSWORD + ("", "\n", "\r\n")[index % 3]).encode())
                self.password_path.chmod(0o600)
                self.assertEqual(self.run_command(args + ["--password-file", str(self.password_path)])[0], 0)
                self.state.api.initial_password.assert_not_called()
                self.assert_logged_out()

    def test_unsafe_or_malformed_password_file_never_attempts_login(self):
        cases = [(value, 0o600) for value in (b"", b"\n", b"\xff", b"x" * 4097,
                                            b"two\nlines", b"two\rlines", b"embedded\0null", b"two\n\n",
                                            b"two\n\r\n", b"two\r")]
        cases.append((ROTATED_PASSWORD.encode(), 0o644))
        for index, (content, mode) in enumerate(cases):
            with self.subTest(case=index):
                self.state = FleetState()
                self.password_path.write_bytes(content)
                self.password_path.chmod(mode)
                self.assertEqual(self.run_command(["policy", "--execute", "--password-file", str(self.password_path)])[0], 1)
                self.state.api.initial_password.assert_not_called()
                self.state.api.request.assert_not_called()

    def test_rotated_password_login_error_is_redacted_without_bootstrap_fallback(self):
        self.password_path.write_text(ROTATED_PASSWORD)
        self.password_path.chmod(0o600)
        self.state.api.request.side_effect = RuntimeError(ROTATED_PASSWORD + TOKEN)
        self.assertEqual(self.run_command(["policy", "--execute", "--password-file", str(self.password_path)])[0], 1)
        self.state.api.initial_password.assert_not_called()
        self.state.api.request.assert_called_once()
        self.assertEqual(self.state.api.request.call_args.args[:2], ("POST", "/api/v1/fleet/login"))

    def test_invalid_private_export_never_authenticates(self):
        self.path.write_text(CONFIG.replace("MTU = 1420", "PostUp = " + PRIVATE))
        status, _, loader = self.run_command(self.args("macos", "--execute"))
        self.assertEqual(status, 1)
        loader.assert_not_called()
        self.state.api.initial_password.assert_not_called()
        self.state.api.request.assert_not_called()

    def test_install_only_targets_exact_mac_or_explicit_mobile_host(self):
        for platform, expected in (("macos", MAC_UUID), ("ios", IOS_UUID)):
            with self.subTest(platform=platform):
                self.state = FleetState()
                self.assertEqual(self.run_command(self.args(platform, "--execute"))[0], 0)
                self.assertEqual(len(self.profile_writes()), 1)
                self.assertTrue(all(call.args[2] == expected for call in self.state.mdm.command.call_args_list))
                self.assertIn(UNRELATED, self.state.installed)
                if platform == "macos":
                    self.state.mdm.local_host.assert_called_once_with(self.state.api, TOKEN)
                else:
                    self.state.mdm.local_host.assert_not_called()
                self.assertEqual([call.args[:2] for call in self.state.api.request.call_args_list if call.args[0] != "GET"],
                                 [("POST", "/api/v1/fleet/login"), ("POST", "/api/v1/fleet/logout")])
                self.assert_logged_out()

    def test_missing_malformed_or_mismatched_device_udid_prevents_profile_writes(self):
        for platform, target in (("macos", MAC_UUID), ("ios", IOS_UUID)):
            replies = [{}, {"UDID": target}, {"QueryResponses": {}}, {"QueryResponses": None},
                       {"QueryResponses": {"UDID": None}}, {"QueryResponses": {"UDID": PRIVATE}},
                       {"QueryResponses": {"UDID": MAC_UUID if target == IOS_UUID else IOS_UUID}}]
            for index, reply in enumerate(replies):
                with self.subTest(platform=platform, case=index):
                    self.state = FleetState()
                    self.state.device_info[target] = reply
                    self.assertEqual(self.run_command(self.args(platform, "--execute"))[0], 1)
                    self.assertEqual(self.profile_writes(), [])
                    self.assert_logged_out()

    def test_personal_device_enrollment_accepts_matching_case_normalized_udid(self):
        for platform, target, host_key in (("macos", MAC_UUID, MAC_UUID), ("ios", IOS_UUID, "2")):
            with self.subTest(platform=platform):
                self.state = FleetState()
                self.state.hosts[host_key]["mdm"].update(
                    enrollment_status="On (personal)", is_personal_enrollment=True)
                self.state.device_info[target] = {"QueryResponses": {"UDID": target.lower()}}
                self.assertEqual(self.run_command(self.args(platform, "--execute"))[0], 0)
                self.assertEqual(len(self.profile_writes()), 1)
                self.assert_logged_out()

    def test_wrong_or_disconnected_device_prevents_profile_writes(self):
        cases = [("platform", "darwin"), ("id", 3), ("uuid", "not-a-uuid"), ("mdm", {}),
                 ("mdm", {"connected_to_fleet": False, "enrollment_status": "On (manual)"})]
        for key, value in cases:
            with self.subTest(field=key):
                self.state = FleetState()
                self.state.hosts["2"][key] = value
                self.assertEqual(self.run_command(self.args("ios", "--execute"))[0], 1)
                self.assertEqual(self.profile_writes(), [])
                self.assert_logged_out()

    def test_missing_or_failed_app_install_prevents_profile_writes(self):
        for apps in ([], [{"Identifier": "com.wireguard.macos"}],
                     [{"Identifier": "com.wireguard.ios", "DownloadFailed": True}]):
            with self.subTest(apps=apps):
                self.state = FleetState()
                self.state.apps = apps
                self.assertEqual(self.run_command(self.args("ios", "--execute"))[0], 1)
                self.assertEqual(self.profile_writes(), [])
                self.assert_logged_out()

    def test_remove_needs_no_config_and_preserves_other_profiles(self):
        for platform in ("macos", "ios"):
            with self.subTest(platform=platform):
                self.state = FleetState()
                self.state.device_info, self.state.apps = {}, []
                _, profile = helper.build_profile(platform, CONFIG, helper.load_catalog())
                self.state.installed.append(profile)
                args = [platform, "--remove", "--execute"] + (["--host-id", "2"] if platform == "ios" else [])
                self.assertEqual(self.run_command(args)[0], 0)
                self.assertEqual(self.profile_writes(), [{"RequestType": "RemoveProfile", "Identifier": profile["PayloadIdentifier"]}])
                self.assertEqual(self.state.installed, [UNRELATED])
                self.state.mdm.command.reset_mock()
                self.assertEqual(self.run_command(args)[0], 0)
                self.assertEqual(self.profile_writes(), [])
                self.assert_logged_out()

    def test_timeout_never_retries_and_session_is_revoked(self):
        self.state.write_error = TimeoutError(PRIVATE)
        self.assertEqual(self.run_command(self.args("macos", "--execute"))[0], 1)
        self.assertEqual(len(self.profile_writes()), 1)
        self.assert_logged_out()

    def test_policy_is_idempotent_with_fresh_readback_across_pages(self):
        self.state.policies = [{"id": index, "name": "Existing " + str(index)} for index in range(1, 102)]
        self.assertEqual(self.run_command(["policy", "--execute"])[0], 0)
        expected = helper.load_catalog()["policy"]
        self.assertTrue(all(self.state.policies[-1][key] == value for key, value in expected.items()))
        self.assertEqual(len(self.state.policies), 102)
        self.state.api.request.reset_mock()
        self.assertEqual(self.run_command(["policy", "--execute"])[0], 0)
        self.assertFalse(any(call.args[:2] == ("POST", "/api/v1/fleet/global/policies")
                             for call in self.state.api.request.call_args_list))
        self.assertEqual(sum(call.args[0] == "GET" and "&page=1" in call.args[1]
                             for call in self.state.api.request.call_args_list), 2)
        self.state.mdm.command.assert_not_called()
        self.assert_logged_out()

    def test_conflicting_duplicate_or_ambiguous_policy_cannot_be_overwritten(self):
        policy = helper.load_catalog()["policy"]
        cases = [[dict(policy, id=1, query="SELECT 1;")], [dict(policy, id=1), dict(policy, id=2)],
                 [{"id": 1, "name": "Other"}, {"id": 1, "name": "Repeated ID"}]]
        for policies in cases:
            with self.subTest(case=cases.index(policies)):
                self.state = FleetState()
                self.state.policies = copy.deepcopy(policies)
                self.assertEqual(self.run_command(["policy", "--execute"])[0], 1)
                self.assertEqual(self.state.policies, policies)
                self.assertFalse(any(call.args[:2] == ("POST", "/api/v1/fleet/global/policies")
                                     for call in self.state.api.request.call_args_list))
                self.assert_logged_out()

    def test_policy_success_requires_readback(self):
        self.state.keep_policy = False
        self.assertEqual(self.run_command(["policy", "--execute"])[0], 1)
        self.assertEqual(sum(call.args[:2] == ("POST", "/api/v1/fleet/global/policies")
                             for call in self.state.api.request.call_args_list), 1)
        self.assert_logged_out()


if __name__ == "__main__":
    unittest.main()
