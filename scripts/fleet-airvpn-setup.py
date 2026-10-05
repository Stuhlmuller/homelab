#!/usr/bin/env python3
"""Prepare a private, per-device WireGuard AirVPN profile; dry run by default."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import base64
import hashlib
import importlib.util
import ipaddress
import json
import os
import plistlib
import re
import stat
import uuid
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "clusters/homelab/apps/fleet/profiles/airvpn-catalog.json"
MAX_CONFIG = 64 * 1024
IDENTIFIER = "com.stinkyboi.fleet.airvpn."
PLATFORMS = {
    "macos": ("com.wireguard.macos", 5, "https://apps.apple.com/app/wireguard/id1451685025"),
    "ios": ("com.wireguard.ios", 1, "https://apps.apple.com/app/wireguard/id1441195209"),
}
INTERFACE_KEYS = {"PrivateKey", "Address", "DNS", "ListenPort", "MTU"}
PEER_KEYS = {"PublicKey", "PresharedKey", "AllowedIPs", "Endpoint", "PersistentKeepalive"}


class SetupError(Exception):
    """Only fixed diagnostics; never include a private path or configuration."""


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        self.exit(2, "Invalid arguments; use --help for the supported options.\n")


def load_catalog():
    catalog = json.loads(CATALOG.read_text())
    for platform, (bundle, device_type, url) in PLATFORMS.items():
        item = catalog["platforms"][platform]
        if (item.get("bundle_id") != bundle or type(item.get("target_device_type")) is not int
                or item["target_device_type"] != device_type or item.get("download_url") != url):
            raise SetupError("Catalog platform guard failed")
    policy = catalog["policy"]
    if (policy.get("name") != "WireGuard installed for AirVPN"
            or policy.get("query") != "SELECT 1 FROM apps WHERE bundle_identifier = 'com.wireguard.macos' LIMIT 1;"
            or policy.get("platform") != "darwin" or policy.get("critical") is not False
            or not isinstance(policy.get("description"), str)
            or not isinstance(policy.get("resolution"), str)
            or set(policy) != {"name", "query", "platform", "critical", "description", "resolution"}):
        raise SetupError("Catalog reporting policy guard failed")
    return catalog


def read_config(path):
    """Read once from an owner-only regular file outside the public checkout."""
    try:
        if not path.is_absolute() or path.is_relative_to(ROOT):
            raise SetupError("Configuration must be an absolute private file outside the repository")
        resolved = path.resolve(strict=True)
        if resolved.is_relative_to(ROOT):
            raise SetupError("Configuration must be an absolute private file outside the repository")
        descriptor = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o077):
                raise SetupError("Configuration must be a user-owned regular file with no group or other access")
            raw = source.read(MAX_CONFIG + 1)
        if not raw or len(raw) > MAX_CONFIG:
            raise SetupError("Configuration must contain at most 64 KiB of WireGuard text")
        return raw.decode("utf-8")
    except SetupError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise SetupError("Private configuration could not be read safely") from None


def hostname(value):
    candidate = value.removesuffix(".")
    return (0 < len(candidate) <= 253
            and all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                    for label in candidate.split(".")))


def number(value, minimum, maximum):
    return re.fullmatch(r"[0-9]{1,5}", value) is not None and minimum <= int(value) <= maximum


def parse_config(text):
    """Accept one AirVPN peer without shell hooks or routing overrides."""
    try:
        if (not isinstance(text, str) or not text or len(text.encode("utf-8")) > MAX_CONFIG
                or any(ord(char) < 32 and char not in "\t\r\n" for char in text)):
            raise ValueError
        sections = {}
        current = None
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("["):
                if line not in ("[Interface]", "[Peer]") or line[1:-1] in sections:
                    raise ValueError
                current = line[1:-1]
                if current == "Peer" and "Interface" not in sections:
                    raise ValueError
                sections[current] = {}
                continue
            if current is None or "=" not in line:
                raise ValueError
            key, value = (part.strip() for part in line.split("=", 1))
            allowed = INTERFACE_KEYS if current == "Interface" else PEER_KEYS
            if key not in allowed or key in sections[current] or not value:
                raise ValueError
            sections[current][key] = value
        if set(sections) != {"Interface", "Peer"}:
            raise ValueError
        interface, peer = sections["Interface"], sections["Peer"]
        if not {"PrivateKey", "Address"} <= interface.keys() or not {"PublicKey", "AllowedIPs", "Endpoint"} <= peer.keys():
            raise ValueError
        for value in (interface["PrivateKey"], peer["PublicKey"], peer.get("PresharedKey")):
            if value is not None and (len(value) != 44 or len(base64.b64decode(value, validate=True)) != 32):
                raise ValueError
        for value in interface["Address"].split(","):
            ipaddress.ip_interface(value.strip())
        for value in peer["AllowedIPs"].split(","):
            ipaddress.ip_network(value.strip(), strict=False)
        for value in interface.get("DNS", "").split(",") if "DNS" in interface else []:
            value = value.strip()
            try:
                ipaddress.ip_address(value)
            except ValueError:
                if not hostname(value):
                    raise ValueError from None
        endpoint = peer["Endpoint"]
        if endpoint.startswith("["):
            match = re.fullmatch(r"\[([^\]]+)\]:([0-9]{1,5})", endpoint)
            if match is None or ipaddress.ip_address(match[1]).version != 6:
                raise ValueError
            port = match[2]
        else:
            host, port = endpoint.rsplit(":", 1)
            if not hostname(host):
                raise ValueError
            if re.fullmatch(r"[0-9.]+", host):
                ipaddress.IPv4Address(host)
        if not number(port, 1, 65535):
            raise ValueError
        for fields, key, minimum, maximum in (
                (interface, "ListenPort", 0, 65535), (interface, "MTU", 576, 65535),
                (peer, "PersistentKeepalive", 0, 65535)):
            if key in fields and not number(fields[key], minimum, maximum):
                raise ValueError
        return sections
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise SetupError("Configuration must be a supported single-interface, single-peer WireGuard export") from None


def build_profile(platform, config, catalog):
    parsed = parse_config(config)
    item = catalog["platforms"][platform]
    identifier = IDENTIFIER + platform
    revision = hashlib.sha256(config.encode("utf-8")).hexdigest()

    def payload_uuid(payload_id):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, payload_id + ":" + revision)).upper()

    profile = {
        "PayloadType": "Configuration", "PayloadVersion": 1,
        "PayloadIdentifier": identifier, "PayloadUUID": payload_uuid(identifier),
        "PayloadDisplayName": "AirVPN", "PayloadScope": "System",
        "PayloadRemovalDisallowed": False, "TargetDeviceType": item["target_device_type"],
        "PayloadContent": [{
            "PayloadType": "com.apple.vpn.managed", "PayloadVersion": 1,
            "PayloadIdentifier": identifier + ".vpn", "PayloadUUID": payload_uuid(identifier + ".vpn"),
            "PayloadDisplayName": "AirVPN", "UserDefinedName": "AirVPN",
            "VPNType": "VPN", "VPNSubType": item["bundle_id"],
            "VPN": {"AuthenticationMethod": "Password", "RemoteAddress": parsed["Peer"]["Endpoint"]},
            "VendorConfig": {"WgQuickConfig": config},
        }],
    }
    return plistlib.dumps(profile), profile


def removal_profile(platform):
    return b"", {"PayloadIdentifier": IDENTIFIER + platform}


def list_policies(api, token):
    policies, seen = [], set()
    for page in range(100):
        batch = api.request("GET", f"/api/v1/fleet/global/policies?per_page=100&page={page}", token=token)["policies"]
        if not isinstance(batch, list) or len(batch) > 100:
            raise SetupError("Fleet policy listing is invalid")
        for policy in batch:
            policy_id = policy.get("id")
            if type(policy_id) is not int or policy_id < 1 or policy_id in seen:
                raise SetupError("Fleet policy pagination is incomplete or ambiguous")
            seen.add(policy_id)
            policies.append(policy)
        if len(batch) < 100:
            return policies
    raise SetupError("Fleet policy pagination exceeded the reviewed limit")


def reporting(api, token, policy):
    def matches():
        found = [item for item in list_policies(api, token) if item.get("name") == policy["name"]]
        if len(found) > 1 or any(any(item.get(key) != value for key, value in policy.items()) for item in found):
            raise SetupError("Existing AirVPN policy differs or is ambiguous; review before changing it")
        return found

    if not matches():
        api.request("POST", "/api/v1/fleet/global/policies", policy, token)
    if len(matches()) != 1:
        raise SetupError("AirVPN reporting policy readback failed")
    print("WireGuard macOS reporting policy configured and read back; host evaluation remains pending")


def require_active_host(host, platform):
    expected = ("darwin",) if platform == "macos" else ("ios", "ipados")
    mdm = host.get("mdm") or {}
    if (host.get("platform") not in expected or mdm.get("connected_to_fleet") is not True
            or mdm.get("enrollment_status") not in ("On (manual)", "On (manual - personal)", "On (personal)",
                                                  "On (automatic)", "On (company-owned)")):
        raise SetupError("An active Fleet MDM enrollment is required")


def require_device_enrollment(host, platform, security_info):
    require_active_host(host, platform)
    # Fleet's personal/BYOD label is not Apple's enrollment mode. The device
    # reports the actual mode through SecurityInfo on both Apple platforms.
    management = security_info.get("SecurityInfo", {}).get("ManagementStatus", {})
    if management.get("IsUserEnrollment") is not False:
        raise SetupError("An active Fleet Device Enrollment is required; User Enrollment and unknown modes are unsupported")


def require_wireguard(reply, bundle_id):
    apps = reply.get("InstalledApplicationList")
    if not isinstance(apps, list):
        raise SetupError("WireGuard app inventory could not be verified")
    matches = [app for app in apps if app.get("Identifier") == bundle_id]
    failures = ("Installing", "DownloadFailed", "DownloadWaiting", "DownloadPaused", "DownloadCancelled")
    if len(matches) != 1 or any(matches[0].get(key) is True for key in failures):
        raise SetupError("Install and open the WireGuard app on the selected device before profile delivery")


def load_setup():
    spec = importlib.util.spec_from_file_location("fleet_free_setup", ROOT / "scripts/fleet-free-setup.py")
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    return setup


def execute(args, catalog, desired):
    setup = load_setup()
    api = setup.module("fleet_api", "fleet-download-apple-csr.py")
    mdm = setup.module("fleet_mdm", "fleet-verify-apple-mdm.py")
    api.MAX_RESPONSE = 16 * 1024 * 1024
    token = api.request("POST", "/api/v1/fleet/login", {
        "email": api.ADMIN_EMAIL, "password": api.initial_password(),
    }).get("token")
    if not isinstance(token, str) or not token:
        raise SetupError("Fleet login did not return a session")
    try:
        settings = api.request("GET", "/api/v1/fleet/config", token=token)
        if settings.get("license", {}).get("tier") != "free":
            raise SetupError("Expected Fleet Free; refusing an unverified license contract")
        if args.action == "policy":
            reporting(api, token, catalog["policy"])
            return
        if settings.get("mdm", {}).get("enabled_and_configured") is not True:
            raise SetupError("Fleet Apple MDM is not configured")
        host_uuid = setup.ios_host(api, mdm, token, args.host_id) if args.action == "ios" else mdm.local_host(api, token)
        path = f"/api/v1/fleet/hosts/{args.host_id}" if args.action == "ios" else "/api/v1/fleet/hosts/identifier/" + quote(host_uuid, safe="")
        host = api.request("GET", path, token=token)["host"]
        if mdm.device_identifier(host.get("uuid")) != mdm.device_identifier(host_uuid):
            raise SetupError("Selected device identity changed; refusing profile delivery")
        require_active_host(host, args.action)
        if not args.remove:
            security_info = mdm.command(api, token, host_uuid, {"RequestType": "SecurityInfo"})
            require_device_enrollment(host, args.action, security_info)
            bundle_id = catalog["platforms"][args.action]["bundle_id"]
            apps = mdm.command(api, token, host_uuid, {
                "RequestType": "InstalledApplicationList", "Identifiers": [bundle_id], "ManagedAppsOnly": False,
            })
            require_wireguard(apps, bundle_id)
        setup.apply_profiles(api, mdm, token, host_uuid, desired, remove=args.remove)
        if not args.remove:
            print("Open WireGuard once, connect AirVPN, and verify a handshake and traffic routing on this device; acceptance remains pending")
    finally:
        failed = sys.exc_info()[0] is not None
        try:
            api.request("POST", "/api/v1/fleet/logout", token=token)
            print("Fleet operator session revoked", flush=True)
        except Exception:  # noqa: BLE001 - redact credential-bearing transport failures
            print("Fleet session revocation failed; private details withheld", file=sys.stderr)
            if not failed:
                raise SetupError("Operation acceptance failed because the operator session was not revoked") from None


def main(argv=None):
    parser = PrivateArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("catalog", "policy", "macos", "ios"))
    parser.add_argument("--config", type=Path, help="Private per-device AirVPN .conf outside this public repository")
    parser.add_argument("--host-id", type=int, help="Positive Fleet ID; required only for the selected iPhone/iPad")
    parser.add_argument("--remove", action="store_true", help="Remove only this platform's managed AirVPN profile")
    parser.add_argument("--execute", action="store_true", help="Apply through Fleet; omitted means local validation only")
    args = parser.parse_args(argv)
    if ((args.action == "ios") != (args.host_id is not None)
            or (args.host_id is not None and args.host_id < 1)):
        parser.error("Only ios requires a positive --host-id")
    device = args.action in ("macos", "ios")
    if (args.remove and not device) or (args.config is not None and (not device or args.remove)):
        parser.error("Configuration and removal options apply only to device profiles")
    if device and not args.remove and args.config is None:
        parser.error("Profile installation requires a private configuration")
    try:
        catalog = load_catalog()
        if args.action == "catalog":
            print("WireGuard / AirVPN")
            for platform in PLATFORMS:
                print(platform + ": " + catalog["platforms"][platform]["download_url"])
            print("Install and open WireGuard on each device. Fleet Free does not automatically install the app.\n"
                  "Supply a separate private AirVPN WireGuard export for each device; Device Enrollment is required.\n"
                  "The macOS policy reports app installation only; iPhone/iPad app presence needs separate verification.")
            return 0
        desired = []
        if device:
            desired = [removal_profile(args.action) if args.remove else build_profile(args.action, read_config(args.config), catalog)]
        if not args.execute:
            print("Dry run passed; no Fleet credentials or APIs accessed.")
            print("With --execute: " + ("configure the macOS app-installation reporting policy; host evaluation remains pending."
                  if args.action == "policy" else "target only the selected device, preserve unrelated profiles, and verify profile inventory."))
            if device and not args.remove:
                print("App installation, first launch, AirVPN handshake, and traffic routing still require device acceptance.")
            return 0
        execute(args, catalog, desired)
    except SetupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 - private input and API responses must never enter diagnostics
        print("Fleet AirVPN setup failed or is incomplete; inspect pending commands before retrying. Private details withheld.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
