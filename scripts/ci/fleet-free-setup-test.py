#!/usr/bin/env python3
"""Safety checks for Fleet Free setup using synthetic API and device state."""

import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import plistlib
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("fleet_free", ROOT / "scripts/fleet-free-setup.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
MDM_SPEC = importlib.util.spec_from_file_location("fleet_mdm_test", ROOT / "scripts/fleet-verify-apple-mdm.py")
mdm_helper = importlib.util.module_from_spec(MDM_SPEC)
MDM_SPEC.loader.exec_module(mdm_helper)
CREDENTIAL_SPEC = importlib.util.spec_from_file_location("fleet_credentials", ROOT / "scripts/fleet-entra-pilot-credentials.py")
credentials = importlib.util.module_from_spec(CREDENTIAL_SPEC)
CREDENTIAL_SPEC.loader.exec_module(credentials)
CSR_SPEC = importlib.util.spec_from_file_location("fleet_csr_identity", ROOT / "scripts/fleet-download-apple-csr.py")
csr = importlib.util.module_from_spec(CSR_SPEC)
CSR_SPEC.loader.exec_module(csr)
BOOTSTRAP_SPEC = importlib.util.spec_from_file_location(
    "fleet_bootstrap_identity", ROOT / "clusters/homelab/apps/fleet/bootstrap.py"
)
bootstrap = importlib.util.module_from_spec(BOOTSTRAP_SPEC)
BOOTSTRAP_SPEC.loader.exec_module(bootstrap)
PASSWORD = "PRIVATE_PASSWORD_DO_NOT_PRINT"
TOKEN = "PRIVATE_SESSION_DO_NOT_PRINT"
RECOVERY_TOKEN = "PRIVATE_RECOVERY_SESSION_DO_NOT_PRINT"
PRIVATE = "PRIVATE_SERVER_OR_DEVICE_DETAIL_DO_NOT_PRINT"
LOCAL_UUID = "11111111-1111-4111-8111-111111111111"
IOS_UUID = "00008110-0123456789ABCDEF"
TENANT = "33333333-3333-4333-8333-333333333333"
APP = "44444444-4444-4444-8444-444444444444"
METADATA = f"https://login.microsoftonline.com/{TENANT}/federationmetadata/2007-06/federationmetadata.xml?appid={APP}"
CERTIFICATE_BYTES = b"synthetic signing certificate bytes for fingerprint binding"
THUMBPRINT = hashlib.sha1(CERTIFICATE_BYTES, usedforsecurity=False).hexdigest().upper()
UNRELATED = {"PayloadIdentifier": "com.example.existing", "PayloadUUID": "55555555-5555-4555-8555-555555555555"}
CATALOG_UNRELATED = {"profile_uuid": "66666666-6666-4666-8666-666666666666", "name": "Existing profile",
                     "identifier": "com.example.existing", "platform": "darwin"}


class FakeAPI:
    ADMIN_EMAIL = "recovery@example.test"
    FLEET_URL = "https://fleet.example.test"

    def __init__(self):
        self.calls = []
        self.errors = {}
        self.config = {"license": {"tier": "free"}, "sso_settings": {"enable_sso": False}}
        self.users = [{"id": 1, "email": self.ADMIN_EMAIL, "sso_enabled": False, "global_role": "admin"}]
        self.credentials = {self.ADMIN_EMAIL: PASSWORD}
        self.sessions = {}
        self.login_failures = set()
        self.host = {"id": 2, "platform": "ios", "uuid": IOS_UUID,
                     "mdm": {"connected_to_fleet": True}}
        self.policies = []
        self.catalog = [copy.deepcopy(CATALOG_UNRELATED)]
        self.catalog_has_next = False
        self.catalog_drop_unrelated = False
        self.catalog_refuse_delete = False
        self.config_refuse_sso_update = False
        self.create_user_drop = False
        self.commit_then_errors = {}
        self.initial_password = Mock(return_value=PASSWORD)
        self.password_login = Mock(side_effect=self.login_with_password)

    def login_with_password(self, password=None):
        password = self.initial_password() if password is None else password
        return self.request("POST", "/api/v1/fleet/login", {
            "email": self.ADMIN_EMAIL, "password": password,
        }).get("token")

    def console_topology(self, final=False):
        self.ADMIN_EMAIL = helper.RECOVERY_USER
        self.users = [
            {"id": 1, "email": helper.CONSOLE_USER, "sso_enabled": final, "global_role": "admin"},
            {"id": 2, "email": helper.RECOVERY_USER, "sso_enabled": not final, "global_role": "admin"},
        ]
        self.credentials = ({helper.RECOVERY_USER: PASSWORD} if final
                            else {helper.CONSOLE_USER: PASSWORD})

    def clean_console_topology(self):
        self.ADMIN_EMAIL = helper.RECOVERY_USER
        self.users = [{"id": 1, "email": helper.RECOVERY_USER, "sso_enabled": False, "global_role": "admin"}]
        self.credentials = {helper.RECOVERY_USER: PASSWORD}

    def legacy_target_topology(self, password=PASSWORD):
        self.ADMIN_EMAIL = helper.CONSOLE_USER
        self.users = [{"id": 1, "email": helper.CONSOLE_USER, "sso_enabled": False, "global_role": "admin"}]
        self.credentials = {helper.CONSOLE_USER: password}

    def user(self, email):
        return next((user for user in self.users if user.get("email") == email), None)

    def request(self, method, path, body=None, token=None, content_type="application/json", accepted_status=200):
        self.calls.append((method, path, copy.deepcopy(body), token))
        if (method, path) in self.errors:
            raise self.errors[method, path]
        if path == "/api/v1/fleet/login":
            if method != "POST" or not isinstance(body, dict):
                raise AssertionError("Unexpected login")
            email, password = body.get("email"), body.get("password")
            if email in self.login_failures or self.credentials.get(email) != password:
                return {}
            session = RECOVERY_TOKEN if email == helper.RECOVERY_USER else TOKEN
            self.sessions[session] = email
            return {"token": session}
        if token not in self.sessions:
            raise AssertionError("Unauthenticated API call")
        if path == "/api/v1/fleet/logout" and method == "POST":
            self.sessions.pop(token, None)
            return {}
        if path == "/api/v1/fleet/me" and method == "GET":
            user = self.user(self.sessions[token])
            if user is None:
                raise AssertionError("Session user missing")
            return {"user": copy.deepcopy(user)}
        if path == "/api/v1/fleet/config":
            if method == "PATCH":
                if not self.config_refuse_sso_update:
                    self.config.update(copy.deepcopy(body))
            return copy.deepcopy(self.config)
        if path == "/api/v1/fleet/users?per_page=100" and method == "GET":
            return {"users": copy.deepcopy(self.users)}
        if path == "/api/v1/fleet/users/admin" and method == "POST":
            if not isinstance(body, dict):
                raise AssertionError("Invalid user creation")
            user = dict(copy.deepcopy(body), id=max(user["id"] for user in self.users) + 1)
            password = user.pop("password", None)
            if user.get("sso_enabled") is False:
                if not isinstance(password, str):
                    raise AssertionError("Local administrator requires a password")
                self.credentials[user["email"]] = password
            elif password is not None:
                raise AssertionError("SSO administrator must not have a password")
            if not self.create_user_drop:
                self.users.append(user)
            return {}
        if path.startswith("/api/v1/fleet/users/") and method == "PATCH":
            try:
                user_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                raise AssertionError("Invalid user update route") from None
            user = next((item for item in self.users if item.get("id") == user_id), None)
            if user is None or not isinstance(body, dict):
                raise AssertionError("Unknown user update")
            if body == {"sso_enabled": False, "new_password": PASSWORD}:
                user["sso_enabled"] = False
                self.credentials[user["email"]] = PASSWORD
                return {}
            if body == {"sso_enabled": True}:
                user["sso_enabled"] = True
                self.credentials.pop(user["email"], None)
                error = self.commit_then_errors.pop((method, path), None)
                if error is not None:
                    raise error
                return {}
            raise AssertionError("Unexpected user update")
        if path == "/api/v1/fleet/hosts/2" and method == "GET":
            return {"host": copy.deepcopy(self.host)}
        if path == "/api/v1/fleet/global/policies?per_page=100" and method == "GET":
            return {"policies": copy.deepcopy(self.policies)}
        if path == "/api/v1/fleet/global/policies" and method == "POST":
            self.policies.append(copy.deepcopy(body))
            return {}
        if path == "/api/v1/fleet/configuration_profiles/batch?dry_run=true" and method == "POST":
            if accepted_status != 204:
                raise AssertionError("Profile validation must require the documented empty 204")
            return {}
        if path == "/api/v1/fleet/configuration_profiles?per_page=100" and method == "GET":
            return {"profiles": copy.deepcopy(self.catalog), "meta": {"has_next_results": self.catalog_has_next}}
        if path.startswith("/api/v1/fleet/configuration_profiles/") and method == "DELETE":
            if accepted_status != 200:
                raise AssertionError("Profile deletion must require HTTP 200")
            if not self.catalog_refuse_delete:
                self.catalog = [item for item in self.catalog if item["profile_uuid"] != path.rsplit("/", 1)[1]]
            if self.catalog_drop_unrelated:
                self.catalog.remove(CATALOG_UNRELATED)
            return {}
        raise AssertionError("Unexpected API route")


class FakeMDM:
    device_identifier = staticmethod(mdm_helper.device_identifier)

    def __init__(self):
        self.calls = []
        self.local_host = Mock(return_value=LOCAL_UUID)
        self.installed = [copy.deepcopy(UNRELATED)]
        self.drop_unrelated = False
        self.install_error = None
        self.security = {"PasscodePresent": True, "PasscodeCompliant": True,
                         "PasscodeCompliantWithProfiles": True}

    @staticmethod
    def profile_identifiers(reply):
        return {item["PayloadIdentifier"] for item in reply["ProfileList"]}

    def command(self, api, token, host, command):
        if token != TOKEN:
            raise AssertionError("Unexpected MDM token")
        self.calls.append((host, copy.deepcopy(command)))
        request = command["RequestType"]
        if request == "ProfileList":
            return {"ProfileList": copy.deepcopy(self.installed)}
        if request == "InstallProfile":
            if self.install_error:
                raise self.install_error
            profile = plistlib.loads(command["Payload"])
            self.installed = [item for item in self.installed
                              if item["PayloadIdentifier"] != profile["PayloadIdentifier"]]
            self.installed.append(profile)
            if self.drop_unrelated:
                self.installed = [item for item in self.installed
                                  if item["PayloadIdentifier"] != UNRELATED["PayloadIdentifier"]]
            return {}
        if request == "RemoveProfile":
            self.installed = [item for item in self.installed
                              if item["PayloadIdentifier"] != command["Identifier"]]
            return {}
        if request == "SecurityInfo":
            return {"SecurityInfo": copy.deepcopy(self.security)}
        raise AssertionError("Unexpected MDM command")


class FleetFreeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.profiles = Path(self.directory.name)
        for name in helper.MAC_FILES + helper.LEGACY_MAC_FILES + helper.IOS_FILES:
            shutil.copyfile(helper.PROFILES / name, self.profiles / name)
        self.api, self.mdm = FakeAPI(), FakeMDM()
        self.private_input = Mock()
        self.private_input.read_password.return_value = PASSWORD

    def run_command(self, argv):
        output = io.StringIO()

        def load(_name, filename):
            if filename == "fleet-download-apple-csr.py":
                return self.api
            if filename == "fleet-verify-apple-mdm.py":
                return self.mdm
            if filename == "fleet-airvpn-setup.py":
                return self.private_input
            raise AssertionError("Unexpected module load")

        with patch.object(helper, "PROFILES", self.profiles), \
                patch.object(helper, "module", side_effect=load) as loader, \
                patch.object(helper, "saml_outputs", return_value=(METADATA, TENANT, THUMBPRINT)), \
                patch.object(helper, "validate_metadata"), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = helper.main(argv)
        text = output.getvalue()
        for secret in (PASSWORD, TOKEN, RECOVERY_TOKEN, PRIVATE, LOCAL_UUID, IOS_UUID):
            self.assertNotIn(secret, text)
        self.assertNotIn("Traceback", text)
        return status, text, loader

    def assert_logged_out(self):
        self.assertEqual(self.api.calls[-1][0:3], ("POST", "/api/v1/fleet/logout", None))
        self.assertIn(self.api.calls[-1][3], (TOKEN, RECOVERY_TOKEN))

    def assert_no_setup_mutations(self):
        self.assertEqual(self.mdm.calls, [])
        self.assertFalse(any(method in ("PATCH", "PUT", "DELETE") or
                             (method == "POST" and path not in
                              ("/api/v1/fleet/login", "/api/v1/fleet/logout"))
                             for method, path, _, _ in self.api.calls))

    def change_profile(self, filename, key, value):
        path = self.profiles / filename
        profile = plistlib.loads(path.read_bytes())
        profile[key] = value
        path.write_bytes(plistlib.dumps(profile))

    def seed_legacy_catalog(self):
        raw = (self.profiles / helper.LEGACY_MAC_FILES[0]).read_bytes()
        profile = plistlib.loads(raw)
        entry = {"profile_uuid": "77777777-7777-4777-8777-777777777777", "platform": "darwin",
                 "identifier": profile["PayloadIdentifier"], "name": profile["PayloadDisplayName"],
                 "checksum": base64.b64encode(hashlib.md5(raw, usedforsecurity=False).digest()).decode()}
        self.api.catalog.append(entry)
        return entry

    @staticmethod
    def sso_settings():
        return {
            "enable_sso": True, "idp_name": "Microsoft Entra ID", "entity_id": FakeAPI.FLEET_URL,
            "issuer_uri": "", "metadata_url": METADATA, "metadata": "",
            "enable_jit_provisioning": False, "enable_sso_idp_login": False,
        }

    def console_migration(self):
        return self.run_command([
            "console-sso", "--current-password-file", "/private/current-fleet-password", "--execute",
        ])

    def test_every_dry_run_avoids_credentials_modules_and_api(self):
        for action in ("validate-profiles", "mac-pilot", "mac-baseline", "mac-psso", "ios-baseline", "mac-baseline-catalog", "console-sso", "reporting"):
            with self.subTest(action=action):
                args = [action]
                if action in ("mac-baseline", "mac-psso", "ios-baseline"):
                    args += ["--host-id", "2"]
                if action == "mac-baseline-catalog":
                    args += ["--remove"]
                status, output, loader = self.run_command(args)
                self.assertEqual(status, 0)
                loader.assert_not_called()
                self.api.initial_password.assert_not_called()
                self.assertEqual(self.api.calls, [])
                self.assertEqual(self.mdm.calls, [])
                if action == "mac-psso":
                    self.assertIn("mac-psso targets only the selected Fleet-enrolled Mac", output)
                if action == "console-sso":
                    self.assertIn("--current-password-file is legacy-only", output)

    def test_current_password_file_is_rejected_outside_console_sso(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as error:
            helper.main(["reporting", "--current-password-file", "/private/current-fleet-password", "--execute"])
        self.assertEqual(error.exception.code, 2)
        self.assertNotIn("/private/current-fleet-password", output.getvalue())
        self.assertEqual(self.api.calls, [])

    def test_wrong_platform_and_boolean_platform_fail_before_login(self):
        for filename, value in ((helper.MAC_FILES[0], 1), (helper.MAC_FILES[0], 2),
                                (helper.MAC_FILES[0], True), (helper.IOS_FILES[0], 5),
                                (helper.IOS_FILES[0], True)):
            with self.subTest(filename=filename, value=value):
                path = self.profiles / filename
                original = path.read_bytes()
                self.change_profile(filename, "TargetDeviceType", value)
                status, _, loader = self.run_command(["mac-pilot", "--execute"])
                self.assertEqual(status, 1)
                loader.assert_not_called()
                self.assertEqual(self.api.calls, [])
                path.write_bytes(original)

    def test_scope_ownership_and_removability_fail_closed(self):
        filename = helper.MAC_FILES[0]
        original = (self.profiles / filename).read_bytes()
        for key, value in (("PayloadScope", "User"), ("PayloadRemovalDisallowed", True),
                           ("PayloadIdentifier", "com.example.unrelated")):
            with self.subTest(key=key):
                self.change_profile(filename, key, value)
                self.assertEqual(self.run_command(["mac-pilot", "--execute"])[0], 1)
                self.assertEqual(self.api.calls, [])
                (self.profiles / filename).write_bytes(original)

    def test_mac_uses_exact_identity_guard_and_preserves_other_profiles(self):
        baseline, psso = [plistlib.loads((self.profiles / name).read_bytes()) for name in helper.MAC_FILES]
        self.mdm.installed += [baseline, psso]
        status, output, _ = self.run_command(["mac-pilot", "--execute"])
        self.assertEqual(status, 0)
        self.mdm.local_host.assert_called_once_with(self.api, TOKEN)
        self.assertTrue(all(host == LOCAL_UUID for host, _ in self.mdm.calls))
        self.assertIn(UNRELATED, self.mdm.installed)
        self.assertEqual([command["RequestType"] for _, command in self.mdm.calls], [
            "ProfileList", "RemoveProfile", "ProfileList", "ProfileList",
            "InstallProfile", "InstallProfile", "ProfileList",
        ])
        removals = [command["Identifier"] for _, command in self.mdm.calls
                    if command["RequestType"] == "RemoveProfile"]
        self.assertEqual(removals, [psso["PayloadIdentifier"]])
        self.assertEqual(self.mdm.installed, [UNRELATED, baseline, psso])
        self.assertIn("Existing Platform SSO profile absence and baseline/unrelated-profile retention: verified", output)
        self.assert_logged_out()

    def test_individual_mac_baseline_preserves_settings_with_distinct_profile_identities(self):
        current = plistlib.loads((self.profiles / helper.MAC_FILES[0]).read_bytes())
        legacy = plistlib.loads((self.profiles / helper.LEGACY_MAC_FILES[0]).read_bytes())

        def without_identity(value, identities):
            if isinstance(value, dict):
                for key in ("PayloadIdentifier", "PayloadUUID"):
                    if key in value:
                        identities.add(value[key])
                return {key: without_identity(item, identities) for key, item in value.items()
                        if key not in ("PayloadIdentifier", "PayloadUUID")}
            if isinstance(value, list):
                return [without_identity(item, identities) for item in value]
            return value

        current_ids, legacy_ids = set(), set()
        self.assertEqual(without_identity(current, current_ids), without_identity(legacy, legacy_ids))
        self.assertEqual(len(current_ids), 4)
        self.assertEqual(len(legacy_ids), 4)
        self.assertTrue(current_ids.isdisjoint(legacy_ids))

    def test_mac_baseline_targets_only_selected_connected_mac_and_one_profile(self):
        self.api.host = {"id": 2, "platform": "darwin", "uuid": LOCAL_UUID,
                         "mdm": {"connected_to_fleet": True}}
        legacy = plistlib.loads((self.profiles / helper.LEGACY_MAC_FILES[0]).read_bytes())
        self.mdm.installed.append(legacy)
        self.assertEqual(self.run_command(["mac-baseline", "--host-id", "2", "--execute"])[0], 0)
        expected = plistlib.loads((self.profiles / helper.MAC_FILES[0]).read_bytes())
        self.assertTrue(all(host == LOCAL_UUID for host, _ in self.mdm.calls))
        self.assertEqual([command["RequestType"] for _, command in self.mdm.calls],
                         ["ProfileList", "InstallProfile", "ProfileList"])
        self.assertEqual(self.mdm.installed, [UNRELATED, legacy, expected])
        self.assertEqual(self.api.catalog, [CATALOG_UNRELATED])
        self.mdm.local_host.assert_not_called()
        self.assert_logged_out()

    def test_mac_baseline_rejects_wrong_identity_platform_or_disconnected_mdm(self):
        connected = {"id": 2, "platform": "darwin", "uuid": LOCAL_UUID,
                     "mdm": {"connected_to_fleet": True}}
        for field, value in (("platform", "ios"), ("platform", "ipados"), ("platform", "linux"),
                             ("id", 3), ("uuid", "not-a-uuid"), ("mdm", {}),
                             ("mdm", {"connected_to_fleet": False}),
                             ("mdm", {"connected_to_fleet": "true"})):
            with self.subTest(field=field, value=value):
                self.api.host = dict(connected, **{field: value})
                self.assertEqual(self.run_command(["mac-baseline", "--host-id", "2", "--execute"])[0], 1)
                self.assert_no_setup_mutations()
                self.mdm.local_host.assert_not_called()
                self.assert_logged_out()

    def test_mac_psso_rejects_wrong_identity_platform_or_disconnected_mdm(self):
        connected = {"id": 2, "platform": "darwin", "uuid": LOCAL_UUID,
                     "mdm": {"connected_to_fleet": True}}
        for field, value in (("platform", "ios"), ("id", 3),
                             ("mdm", {"connected_to_fleet": False})):
            with self.subTest(field=field, value=value):
                self.api.host = dict(connected, **{field: value})
                self.assertEqual(self.run_command(["mac-psso", "--host-id", "2", "--execute"])[0], 1)
                self.assert_no_setup_mutations()
                self.mdm.local_host.assert_not_called()
                self.assert_logged_out()

    def test_mac_baseline_removes_only_individual_profile_and_is_idempotent(self):
        self.api.host = {"id": 2, "platform": "darwin", "uuid": LOCAL_UUID,
                         "mdm": {"connected_to_fleet": True}}
        baseline, entra = [plistlib.loads((self.profiles / name).read_bytes()) for name in helper.MAC_FILES]
        legacy = plistlib.loads((self.profiles / helper.LEGACY_MAC_FILES[0]).read_bytes())
        self.mdm.installed += [baseline, entra, legacy]
        args = ["mac-baseline", "--host-id", "2", "--remove", "--execute"]
        self.assertEqual(self.run_command(args)[0], 0)
        self.assertEqual([command for _, command in self.mdm.calls], [
            {"RequestType": "ProfileList"},
            {"RequestType": "RemoveProfile", "Identifier": baseline["PayloadIdentifier"]},
            {"RequestType": "ProfileList"},
        ])
        self.assertTrue(all(host == LOCAL_UUID for host, _ in self.mdm.calls))
        self.assertEqual(self.mdm.installed, [UNRELATED, entra, legacy])
        self.mdm.local_host.assert_not_called()
        self.assert_logged_out()
        self.mdm.calls.clear()
        self.assertEqual(self.run_command(args)[0], 0)
        self.assertTrue(all(command["RequestType"] == "ProfileList" for _, command in self.mdm.calls))
        self.assertEqual(self.mdm.installed, [UNRELATED, entra, legacy])

    def test_mac_psso_targets_only_selected_mac_and_preserves_baseline_on_removal(self):
        self.api.host = {"id": 2, "platform": "darwin", "uuid": LOCAL_UUID,
                         "mdm": {"connected_to_fleet": True}}
        baseline, entra = [plistlib.loads((self.profiles / name).read_bytes()) for name in helper.MAC_FILES]
        self.assertIn("Microsoft Authenticator", entra["PayloadDescription"])
        self.mdm.installed.append(baseline)
        args = ["mac-psso", "--host-id", "2", "--execute"]
        self.assertEqual(self.run_command(args)[0], 0)
        self.assertTrue(all(host == LOCAL_UUID for host, _ in self.mdm.calls))
        self.assertEqual([command["RequestType"] for _, command in self.mdm.calls],
                         ["ProfileList", "InstallProfile", "ProfileList"])
        self.assertEqual(self.mdm.installed, [UNRELATED, baseline, entra])
        self.mdm.local_host.assert_not_called()
        self.assert_logged_out()

        self.mdm.calls.clear()
        self.assertEqual(self.run_command(args[:-1] + ["--remove", "--execute"])[0], 0)
        self.assertEqual([command for _, command in self.mdm.calls], [
            {"RequestType": "ProfileList"},
            {"RequestType": "RemoveProfile", "Identifier": entra["PayloadIdentifier"]},
            {"RequestType": "ProfileList"},
        ])
        self.assertEqual(self.mdm.installed, [UNRELATED, baseline])
        self.mdm.local_host.assert_not_called()
        self.assert_logged_out()

    def test_ios_baseline_targets_only_selected_device_and_reports_security_info(self):
        for platform in ("ios", "ipados"):
            with self.subTest(platform=platform):
                self.api, self.mdm = FakeAPI(), FakeMDM()
                self.api.host["platform"] = platform
                status, output, _ = self.run_command(["ios-baseline", "--host-id", "2", "--execute"])
                expected = plistlib.loads((self.profiles / helper.IOS_FILES[0]).read_bytes())
                self.assertEqual(status, 0)
                self.assertTrue(all(host == IOS_UUID for host, _ in self.mdm.calls))
                self.assertEqual([command["RequestType"] for _, command in self.mdm.calls],
                                 ["ProfileList", "InstallProfile", "ProfileList", "SecurityInfo"])
                passcode = next(json.loads(line) for line in output.splitlines() if line.startswith("{"))
                self.assertEqual(passcode, self.mdm.security)
                self.assertEqual(self.mdm.installed, [UNRELATED, expected])
                self.assertEqual(self.api.catalog, [CATALOG_UNRELATED])
                self.mdm.local_host.assert_not_called()
                self.assert_logged_out()

    def test_ios_baseline_rejects_wrong_identity_or_platform_before_commands(self):
        for field, value in (("platform", "darwin"), ("platform", "linux"), ("id", 3),
                             ("uuid", "not-a-uuid"), ("mdm", {}),
                             ("mdm", {"connected_to_fleet": False}),
                             ("mdm", {"connected_to_fleet": "true"})):
            with self.subTest(field=field, value=value):
                self.api.host[field] = value
                self.assertEqual(self.run_command(["ios-baseline", "--host-id", "2", "--execute"])[0], 1)
                self.assert_no_setup_mutations()
                self.mdm.local_host.assert_not_called()
                self.assert_logged_out()
                self.api.host = {"id": 2, "platform": "ios", "uuid": IOS_UUID,
                                 "mdm": {"connected_to_fleet": True}}

    def test_ios_baseline_removes_only_selected_profile_and_is_idempotent(self):
        profile = plistlib.loads((self.profiles / helper.IOS_FILES[0]).read_bytes())
        self.mdm.installed.append(profile)
        args = ["ios-baseline", "--host-id", "2", "--remove", "--execute"]
        self.assertEqual(self.run_command(args)[0], 0)
        self.assertEqual([command for _, command in self.mdm.calls], [
            {"RequestType": "ProfileList"},
            {"RequestType": "RemoveProfile", "Identifier": profile["PayloadIdentifier"]},
            {"RequestType": "ProfileList"},
        ])
        self.assertTrue(all(host == IOS_UUID for host, _ in self.mdm.calls))
        self.assertEqual(self.mdm.installed, [UNRELATED])
        self.assertEqual(self.api.catalog, [CATALOG_UNRELATED])
        self.mdm.local_host.assert_not_called()
        self.assert_logged_out()
        self.mdm.calls.clear()
        self.assertEqual(self.run_command(args)[0], 0)
        self.assertTrue(all(command["RequestType"] == "ProfileList" for _, command in self.mdm.calls))
        self.assertEqual(self.mdm.installed, [UNRELATED])

    def test_ios_security_info_types_fail_closed_without_leaking_values(self):
        for key, value, message in ((None, PRIVATE, "Passcode security response is invalid"),
                                    ("PasscodePresent", PRIVATE,
                                     "Passcode security response has an invalid value type"),
                                    ("PasscodeCompliant", 1,
                                     "Passcode security response has an invalid value type"),
                                    ("PasscodeCompliantWithProfiles", "yes",
                                     "Passcode security response has an invalid value type")):
            with self.subTest(key=key, value_type=type(value).__name__):
                if key is None:
                    self.mdm.security = value
                else:
                    self.mdm.security[key] = value
                status, output, _ = self.run_command(["ios-baseline", "--host-id", "2", "--execute"])
                self.assertEqual(status, 1)
                self.assertIn(message, output)
                self.assertEqual(self.mdm.calls[-1][1]["RequestType"], "SecurityInfo")
                self.assert_logged_out()
                self.mdm = FakeMDM()

    def test_selected_device_actions_require_positive_host_ids_before_loading_credentials(self):
        for action in ("mac-baseline", "mac-psso", "ios-baseline"):
            for host_args in ([], ["--host-id", "0"], ["--host-id", "-1"]):
                with self.subTest(action=action, host_args=host_args), \
                        patch.object(helper, "module") as loader, \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    helper.main([action, "--remove", "--execute"] + host_args)
                self.assertEqual(error.exception.code, 2)
                loader.assert_not_called()
                self.api.initial_password.assert_not_called()
                self.assertEqual(self.api.calls, [])
                self.assertEqual(self.mdm.calls, [])

    def test_server_profile_validation_cannot_assign_profiles(self):
        self.assertEqual(self.run_command(["validate-profiles", "--execute"])[0], 0)
        writes = [(method, path) for method, path, _, _ in self.api.calls if method != "GET"]
        self.assertEqual(writes, [("POST", "/api/v1/fleet/login"),
                                  ("POST", "/api/v1/fleet/configuration_profiles/batch?dry_run=true"),
                                  ("POST", "/api/v1/fleet/logout")])
        submitted = [plistlib.loads(base64.b64decode(item["profile"]))
                     for item in self.api.calls[2][2]["configuration_profiles"]]
        self.assertEqual([profile["PayloadIdentifier"] for profile in submitted],
                         [profile["PayloadIdentifier"] for _, profile in
                          helper.profiles(helper.MAC_FILES, 5) + helper.profiles(helper.IOS_FILES, 1)])
        self.assertEqual([profile["TargetDeviceType"] for profile in submitted], [5, 5, 1])
        self.assertEqual(self.mdm.calls, [])
        self.assert_logged_out()

    def test_identity_mismatch_cannot_queue_any_command(self):
        self.mdm.local_host.side_effect = RuntimeError(PRIVATE)
        self.assertEqual(self.run_command(["mac-pilot", "--execute"])[0], 1)
        self.assert_no_setup_mutations()
        self.assert_logged_out()

    def test_retired_catalog_upload_is_rejected_before_credentials_modules_and_api(self):
        for flags in ([], ["--execute"]):
            with self.subTest(flags=flags):
                status, output, loader = self.run_command(["mac-baseline-catalog"] + flags)
                self.assertEqual(status, 1)
                self.assertIn("mac-baseline-catalog requires --remove", output)
                loader.assert_not_called()
                self.api.initial_password.assert_not_called()
                self.assertEqual(self.api.calls, [])
                self.assertEqual(self.mdm.calls, [])

    def test_catalog_upload_function_cannot_bypass_cli_guard(self):
        with self.assertRaises(helper.SetupError):
            helper.mac_baseline_catalog(self.api, TOKEN)
        self.assertEqual(self.api.calls, [])

    def test_catalog_incomplete_listing_cannot_remove_profiles(self):
        self.seed_legacy_catalog()
        for has_next in (True, None):
            with self.subTest(has_next=has_next):
                self.api.catalog_has_next = has_next
                self.assertEqual(self.run_command(["mac-baseline-catalog", "--remove", "--execute"])[0], 1)
                self.assert_no_setup_mutations()
                self.assert_logged_out()

    def test_catalog_non_free_license_cannot_remove_profiles(self):
        self.seed_legacy_catalog()
        self.api.config["license"] = {"tier": "premium"}
        self.assertEqual(self.run_command(["mac-baseline-catalog", "--remove", "--execute"])[0], 1)
        self.assert_no_setup_mutations()
        self.assert_logged_out()

    def test_catalog_removal_is_idempotent_and_preserves_unrelated_profiles(self):
        profile_uuid = self.seed_legacy_catalog()["profile_uuid"]
        self.assertEqual(self.run_command(["mac-baseline-catalog", "--remove", "--execute"])[0], 0)
        self.assertEqual([(method, path) for method, path, _, _ in self.api.calls if method != "GET"], [
            ("POST", "/api/v1/fleet/login"),
            ("DELETE", "/api/v1/fleet/configuration_profiles/" + profile_uuid),
            ("POST", "/api/v1/fleet/logout"),
        ])
        self.assertEqual(self.api.catalog, [CATALOG_UNRELATED])
        self.assertEqual(self.mdm.calls, [])
        self.assert_logged_out()
        self.api.calls.clear()
        self.assertEqual(self.run_command(["mac-baseline-catalog", "--remove", "--execute"])[0], 0)
        self.assert_no_setup_mutations()
        self.assertEqual(self.api.catalog, [CATALOG_UNRELATED])
        self.assert_logged_out()

    def test_catalog_removal_refuses_conflicting_content(self):
        self.seed_legacy_catalog()["checksum"] = "different-content"
        self.assertEqual(self.run_command(["mac-baseline-catalog", "--remove", "--execute"])[0], 1)
        self.assert_no_setup_mutations()
        self.assert_logged_out()

    def test_catalog_removal_verifies_absence_and_unrelated_retention(self):
        for flag in ("catalog_refuse_delete", "catalog_drop_unrelated"):
            with self.subTest(flag=flag):
                self.api = FakeAPI()
                self.seed_legacy_catalog()
                setattr(self.api, flag, True)
                self.assertEqual(self.run_command(["mac-baseline-catalog", "--remove", "--execute"])[0], 1)
                self.assertEqual(self.mdm.calls, [])
                self.assert_logged_out()

    def test_catalog_failed_delete_is_not_retried(self):
        path = "/api/v1/fleet/configuration_profiles/" + self.seed_legacy_catalog()["profile_uuid"]
        self.api.errors["DELETE", path] = TimeoutError(PRIVATE)
        self.assertEqual(self.run_command(["mac-baseline-catalog", "--remove", "--execute"])[0], 1)
        self.assertEqual(sum(method == "DELETE" for method, _, _, _ in self.api.calls), 1)
        self.assertEqual(len(self.api.catalog), 2)
        self.assertEqual(self.mdm.calls, [])
        self.assert_logged_out()

    def test_remove_is_idempotent_and_never_removes_another_profile(self):
        for name in helper.MAC_FILES:
            self.mdm.installed.append(plistlib.loads((self.profiles / name).read_bytes()))
        self.assertEqual(self.run_command(["mac-pilot", "--remove", "--execute"])[0], 0)
        removals = [command["Identifier"] for _, command in self.mdm.calls
                    if command["RequestType"] == "RemoveProfile"]
        self.assertEqual(len(removals), 2)
        self.assertNotIn(UNRELATED["PayloadIdentifier"], removals)
        self.assertEqual(self.mdm.installed, [UNRELATED])
        self.mdm.calls.clear()
        self.assertEqual(self.run_command(["mac-pilot", "--remove", "--execute"])[0], 0)
        self.assertTrue(all(command["RequestType"] == "ProfileList" for _, command in self.mdm.calls))
        self.assert_logged_out()

    def test_unrelated_profile_loss_is_not_reported_as_success(self):
        self.mdm.drop_unrelated = True
        self.assertEqual(self.run_command(["mac-pilot", "--execute"])[0], 1)
        self.assert_logged_out()

    def test_timeout_does_not_retry_install_or_remove_profiles(self):
        self.mdm.install_error = TimeoutError(PRIVATE)
        self.assertEqual(self.run_command(["mac-pilot", "--execute"])[0], 1)
        self.assertEqual([command["RequestType"] for _, command in self.mdm.calls],
                         ["ProfileList", "ProfileList", "ProfileList", "InstallProfile"])
        self.assert_logged_out()

    def test_non_free_and_unknown_license_prevent_all_setup_writes(self):
        for license_info in ({"tier": "premium"}, {"tier": "trial"}, {}, None):
            with self.subTest(license_info=license_info):
                self.api.config["license"] = license_info
                self.assertEqual(self.run_command(["mac-pilot", "--execute"])[0], 1)
                self.assert_no_setup_mutations()
                self.assert_logged_out()

    def test_conflicting_sso_provider_is_not_replaced(self):
        self.api.console_topology()
        self.api.config["sso_settings"] = {"enable_sso": True, "metadata_url": "https://other.example.test/metadata"}
        self.assertEqual(self.console_migration()[0], 1)
        self.assert_no_setup_mutations()
        self.assert_logged_out()

    def test_conflicting_or_duplicate_console_users_are_not_converted(self):
        self.api.console_topology()
        users = [
            [{"id": 1, "email": helper.CONSOLE_USER, "sso_enabled": True, "global_role": "admin"}],
            [{"id": 1, "email": helper.CONSOLE_USER, "sso_enabled": True, "global_role": "admin"},
             {"id": 2, "email": helper.RECOVERY_USER, "sso_enabled": True, "global_role": "admin"}],
            [{"id": 1, "email": helper.CONSOLE_USER, "sso_enabled": False, "global_role": "admin"},
             {"id": 2, "email": helper.RECOVERY_USER, "sso_enabled": True, "global_role": "observer"}],
            [{"id": 1, "email": helper.CONSOLE_USER, "sso_enabled": False, "global_role": "admin"},
             {"id": 1, "email": helper.CONSOLE_USER, "sso_enabled": False, "global_role": "admin"},
             {"id": 2, "email": helper.RECOVERY_USER, "sso_enabled": True, "global_role": "admin"}],
            [{"id": 1, "email": helper.CONSOLE_USER, "sso_enabled": False, "global_role": "admin"},
             {"id": 2, "email": helper.RECOVERY_USER, "sso_enabled": True, "global_role": "admin"},
             {"id": 3, "email": "other@example.test", "sso_enabled": False, "global_role": "admin"}],
        ]
        for existing in users:
            with self.subTest(users=existing):
                self.api.users = copy.deepcopy(existing)
                self.assertEqual(self.console_migration()[0], 1)
                self.assert_no_setup_mutations()
                self.assertEqual(self.api.users, existing)
                self.assert_logged_out()
                self.api.calls.clear()

    def test_console_migration_verifies_local_recovery_before_switching_target_to_sso(self):
        self.api.console_topology()
        self.assertEqual(self.console_migration()[0], 0)
        self.private_input.read_password.assert_called_once_with(Path("/private/current-fleet-password"))
        self.assertEqual(self.api.initial_password.call_count, 1)
        self.assertTrue(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        self.assertFalse(self.api.user(helper.RECOVERY_USER)["sso_enabled"])
        self.assertEqual(self.api.credentials, {helper.RECOVERY_USER: PASSWORD})
        self.assertEqual(self.api.config["sso_settings"], self.sso_settings())
        routes = [(method, path) for method, path, _, _ in self.api.calls]
        recovery_update = routes.index(("PATCH", "/api/v1/fleet/users/2"))
        recovery_login = [index for index, route in enumerate(routes) if route == ("POST", "/api/v1/fleet/login")][1]
        recovery_logout = next(index for index, call in enumerate(self.api.calls)
                               if call == ("POST", "/api/v1/fleet/logout", None, RECOVERY_TOKEN))
        config_update = routes.index(("PATCH", "/api/v1/fleet/config"))
        target_update = routes.index(("PATCH", "/api/v1/fleet/users/1"))
        self.assertLess(recovery_update, recovery_login)
        self.assertLess(recovery_login, recovery_logout)
        self.assertLess(recovery_logout, config_update)
        self.assertLess(config_update, target_update)
        self.assert_logged_out()

    def test_legacy_single_target_creates_and_verifies_recovery_before_sso(self):
        self.api.legacy_target_topology(PRIVATE)
        self.private_input.read_password.return_value = PRIVATE
        self.assertEqual(self.console_migration()[0], 0)
        recovery = {
            "email": helper.RECOVERY_USER, "name": "Rodman", "password": PASSWORD,
            "sso_enabled": False, "global_role": "admin", "admin_forced_password_reset": False,
        }
        self.assertIn(("POST", "/api/v1/fleet/users/admin", recovery, TOKEN), self.api.calls)
        self.assertTrue(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        self.assertFalse(self.api.user(helper.RECOVERY_USER)["sso_enabled"])
        self.assertEqual(self.api.credentials, {helper.RECOVERY_USER: PASSWORD})
        routes = [(method, path) for method, path, _, _ in self.api.calls]
        recovery_create = routes.index(("POST", "/api/v1/fleet/users/admin"))
        recovery_login = next(index for index, call in enumerate(self.api.calls)
                              if call[:2] == ("POST", "/api/v1/fleet/login")
                              and call[2]["email"] == helper.RECOVERY_USER)
        recovery_logout = next(index for index, call in enumerate(self.api.calls)
                               if call == ("POST", "/api/v1/fleet/logout", None, RECOVERY_TOKEN))
        config_update = routes.index(("PATCH", "/api/v1/fleet/config"))
        target_update = routes.index(("PATCH", "/api/v1/fleet/users/1"))
        self.assertLess(recovery_create, recovery_login)
        self.assertLess(recovery_login, recovery_logout)
        self.assertLess(recovery_logout, config_update)
        self.assertLess(config_update, target_update)
        self.assert_logged_out()

    def test_final_console_sso_verification_is_idempotent_without_password_file(self):
        self.api.console_topology(final=True)
        self.api.config["sso_settings"] = self.sso_settings()
        status, _, loader = self.run_command(["console-sso", "--execute"])
        self.assertEqual(status, 0)
        self.assertFalse(any(method == "PATCH" for method, _, _, _ in self.api.calls))
        self.assertNotIn("fleet-airvpn-setup.py", [call.args[1] for call in loader.call_args_list])
        self.assert_logged_out()

    def test_clean_recovery_bootstrap_configures_sso_before_creating_target_administrator(self):
        self.api.clean_console_topology()
        status, _, loader = self.run_command(["console-sso", "--execute"])
        self.assertEqual(status, 0)
        self.assertEqual(self.api.config["sso_settings"], self.sso_settings())
        self.assertTrue(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        self.assertFalse(self.api.user(helper.RECOVERY_USER)["sso_enabled"])
        self.assertNotIn("fleet-airvpn-setup.py", [call.args[1] for call in loader.call_args_list])
        routes = [(method, path) for method, path, _, _ in self.api.calls]
        config_update = routes.index(("PATCH", "/api/v1/fleet/config"))
        target_create = routes.index(("POST", "/api/v1/fleet/users/admin"))
        self.assertEqual(routes[config_update + 1], ("GET", "/api/v1/fleet/config"))
        self.assertLess(config_update, target_create)
        self.assert_logged_out()

    def test_clean_console_setup_refuses_unexpected_user_topology(self):
        self.api.clean_console_topology()
        self.api.users.append({"id": 2, "email": "other@example.test", "sso_enabled": False, "global_role": "admin"})
        self.assertEqual(self.run_command(["console-sso", "--execute"])[0], 1)
        self.assert_no_setup_mutations()
        self.assert_logged_out()

    def test_legacy_single_target_does_not_touch_sso_or_target_until_recovery_login_is_verified(self):
        self.api.legacy_target_topology()
        self.api.login_failures.add(helper.RECOVERY_USER)
        self.assertEqual(self.console_migration()[0], 1)
        self.assertFalse(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        self.assertFalse(self.api.user(helper.RECOVERY_USER)["sso_enabled"])
        routes = [(method, path) for method, path, _, _ in self.api.calls]
        self.assertNotIn(("PATCH", "/api/v1/fleet/config"), routes)
        self.assertNotIn(("PATCH", "/api/v1/fleet/users/1"), routes)
        self.assert_logged_out()

    def test_console_migration_configures_matching_entra_sso_only_after_recovery_verification(self):
        self.api.console_topology()
        self.api.config["sso_settings"] = self.sso_settings()
        self.assertEqual(self.console_migration()[0], 0)
        self.assertNotIn(("PATCH", "/api/v1/fleet/config"),
                         [(method, path) for method, path, _, _ in self.api.calls])
        self.api.calls.clear()
        self.assertEqual(self.run_command(["console-sso", "--execute"])[0], 0)
        self.assertFalse(any(method == "PATCH" for method, _, _, _ in self.api.calls))
        self.assert_logged_out()

    def test_legacy_single_target_does_not_switch_target_when_recovery_creation_fails(self):
        self.api.legacy_target_topology()
        self.api.errors["POST", "/api/v1/fleet/users/admin"] = RuntimeError(PRIVATE)
        self.assertEqual(self.console_migration()[0], 1)
        self.assertIsNone(self.api.user(helper.RECOVERY_USER))
        self.assertFalse(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        routes = [(method, path) for method, path, _, _ in self.api.calls]
        self.assertNotIn(("PATCH", "/api/v1/fleet/config"), routes)
        self.assertNotIn(("PATCH", "/api/v1/fleet/users/1"), routes)
        self.assert_logged_out()

    def test_legacy_single_target_requires_recovery_readback_before_sso(self):
        self.api.legacy_target_topology()
        self.api.create_user_drop = True
        self.assertEqual(self.console_migration()[0], 1)
        self.assertIsNone(self.api.user(helper.RECOVERY_USER))
        self.assertFalse(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        routes = [(method, path) for method, path, _, _ in self.api.calls]
        self.assertNotIn(("PATCH", "/api/v1/fleet/config"), routes)
        self.assertNotIn(("PATCH", "/api/v1/fleet/users/1"), routes)
        self.assert_logged_out()

    def test_console_migration_failure_after_recovery_verification_keeps_local_recovery(self):
        self.api.console_topology()
        self.api.errors["PATCH", "/api/v1/fleet/users/1"] = RuntimeError(PRIVATE)
        self.assertEqual(self.console_migration()[0], 1)
        self.assertFalse(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        self.assertFalse(self.api.user(helper.RECOVERY_USER)["sso_enabled"])
        self.assertEqual(sum(method == "PATCH" and path == "/api/v1/fleet/users/1"
                             for method, path, _, _ in self.api.calls), 1)
        self.assert_logged_out()

    def test_console_migration_resumes_after_recovery_was_made_local(self):
        self.api.console_topology()
        self.api.errors["PATCH", "/api/v1/fleet/users/1"] = RuntimeError(PRIVATE)
        self.assertEqual(self.console_migration()[0], 1)
        self.api.errors.clear()
        self.api.calls.clear()
        self.assertEqual(self.console_migration()[0], 0)
        self.assertTrue(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        self.assertFalse(self.api.user(helper.RECOVERY_USER)["sso_enabled"])
        self.assertNotIn(("PATCH", "/api/v1/fleet/users/2"),
                         [(method, path) for method, path, _, _ in self.api.calls])
        self.assert_logged_out()

    def test_final_verifier_recovers_from_an_ambiguous_target_sso_update(self):
        self.api.console_topology()
        self.api.commit_then_errors["PATCH", "/api/v1/fleet/users/1"] = RuntimeError(PRIVATE)
        self.assertEqual(self.console_migration()[0], 1)
        self.assertTrue(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        self.assertFalse(self.api.user(helper.RECOVERY_USER)["sso_enabled"])
        self.api.calls.clear()
        self.assertEqual(self.run_command(["console-sso", "--execute"])[0], 0)
        self.assertFalse(any(method == "PATCH" for method, _, _, _ in self.api.calls))
        self.assert_logged_out()

    def test_console_migration_does_not_switch_target_when_sso_config_readback_fails(self):
        self.api.console_topology()
        self.api.config_refuse_sso_update = True
        self.assertEqual(self.console_migration()[0], 1)
        self.assertFalse(self.api.user(helper.CONSOLE_USER)["sso_enabled"])
        self.assertFalse(self.api.user(helper.RECOVERY_USER)["sso_enabled"])
        self.assertNotIn(("PATCH", "/api/v1/fleet/users/1"),
                         [(method, path) for method, path, _, _ in self.api.calls])
        self.assert_logged_out()

    def test_final_console_sso_drift_is_not_repaired_without_migration_input(self):
        self.api.console_topology(final=True)
        self.assertEqual(self.run_command(["console-sso", "--execute"])[0], 1)
        self.assert_no_setup_mutations()
        self.assert_logged_out()

    def test_steady_state_fleet_operators_use_the_local_recovery_administrator(self):
        self.assertEqual(csr.ADMIN_EMAIL, helper.RECOVERY_USER)
        self.assertEqual(bootstrap.ADMIN_EMAIL, helper.RECOVERY_USER)

    def test_incomplete_user_and_policy_pages_block_mutations(self):
        self.api.users *= 100
        self.assertEqual(self.run_command(["console-sso", "--execute"])[0], 1)
        self.assert_no_setup_mutations()
        self.assert_logged_out()
        self.api.policies = [{"name": "existing"}] * 100
        self.assertEqual(self.run_command(["reporting", "--execute"])[0], 1)
        self.assert_no_setup_mutations()
        self.assert_logged_out()

    def test_conflicting_reporting_policy_is_not_overwritten(self):
        original = dict(helper.POLICY, query="SELECT 1;")
        self.api.policies = [original]
        self.assertEqual(self.run_command(["reporting", "--execute"])[0], 1)
        self.assertEqual(self.api.policies, [original])
        self.assert_no_setup_mutations()
        self.assert_logged_out()

    def test_reporting_uses_free_global_routes_without_remediation(self):
        self.assertEqual(self.run_command(["reporting", "--execute"])[0], 0)
        self.assertEqual(self.api.policies, [helper.POLICY])
        self.assertEqual(self.mdm.calls, [])
        self.api.calls.clear()
        self.assertEqual(self.run_command(["reporting", "--execute"])[0], 0)
        self.assertNotIn(("POST", "/api/v1/fleet/global/policies"),
                         [(method, path) for method, path, _, _ in self.api.calls])
        self.assert_logged_out()

    def test_config_and_logout_errors_are_redacted(self):
        self.api.errors["GET", "/api/v1/fleet/config"] = RuntimeError(PRIVATE + PASSWORD)
        self.api.errors["POST", "/api/v1/fleet/logout"] = RuntimeError(TOKEN)
        self.assertEqual(self.run_command(["mac-pilot", "--execute"])[0], 1)
        self.assert_no_setup_mutations()
        self.assert_logged_out()

    def test_logout_failure_returns_failure_after_successful_device_work(self):
        self.api.errors["POST", "/api/v1/fleet/logout"] = RuntimeError(TOKEN)
        self.assertEqual(self.run_command(["mac-pilot", "--execute"])[0], 1)
        self.assert_logged_out()

    def test_metadata_url_must_match_managed_tenant_and_application(self):
        outputs = {"tenant_id": {"value": TENANT}, "client_id": {"value": APP},
                   "metadata_url": {"value": "https://unrelated.example.test/"}}
        result = subprocess.CompletedProcess([], 0, json.dumps(outputs).encode(), b"")
        with patch.object(helper.subprocess, "run", return_value=result), self.assertRaises(helper.SetupError):
            helper.saml_outputs()


class SamlMetadataTest(unittest.TestCase):
    def outputs(self):
        return {"tenant_id": {"value": TENANT}, "client_id": {"value": APP},
                "metadata_url": {"value": METADATA},
                "signing_certificate_thumbprint": {"value": THUMBPRINT.lower()},
                "signing_certificate_expires_at": {"value": "2099-01-01T00:00:00Z"}}

    def read_outputs(self, values):
        result = subprocess.CompletedProcess([], 0, json.dumps(values).encode(), b"")
        with patch.object(helper.subprocess, "run", return_value=result):
            return helper.saml_outputs()

    def validate(self, certificate=None, tenant=TENANT, use="signing"):
        certificate = certificate if certificate is not None else base64.b64encode(CERTIFICATE_BYTES).decode()
        raw = (f'<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" '
               f'xmlns:ds="http://www.w3.org/2000/09/xmldsig#" entityID="https://sts.windows.net/{tenant}/">'
               f'<IDPSSODescriptor><KeyDescriptor use="{use}"><ds:KeyInfo><ds:X509Data>'
               f'<ds:X509Certificate>{certificate}</ds:X509Certificate>'
               '</ds:X509Data></ds:KeyInfo></KeyDescriptor></IDPSSODescriptor></EntityDescriptor>').encode()
        response = MagicMock(status=200)
        response.read.return_value = raw
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch.object(helper.urllib.request, "build_opener", return_value=opener):
            return helper.validate_metadata(Mock(), METADATA, TENANT, THUMBPRINT)

    def test_managed_output_requires_future_certificate_and_normalizes_thumbprint(self):
        self.assertEqual(self.read_outputs(self.outputs()), (METADATA, TENANT, THUMBPRINT))

    def test_expired_naive_and_malformed_certificate_expiry_are_rejected(self):
        for value in ("2000-01-01T00:00:00Z", "2099-01-01T00:00:00", PRIVATE, None):
            with self.subTest(value_type=type(value).__name__):
                values = self.outputs()
                values["signing_certificate_expires_at"]["value"] = value
                with self.assertRaises(helper.SetupError) as error:
                    self.read_outputs(values)
                self.assertNotIn(PRIVATE, str(error.exception))

    def test_malformed_managed_thumbprint_is_rejected(self):
        for value in (None, "", "G" * 40, "A" * 39, PRIVATE):
            with self.subTest(value_type=type(value).__name__):
                values = self.outputs()
                values["signing_certificate_thumbprint"]["value"] = value
                with self.assertRaises(helper.SetupError) as error:
                    self.read_outputs(values)
                self.assertNotIn(PRIVATE, str(error.exception))

    def test_metadata_signing_certificate_must_match_managed_fingerprint(self):
        self.assertIsNone(self.validate())
        for certificate in (base64.b64encode(b"another certificate").decode(), "!invalid-base64!", ""):
            with self.subTest(empty=not certificate), self.assertRaises(helper.SetupError):
                self.validate(certificate=certificate)

    def test_matching_certificate_cannot_authorize_another_tenant_or_encryption_key(self):
        for kwargs in ({"tenant": APP}, {"use": "encryption"}):
            with self.subTest(case=next(iter(kwargs))), self.assertRaises(helper.SetupError):
                self.validate(**kwargs)


class AppleIdentityTest(unittest.TestCase):
    def run_command(self, target, reply_id, envelope_id=None):
        output = io.StringIO()
        api = Mock()
        queued = {}

        def request(method, path, body=None, token=None):
            if method == "POST":
                self.assertEqual(path, "/api/v1/fleet/commands/run")
                self.assertEqual(body["host_uuids"], [target])
                command = plistlib.loads(base64.b64decode(body["command"]))
                queued["command_uuid"] = command["CommandUUID"]
                queued["request_type"] = command["Command"]["RequestType"]
                return dict(queued, failed_uuids=[])
            reply = {"CommandUUID": queued["command_uuid"], "Status": "Acknowledged"}
            if reply_id is not None:
                reply["UDID"] = reply_id
            return {"results": [dict(queued, host_uuid=envelope_id or target, status="Acknowledged",
                                     result=base64.b64encode(plistlib.dumps(reply)).decode())]}

        api.request.side_effect = request
        with patch.object(mdm_helper.signal, "signal"), patch.object(mdm_helper.signal, "setitimer"), \
                patch.object(mdm_helper.time, "sleep", side_effect=AssertionError("Unexpected polling")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                reply = mdm_helper.command(api, TOKEN, target, {"RequestType": "DeviceInformation"})
                error = None
            except mdm_helper.VerificationError as failure:
                reply, error = None, failure
        for private in (target, reply_id, envelope_id, TOKEN):
            if private is not None:
                self.assertNotIn(private, output.getvalue())
                if error:
                    self.assertNotIn(private, str(error))
        return reply, error, api

    def test_acknowledgement_accepts_only_case_normalized_supported_device_forms(self):
        for value in ("01234567-89AB-4CDE-8F01-23456789ABCD", IOS_UUID, "A1B2C3D4" * 5):
            with self.subTest(length=len(value)):
                reply, error, api = self.run_command(value, value.lower(), value.lower())
                self.assertIsNone(error)
                self.assertEqual(reply["Status"], "Acknowledged")
                self.assertEqual(api.request.call_count, 2)

    def test_device_mismatch_in_result_envelope_or_apple_reply_fails_closed(self):
        cases = [(IOS_UUID, "00008110-0123456789ABCDE0", IOS_UUID),
                 (LOCAL_UUID, "11111111-1111-4111-8111-111111111112", LOCAL_UUID),
                 (IOS_UUID, IOS_UUID, "00008110-0123456789ABCDE0"),
                 (LOCAL_UUID, LOCAL_UUID, "11111111-1111-4111-8111-111111111112"),
                 (IOS_UUID, None, IOS_UUID)]
        for target, reply_id, envelope in cases:
            with self.subTest(target_length=len(target), missing_reply=reply_id is None):
                reply, error, api = self.run_command(target, reply_id, envelope)
                self.assertIsNone(reply)
                self.assertIsInstance(error, mdm_helper.VerificationError)
                self.assertEqual(api.request.call_count, 2)

    def test_invalid_device_identifier_is_rejected_before_submission(self):
        invalid = (None, True, "", "A" * 41, "A" * 32, "G" * 40,
                   IOS_UUID + "\n", " " + IOS_UUID, "{" + LOCAL_UUID + "}", "urn:uuid:" + LOCAL_UUID)
        for value in invalid:
            with self.subTest(value_type=type(value).__name__, size=len(value) if isinstance(value, str) else None):
                api = Mock()
                with self.assertRaises(mdm_helper.VerificationError):
                    mdm_helper.command(api, TOKEN, value, {"RequestType": "ProfileList"})
                api.request.assert_not_called()

    def test_local_mac_requires_both_serial_and_uuid_with_single_match(self):
        serial = "PRIVATE_LOCAL_HARDWARE_SERIAL"
        hardware = {"SPHardwareDataType": [{"serial_number": serial, "platform_UUID": LOCAL_UUID}]}
        local = {"platform": "darwin", "hardware_serial": serial, "uuid": LOCAL_UUID}
        candidates = [[dict(local, uuid="11111111-1111-4111-8111-111111111112")],
                      [dict(local, hardware_serial="OTHER_SERIAL")],
                      [dict(local, platform="ios")], [local, local]]
        result = subprocess.CompletedProcess([], 0, json.dumps(hardware).encode(), b"")
        for hosts in candidates:
            with self.subTest(count=len(hosts)):
                api = Mock()
                api.request.return_value = {"hosts": hosts}
                output = io.StringIO()
                with patch.object(mdm_helper.sys, "platform", "darwin"), \
                        patch.object(mdm_helper.subprocess, "run", return_value=result), \
                        contextlib.redirect_stdout(output), \
                        self.assertRaises(mdm_helper.VerificationError) as error:
                    mdm_helper.local_host(api, TOKEN)
                for value in (serial, LOCAL_UUID):
                    self.assertNotIn(value, output.getvalue())
                    self.assertNotIn(value, str(error.exception))


class CredentialExportTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.destination = self.base / "private-password.txt"
        self.password = PASSWORD.ljust(40, "x")
        self.values = {"user_principal_name": {"value": "rodman.mac@stinkyboi.com"},
                       "initial_password": {"value": self.password}}

    def run_export(self, error=None, pilot=None):
        output = io.StringIO()
        result = subprocess.CompletedProcess([], 0, json.dumps(self.values).encode(), b"")
        argv = ["credentials", "--output", str(self.destination)]
        if pilot:
            argv[1:1] = ["--pilot", pilot]
        with patch.object(credentials, "ROOT", self.repo), \
                patch.object(credentials.sys, "argv", argv), \
                patch.object(credentials.subprocess, "run", return_value=result, side_effect=error) as process, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                status = credentials.main()
            except SystemExit as failure:
                status = failure.code
        for secret in (self.password, PASSWORD, PRIVATE):
            self.assertNotIn(secret, output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        return status, process

    def test_success_writes_secret_only_to_owner_private_file(self):
        status, process = self.run_export()
        self.assertEqual(status, 0)
        content = self.destination.read_text()
        self.assertIn(self.password, content)
        self.assertIn("Microsoft Authenticator", content)
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o600)
        process.assert_called_once()
        self.assertIn("IaC/live/azuread-applications/fleet-pilot-user", str(process.call_args))

    def test_stuhlmuller_pilot_requires_explicit_selection(self):
        self.values["user_principal_name"]["value"] = "rodman.mac@stuhlmuller.net"
        status, process = self.run_export(pilot="stuhlmuller")
        self.assertEqual(status, 0)
        self.assertIn("IaC/operator/entra-stuhlmuller-pilot-user", str(process.call_args))

    def test_existing_file_is_preserved_without_reading_credentials(self):
        self.destination.write_text("existing content")
        status, process = self.run_export()
        self.assertEqual(status, 1)
        self.assertEqual(self.destination.read_text(), "existing content")
        process.assert_not_called()

    def test_existing_and_dangling_symlinks_are_preserved_without_touching_targets(self):
        target = self.base / "target"
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    target.write_text("target content")
                self.destination.symlink_to(target)
                status, process = self.run_export()
                self.assertEqual(status, 1)
                self.assertTrue(self.destination.is_symlink())
                self.assertEqual(target.exists(), existing)
                if existing:
                    self.assertEqual(target.read_text(), "target content")
                process.assert_not_called()
                self.destination.unlink()

    def test_repository_and_symlinked_repository_destinations_are_rejected(self):
        alias = self.base / "repo-alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        other = self.base / "other-repo"
        other.mkdir()
        (other / ".git").write_text("gitdir: elsewhere")
        for parent in (self.repo, alias, other):
            with self.subTest(parent=parent.name):
                self.destination = parent / "must-not-exist.txt"
                status, process = self.run_export()
                self.assertEqual(status, 2)
                self.assertFalse(self.destination.exists())
                process.assert_not_called()

    def test_private_process_failure_removes_partial_file_and_redacts_exception(self):
        failure = subprocess.CalledProcessError(1, ["terragrunt"], output=self.password, stderr=PRIVATE)
        self.assertEqual(self.run_export(error=failure)[0], 1)
        self.assertFalse(self.destination.exists())

    def test_unexpected_identity_or_invalid_password_is_not_exported(self):
        for field, value in (("user_principal_name", "different@example.test"),
                             ("initial_password", "short"), ("initial_password", self.password + "\n")):
            with self.subTest(field=field):
                original = copy.deepcopy(self.values)
                self.values[field]["value"] = value
                self.assertEqual(self.run_export()[0], 1)
                self.assertFalse(self.destination.exists())
                self.values = original


if __name__ == "__main__":
    unittest.main()
