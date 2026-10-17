#!/usr/bin/env python3
"""Apply reviewed Fleet Free profiles and Entra console SSO; dry run by default."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import base64
import hashlib
import importlib.util
import json
import plistlib
import re
import subprocess
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "clusters/homelab/apps/fleet/profiles"
CONSOLE_USER = "rodman@stuhlmuller.net"
RECOVERY_USER = "rodman@stinkyboi.com"
MAC_FILES = ("macos-security-baseline-host.mobileconfig", "macos-entra-platform-sso.mobileconfig")
MAC_BASELINE_FILES = (MAC_FILES[0],)
MAC_PSSO_FILES = (MAC_FILES[1],)
IOS_FILES = ("ios-passcode-baseline.mobileconfig",)
LEGACY_MAC_FILES = ("macos-security-baseline.mobileconfig",)  # Global assignment retired; removal only.
POLICY = {
    "name": "Family Mac FileVault enabled",
    "query": "SELECT 1 FROM disk_encryption WHERE user_uuid IS NOT '' AND filevault_status = 'on' LIMIT 1;",
    "platform": "darwin",
    "description": "Reports FileVault encryption. Does not enable encryption, escrow keys, or attest Entra compliance.",
    "resolution": "Review FileVault locally and preserve recovery access before changing encryption settings.",
    "critical": False,
}


class SetupError(Exception):
    """Only fixed, non-sensitive diagnostics may be printed."""


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def profiles(filenames, device_type):
    result = []
    for filename in filenames:
        raw = (PROFILES / filename).read_bytes()
        profile = plistlib.loads(raw)
        if (profile.get("PayloadType") != "Configuration"
                or profile.get("PayloadScope") != "System"
                or type(profile.get("TargetDeviceType")) is not int
                or profile.get("TargetDeviceType") != device_type
                or profile.get("PayloadRemovalDisallowed") is not False
                or not profile.get("PayloadIdentifier", "").startswith("com.stinkyboi.fleet.")):
            raise SetupError("Profile scope or platform guard failed")
        uuid.UUID(profile["PayloadUUID"])
        result.append((raw, profile))
    return result


def apply_profiles(api, mdm, token, host_uuid, desired, remove=False):
    before = mdm.profile_identifiers(mdm.command(api, token, host_uuid, {"RequestType": "ProfileList"}))
    identifiers = {profile["PayloadIdentifier"] for _, profile in desired}
    for raw, profile in desired:
        identifier = profile["PayloadIdentifier"]
        if remove:
            if identifier in before:
                mdm.command(api, token, host_uuid, {"RequestType": "RemoveProfile", "Identifier": identifier})
        else:
            # Stable identifiers replace only these repository-owned profiles.
            # Do not retry writes after timeout: first inspect pending commands.
            mdm.command(api, token, host_uuid, {"RequestType": "InstallProfile", "Payload": raw})
    reply = mdm.command(api, token, host_uuid, {"RequestType": "ProfileList"})
    after = mdm.profile_identifiers(reply)
    if not before - identifiers <= after:
        raise SetupError("Pre-existing profile retention was not verified")
    if remove:
        if identifiers & after:
            raise SetupError("Profile removal was not verified")
    else:
        for _, expected in desired:
            matches = [item for item in reply["ProfileList"]
                       if item.get("PayloadIdentifier") == expected["PayloadIdentifier"]]
            if len(matches) != 1 or matches[0].get("PayloadUUID", "").lower() != expected["PayloadUUID"].lower():
                raise SetupError("Installed profile identity was not verified")
    print("Profile acknowledgement, inventory, and unrelated-profile preservation: passed", flush=True)


def ios_host(api, mdm, token, host_id):
    host = api.request("GET", f"/api/v1/fleet/hosts/{host_id}", token=token)["host"]
    if (host.get("id") != host_id or host.get("platform") not in ("ios", "ipados")
            or host.get("mdm", {}).get("connected_to_fleet") is not True):
        raise SetupError("Selected host is not a Fleet-enrolled iPhone or iPad")
    mdm.device_identifier(host["uuid"])
    return host["uuid"]


def mac_host(api, mdm, token, host_id):
    host = api.request("GET", f"/api/v1/fleet/hosts/{host_id}", token=token)["host"]
    if (host.get("id") != host_id or host.get("platform") != "darwin"
            or host.get("mdm", {}).get("connected_to_fleet") is not True):
        raise SetupError("Selected host is not a Fleet-enrolled Mac")
    mdm.device_identifier(host["uuid"])
    return host["uuid"]


def saml_outputs():
    result = subprocess.run([
        "terragrunt", "--log-disable", "--working-dir",
        str(ROOT / "IaC/live/azuread-applications/fleet"), "output", "-json",
    ], capture_output=True, check=True, timeout=120)
    outputs = json.loads(result.stdout)
    tenant = str(uuid.UUID(outputs["tenant_id"]["value"]))
    app = str(uuid.UUID(outputs["client_id"]["value"]))
    expected = f"https://login.microsoftonline.com/{tenant}/federationmetadata/2007-06/federationmetadata.xml?appid={app}"
    if outputs["metadata_url"]["value"] != expected:
        raise SetupError("SAML metadata URL does not match the managed Entra application")
    thumbprint = outputs["signing_certificate_thumbprint"]["value"]
    if not isinstance(thumbprint, str) or not re.fullmatch(r"[0-9A-Fa-f]{40}", thumbprint):
        raise SetupError("Managed SAML signing certificate thumbprint is invalid")
    try:
        expiry = datetime.fromisoformat(outputs["signing_certificate_expires_at"]["value"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise SetupError("Managed SAML signing certificate expiry is invalid") from error
    if expiry.utcoffset() is None or expiry <= datetime.now(timezone.utc):
        raise SetupError("Managed SAML signing certificate is expired or has an invalid expiry")
    return expected, tenant, thumbprint.upper()


def validate_metadata(api, url, tenant, thumbprint):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), api.NoRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": "Fleet-Free-Setup/1.0"})
    with opener.open(req, timeout=30) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 2 * 1024 * 1024 or b"<!" in raw:
            raise SetupError("Entra metadata response is invalid")
    root = ET.fromstring(raw)
    ns = {"md": "urn:oasis:names:tc:SAML:2.0:metadata", "ds": "http://www.w3.org/2000/09/xmldsig#"}
    if root.attrib.get("entityID") != f"https://sts.windows.net/{tenant}/":
        raise SetupError("Entra metadata tenant or SAML signing key did not match")
    certificates = root.findall("md:IDPSSODescriptor/md:KeyDescriptor[@use='signing']//ds:X509Certificate", ns)
    for certificate in certificates:
        try:
            der = base64.b64decode("".join((certificate.text or "").split()), validate=True)
        except ValueError as error:
            raise SetupError("Entra metadata signing certificate is invalid") from error
        # SHA-1 is Microsoft's certificate identifier, not a trust algorithm here.
        if hashlib.sha1(der, usedforsecurity=False).hexdigest().upper() == thumbprint:
            return
    raise SetupError("Entra metadata tenant or SAML signing key did not match")


def console_users(api, token):
    users = api.request("GET", "/api/v1/fleet/users?per_page=100", token=token)["users"]
    if not isinstance(users, list) or len(users) >= 100 or not all(isinstance(user, dict) for user in users):
        raise SetupError("Fleet user listing is incomplete")
    return users


def console_account(users, email, sso_enabled):
    matches = [user for user in users if user.get("email") == email]
    if len(matches) != 1:
        raise SetupError("Fleet console account topology differs from the reviewed migration")
    user = matches[0]
    if (type(user.get("id")) is not int or user["id"] < 1
            or user.get("global_role") != "admin" or user.get("sso_enabled") is not sso_enabled):
        raise SetupError("Fleet console account topology differs from the reviewed migration")
    return user


def console_accounts(users, target_sso, recovery_sso):
    if len(users) != 2:
        raise SetupError("Fleet console account topology differs from the reviewed migration")
    target = console_account(users, CONSOLE_USER, target_sso)
    recovery = console_account(users, RECOVERY_USER, recovery_sso)
    if target["id"] == recovery["id"]:
        raise SetupError("Fleet console account topology differs from the reviewed migration")
    return target, recovery


def console_session(api, token, email):
    response = api.request("GET", "/api/v1/fleet/me", token=token)
    account = response.get("user") if isinstance(response, dict) else None
    if not isinstance(account, dict) or account.get("email") != email or account.get("global_role") != "admin":
        raise SetupError("Fleet operator session does not match the reviewed administrator")


def configure_console_sso(api, token, current, desired):
    if any(current.get(key) != value for key, value in desired.items()):
        api.request("PATCH", "/api/v1/fleet/config", {"sso_settings": desired}, token)
    config = api.request("GET", "/api/v1/fleet/config", token=token)
    actual = config.get("sso_settings", {}) if isinstance(config, dict) else None
    if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in desired.items()):
        raise SetupError("Fleet console SSO configuration readback failed")


def console_sso(api, token, current_password=None, recovery_password=None):
    migrating = current_password is not None
    if migrating != (recovery_password is not None):
        raise SetupError("Fleet console migration password handling is incomplete")
    url, tenant, thumbprint = saml_outputs()
    validate_metadata(api, url, tenant, thumbprint)
    desired = {
        "enable_sso": True, "idp_name": "Microsoft Entra ID", "entity_id": api.FLEET_URL,
        "issuer_uri": "", "metadata_url": url, "metadata": "",
        "enable_jit_provisioning": False, "enable_sso_idp_login": False,
    }
    config = api.request("GET", "/api/v1/fleet/config", token=token)
    current = config.get("sso_settings", {}) if isinstance(config, dict) else None
    if not isinstance(current, dict):
        raise SetupError("Fleet console SSO settings are invalid")
    if current.get("enable_sso") and current.get("metadata_url") != url:
        raise SetupError("A different SSO provider is enabled; refusing replacement")
    users = console_users(api, token)
    if not migrating:
        console_session(api, token, RECOVERY_USER)
        if not any(user.get("email") == CONSOLE_USER for user in users):
            if len(users) != 1:
                raise SetupError("Fleet console account topology differs from the reviewed migration")
            console_account(users, RECOVERY_USER, sso_enabled=False)
            configure_console_sso(api, token, current, desired)
            api.request("POST", "/api/v1/fleet/users/admin", {
                "email": CONSOLE_USER, "name": "Rodman", "sso_enabled": True,
                "global_role": "admin", "admin_forced_password_reset": False,
            }, token)
            console_accounts(console_users(api, token), target_sso=True, recovery_sso=False)
            print("Console SAML settings and staged administrator migration: verified; interactive login still untested")
            return
        console_accounts(users, target_sso=True, recovery_sso=False)
        if any(current.get(key) != value for key, value in desired.items()):
            raise SetupError("Fleet console SSO configuration is not in the reviewed final state")
        print("Console SAML settings and staged administrator migration: verified; interactive login still untested")
        return

    console_session(api, token, CONSOLE_USER)
    if len(users) == 1:
        target = console_account(users, CONSOLE_USER, sso_enabled=False)
        api.request("POST", "/api/v1/fleet/users/admin", {
            "email": RECOVERY_USER, "name": "Rodman", "password": recovery_password,
            "sso_enabled": False, "global_role": "admin", "admin_forced_password_reset": False,
        }, token)
        target_after, recovery = console_accounts(console_users(api, token), target_sso=False,
                                                   recovery_sso=False)
        if target_after["id"] != target["id"]:
            raise SetupError("Fleet console account identity changed during migration")
        target = target_after
    else:
        try:
            target, recovery = console_accounts(users, target_sso=False, recovery_sso=True)
        except SetupError:
            target, recovery = console_accounts(users, target_sso=False, recovery_sso=False)
        else:
            api.request("PATCH", f"/api/v1/fleet/users/{recovery['id']}", {
                "sso_enabled": False, "new_password": recovery_password,
            }, token)
            users = console_users(api, token)
            target_after, recovery_after = console_accounts(users, target_sso=False, recovery_sso=False)
            if target_after["id"] != target["id"] or recovery_after["id"] != recovery["id"]:
                raise SetupError("Fleet console account identity changed during migration")
    recovery_token = api.request("POST", "/api/v1/fleet/login", {
        "email": RECOVERY_USER, "password": recovery_password,
    }).get("token")
    if not isinstance(recovery_token, str) or not recovery_token:
        raise SetupError("Fleet recovery login did not return a session")
    try:
        console_session(api, recovery_token, RECOVERY_USER)
    finally:
        api.request("POST", "/api/v1/fleet/logout", token=recovery_token)
    configure_console_sso(api, token, current, desired)
    api.request("PATCH", f"/api/v1/fleet/users/{target['id']}", {"sso_enabled": True}, token)
    users = console_users(api, token)
    target_after, recovery_after = console_accounts(users, target_sso=True, recovery_sso=False)
    if target_after["id"] != target["id"] or recovery_after["id"] != recovery["id"]:
        raise SetupError("Fleet console account identity changed during migration")
    print("Console SAML settings and staged administrator migration: verified; interactive login still untested")


def reporting(api, token):
    existing = api.request("GET", "/api/v1/fleet/global/policies?per_page=100", token=token)["policies"]
    if len(existing) >= 100:
        raise SetupError("Policy listing is incomplete")
    matches = [item for item in existing if item["name"] == POLICY["name"]]
    if len(matches) > 1:
        raise SetupError("Ambiguous repository-owned policy")
    if matches:
        if any(matches[0].get(key) != value for key, value in POLICY.items()):
            raise SetupError("Existing policy differs; review before changing it")
    else:
        api.request("POST", "/api/v1/fleet/global/policies", POLICY, token)
    print("Free FileVault reporting policy configured; host evaluation is a separate check")


def mac_baseline_catalog(api, token, remove=False):
    if not remove:
        raise SetupError("Global Mac baseline assignment is retired; mac-baseline-catalog requires --remove")
    raw, profile = profiles(LEGACY_MAC_FILES, 5)[0]

    def catalog():
        result = api.request("GET", "/api/v1/fleet/configuration_profiles?per_page=100", token=token)
        if result.get("meta", {}).get("has_next_results") is not False:
            raise SetupError("Configuration profile catalog listing is incomplete")
        return result["profiles"]

    # Fleet stores UNHEX(MD5(profile bytes)) and JSON encodes those bytes as base64.
    # This is its content-equality checksum, not an authentication primitive.
    expected = {"identifier": profile["PayloadIdentifier"], "name": profile["PayloadDisplayName"],
                "platform": "darwin",
                "checksum": base64.b64encode(hashlib.md5(raw, usedforsecurity=False).digest()).decode()}
    before = catalog()
    matches = [item for item in before if item.get("identifier") == expected["identifier"]
               or item.get("name") == expected["name"]]
    if matches and (len(matches) != 1 or any(matches[0].get(key) != value for key, value in expected.items())):
        raise SetupError("Mac baseline already exists in the catalog; inspect it before changing it")
    if not matches:
        print("Mac baseline is absent from the catalog; no catalog changes made")
        return
    profile_uuid = matches[0]["profile_uuid"]
    if not isinstance(profile_uuid, str) or not profile_uuid:
        raise SetupError("Mac baseline catalog UUID is invalid")
    api.request("DELETE", "/api/v1/fleet/configuration_profiles/" + urllib.parse.quote(profile_uuid, safe=""),
                token=token)
    after = catalog()
    if any(item.get("identifier") == expected["identifier"] or item.get("profile_uuid") == profile_uuid
           for item in after):
        raise SetupError("Mac baseline catalog removal was not verified")
    if not all(item in after for item in before if item not in matches):
        raise SetupError("Pre-existing catalog profile retention was not verified")
    print("Mac baseline catalog removal and unrelated-profile preservation: verified; device removal is separate")
    return


def execute(args):
    desired = (profiles(IOS_FILES, 1) if args.action == "ios-baseline"
               else profiles(MAC_BASELINE_FILES if args.action == "mac-baseline"
                             else MAC_PSSO_FILES if args.action == "mac-psso" else MAC_FILES, 5))
    api = module("fleet_api", "fleet-download-apple-csr.py")
    mdm = module("fleet_mdm", "fleet-verify-apple-mdm.py")
    api.MAX_RESPONSE = 16 * 1024 * 1024
    current_password = recovery_password = None
    if args.action == "console-sso" and args.current_password_file is not None:
        private_input = module("fleet_private_input", "fleet-airvpn-setup.py")
        current_password = private_input.read_password(args.current_password_file)
        # Keep the existing secret as the sole local-recovery password after SSO takes over the target account.
        recovery_password = api.initial_password()
        token = api.request("POST", "/api/v1/fleet/login", {
            "email": CONSOLE_USER, "password": current_password,
        }).get("token")
    else:
        token = api.password_login()
    if not isinstance(token, str) or not token:
        raise SetupError("Fleet login did not return a session")
    try:
        config = api.request("GET", "/api/v1/fleet/config", token=token)
        if config.get("license", {}).get("tier") != "free":
            raise SetupError("Expected Fleet Free; refusing an unverified license contract")
        if args.action == "console-sso":
            console_sso(api, token, current_password, recovery_password)
        elif args.action == "reporting":
            reporting(api, token)
        elif args.action == "mac-baseline-catalog":
            mac_baseline_catalog(api, token, remove=args.remove)
        elif args.action == "validate-profiles":
            api.request("POST", "/api/v1/fleet/configuration_profiles/batch?dry_run=true", {
                "configuration_profiles": [{"profile": base64.b64encode(raw).decode()}
                                           for raw, _ in desired + profiles(IOS_FILES, 1)],
            }, token, accepted_status=204)
            print("Fleet Free profile validation passed; no profiles assigned")
        else:
            host = (ios_host(api, mdm, token, args.host_id) if args.action == "ios-baseline"
                    else mac_host(api, mdm, token, args.host_id) if args.action in ("mac-baseline", "mac-psso")
                    else mdm.local_host(api, token))
            if args.action == "mac-pilot" and not args.remove:
                apply_profiles(api, mdm, token, host, profiles(MAC_PSSO_FILES, 5), remove=True)
                print("Existing Platform SSO profile absence and baseline/unrelated-profile retention: verified")
            apply_profiles(api, mdm, token, host, desired, remove=args.remove)
            if args.action == "ios-baseline" and not args.remove:
                info = mdm.command(api, token, host, {"RequestType": "SecurityInfo"}).get(
                    "SecurityInfo", {})
                if not isinstance(info, dict):
                    raise SetupError("Passcode security response is invalid")
                passcode = {key: info.get(key) for key in
                            ("PasscodePresent", "PasscodeCompliant", "PasscodeCompliantWithProfiles")}
                if any(value is not None and type(value) is not bool for value in passcode.values()):
                    raise SetupError("Passcode security response has an invalid value type")
                print(json.dumps(passcode))
    finally:
        api.request("POST", "/api/v1/fleet/logout", token=token)
        print("Fleet operator session revoked", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate-profiles", "mac-pilot", "mac-baseline", "mac-psso",
                                            "ios-baseline", "mac-baseline-catalog", "console-sso", "reporting"))
    parser.add_argument("--host-id", type=int,
                        help="Explicit enrolled Fleet ID; required for mac-baseline, mac-psso, or ios-baseline")
    parser.add_argument("--remove", action="store_true",
                        help="Remove only the selected repository profiles; does not restore old passwords")
    parser.add_argument("--current-password-file", type=Path,
                        help="Private current target-local Fleet password file for a legacy console SSO migration")
    parser.add_argument("--execute", action="store_true", help="Apply through the authenticated Fleet API")
    args = parser.parse_args(argv)
    if ((args.action in ("mac-baseline", "mac-psso", "ios-baseline")) != (args.host_id is not None)
            or (args.host_id is not None and args.host_id < 1)):
        parser.error("Only mac-baseline, mac-psso, and ios-baseline require --host-id with a positive Fleet host ID")
    if args.remove and args.action not in ("mac-pilot", "mac-baseline", "mac-psso", "ios-baseline", "mac-baseline-catalog"):
        parser.error("--remove applies only to device profiles")
    if args.current_password_file is not None and args.action != "console-sso":
        parser.error("--current-password-file applies only to console-sso")
    try:
        if args.action == "mac-baseline-catalog" and not args.remove:
            raise SetupError("Global Mac baseline assignment is retired; mac-baseline-catalog requires --remove")
        profiles(MAC_FILES, 5)
        profiles(IOS_FILES, 1)
        profiles(LEGACY_MAC_FILES, 5)
        if not args.execute:
            print("Dry run: profile files valid; no credentials or APIs accessed.\n"
                  "mac-pilot targets this exact Mac by serial AND hardware UUID.\n"
                  "Profile writes replace only stable repository identifiers, preserve other profiles, and never auto-retry.\n"
                  "mac-baseline targets only the selected Fleet-enrolled Mac; future Macs require an explicit install.\n"
                  "mac-psso targets only the selected Fleet-enrolled Mac and installs or removes only Platform SSO.\n"
                  "ios-baseline targets only the selected iPhone or iPad; install and removal never use a global catalog.\n"
                  "mac-baseline-catalog --remove retires the old global assignment after host-scoped Mac installs.\n"
                  "console-sso stages or verifies the SSO/recovery topology from local recovery; "
                  "--current-password-file is legacy-only.\n"
                  "reporting adds a macOS-only FileVault SQL policy without automatic remediation.")
            return 0
        execute(args)
    except Exception as error:  # noqa: BLE001 - redact library and transport failures at the operator boundary
        if type(error).__name__ in ("SetupError", "DownloadError", "VerificationError"):
            print(str(error), file=sys.stderr)
        print("Fleet Free setup failed or is incomplete; inspect status before retrying. Private details withheld.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Fleet Free setup interrupted; inspect pending commands before retrying.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
