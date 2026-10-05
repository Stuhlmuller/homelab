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
CONSOLE_USER = "rodman@stinkyboi.com"
MAC_FILES = ("macos-security-baseline.mobileconfig", "macos-entra-platform-sso.mobileconfig")
IOS_FILES = ("ios-passcode-baseline.mobileconfig",)  # Retired; retained only for removal.
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
    if host.get("id") != host_id or host.get("platform") not in ("ios", "ipados"):
        raise SetupError("Selected host is not an iPhone or iPad")
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


def console_sso(api, token):
    url, tenant, thumbprint = saml_outputs()
    validate_metadata(api, url, tenant, thumbprint)
    desired = {
        "enable_sso": True, "idp_name": "Microsoft Entra ID", "entity_id": api.FLEET_URL,
        "issuer_uri": "", "metadata_url": url, "metadata": "",
        "enable_jit_provisioning": False, "enable_sso_idp_login": False,
    }
    current = api.request("GET", "/api/v1/fleet/config", token=token).get("sso_settings", {})
    if current.get("enable_sso") and current.get("metadata_url") != url:
        raise SetupError("A different SSO provider is enabled; refusing replacement")
    users = api.request("GET", "/api/v1/fleet/users?per_page=100", token=token)["users"]
    if len(users) >= 100:
        raise SetupError("Fleet user listing is incomplete")
    matches = [user for user in users if user["email"] == CONSOLE_USER]
    if len(matches) > 1 or (matches and (not matches[0].get("sso_enabled")
                                        or matches[0].get("global_role") != "admin")):
        raise SetupError("Existing console user conflicts with the reviewed SSO administrator")
    api.request("PATCH", "/api/v1/fleet/config", {"sso_settings": desired}, token)
    if not matches:
        api.request("POST", "/api/v1/fleet/users/admin", {
            "email": CONSOLE_USER, "name": "Rodman", "sso_enabled": True,
            "global_role": "admin", "admin_forced_password_reset": False,
        }, token)
    actual = api.request("GET", "/api/v1/fleet/config", token=token)["sso_settings"]
    if any(actual.get(key) != value for key, value in desired.items()):
        raise SetupError("Fleet console SSO configuration readback failed")
    users = api.request("GET", "/api/v1/fleet/users?per_page=100", token=token)["users"]
    if not any(user["email"] == CONSOLE_USER and user.get("sso_enabled")
               and user.get("global_role") == "admin" for user in users):
        raise SetupError("Precreated SSO administrator readback failed")
    print("Console SAML settings and precreated administrator: verified; interactive login still untested")


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
    raw, profile = profiles((MAC_FILES[0],), 5)[0]

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
    if remove:
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
    if matches:
        print("Mac baseline already exists with matching identity and content; no catalog changes made")
        return
    api.request("POST", "/api/v1/fleet/configuration_profiles/batch?dry_run=true", {
        "configuration_profiles": [{"profile": base64.b64encode(raw).decode()}],
    }, token, accepted_status=204)
    boundary = "fleet-mac-baseline-profile"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="profile"; '
            f'filename="{MAC_FILES[0]}"\r\nContent-Type: application/x-apple-aspen-config\r\n\r\n').encode()
    body += raw + f"\r\n--{boundary}--\r\n".encode()
    # Add one profile only. Never batch-replace the catalog or retry a timed-out write.
    created = api.request("POST", "/api/v1/fleet/configuration_profiles", body, token,
                          content_type=f"multipart/form-data; boundary={boundary}")
    after = catalog()
    matches = [item for item in after if item.get("identifier") == expected["identifier"]]
    if (len(matches) != 1 or any(matches[0].get(key) != value for key, value in expected.items())
            or not created.get("profile_uuid") or matches[0].get("profile_uuid") != created["profile_uuid"]):
        raise SetupError("Mac baseline catalog identity was not verified")
    if not all(item in after for item in before):
        raise SetupError("Pre-existing catalog profile retention was not verified")
    print("Mac baseline catalog upload and unrelated-profile preservation: verified; device enforcement is separate")


def execute(args):
    desired = profiles(IOS_FILES if args.action == "ios-baseline" else MAC_FILES,
                       1 if args.action == "ios-baseline" else 5)
    api = module("fleet_api", "fleet-download-apple-csr.py")
    mdm = module("fleet_mdm", "fleet-verify-apple-mdm.py")
    api.MAX_RESPONSE = 16 * 1024 * 1024
    token = api.request("POST", "/api/v1/fleet/login", {
        "email": api.ADMIN_EMAIL, "password": api.initial_password(),
    }).get("token")
    if not isinstance(token, str) or not token:
        raise SetupError("Fleet login did not return a session")
    try:
        config = api.request("GET", "/api/v1/fleet/config", token=token)
        if config.get("license", {}).get("tier") != "free":
            raise SetupError("Expected Fleet Free; refusing an unverified license contract")
        if args.action == "console-sso":
            console_sso(api, token)
        elif args.action == "reporting":
            reporting(api, token)
        elif args.action == "mac-baseline-catalog":
            mac_baseline_catalog(api, token, remove=args.remove)
        elif args.action == "validate-profiles":
            api.request("POST", "/api/v1/fleet/configuration_profiles/batch?dry_run=true", {
                "configuration_profiles": [{"profile": base64.b64encode(raw).decode()}
                                           for raw, _ in desired],
            }, token, accepted_status=204)
            print("Fleet Free profile validation passed; no profiles assigned")
        else:
            host = ios_host(api, mdm, token, args.host_id) if args.action == "ios-baseline" else mdm.local_host(api, token)
            apply_profiles(api, mdm, token, host, desired, remove=args.remove)
    finally:
        api.request("POST", "/api/v1/fleet/logout", token=token)
        print("Fleet operator session revoked", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate-profiles", "mac-pilot", "mac-baseline-catalog", "ios-baseline", "console-sso", "reporting"))
    parser.add_argument("--host-id", type=int, help="Explicit enrolled iPhone/iPad Fleet ID; required for ios-baseline")
    parser.add_argument("--remove", action="store_true", help="Remove only the selected repository profiles; does not restore old passwords")
    parser.add_argument("--execute", action="store_true", help="Apply through the authenticated Fleet API")
    args = parser.parse_args(argv)
    if (args.action == "ios-baseline") != (args.host_id is not None) or (args.host_id is not None and args.host_id < 1):
        parser.error("Only ios-baseline requires --host-id with a positive Fleet host ID")
    if args.remove and args.action not in ("mac-pilot", "mac-baseline-catalog", "ios-baseline"):
        parser.error("--remove applies only to device profiles")
    try:
        if args.action == "ios-baseline" and not args.remove:
            raise SetupError("The iOS passcode baseline is retired; ios-baseline requires --remove")
        profiles(MAC_FILES, 5)
        profiles(IOS_FILES, 1)
        if not args.execute:
            print("Dry run: profile files valid; no credentials or APIs accessed.\n"
                  "mac-pilot targets this exact Mac by serial AND hardware UUID; ios-baseline removes the retired profile from the selected iPhone/iPad.\n"
                  "Profile writes replace only stable repository identifiers, preserve other profiles, and never auto-retry.\n"
                  "mac-baseline-catalog uploads only the Mac password baseline for Fleet-managed enforcement, or removes it with --remove.\n"
                  "console-sso uses the managed Entra unit outputs, precreates only the authorized SSO admin, and keeps recovery login.\n"
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
