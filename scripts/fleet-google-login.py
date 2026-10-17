#!/usr/bin/env python3
"""Store Google OAuth privately and deliver XCreds settings to the local Fleet Mac."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
PREFERENCES = ROOT / "clusters/homelab/apps/fleet/google-login-preferences.json"
PARAMETER = "/homelab/fleet/google-oauth"
REGION = "us-west-2"
CLIENT_ID = "243156845147-lc3v0cl7qu3jbtt5gacsq4to8skbuljm.apps.googleusercontent.com"
REDIRECT = "https://twocanoes.com/xcreds-redirect"
IDENTIFIER = "com.stinkyboi.fleet.google-xcreds"


class Failure(Exception):
    """Only fixed diagnostics may leave the credential boundary."""


def command(args):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("AWS_ENDPOINT_URL")}
    environment.update(AWS_PAGER="", AWS_IGNORE_CONFIGURED_ENDPOINT_URLS="true")
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                            timeout=120, env=environment)
    if result.returncode:
        raise Failure("Private operator command failed; details withheld")
    return result.stdout


def module(filename):
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def validate_context():
    sha = command(["git", "rev-parse", "HEAD"]).strip()
    if (command(["git", "branch", "--show-current"]).strip() != "main"
            or command(["git", "status", "--porcelain"]).strip()
            or not re.fullmatch(r"[0-9a-f]{40}", sha)
            or command(["git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
                        "refs/heads/main"]).split() != [sha, "refs/heads/main"]
            or command(["gh", "api", f"repos/Stuhlmuller/homelab/commits/{sha}",
                        "--jq", ".commit.verification.verified"]).strip() != "true"):
        raise Failure("Run from clean, signed, current main after protected merge")


def credential(value):
    try:
        web = value["web"]
        if (web["client_id"] != CLIENT_ID or web["project_id"] != "n8n-credentials-498013"
                or web["redirect_uris"] != [REDIRECT]
                or web["auth_uri"] != "https://accounts.google.com/o/oauth2/auth"
                or web["token_uri"] != "https://oauth2.googleapis.com/token"
                or not isinstance(web["client_secret"], str)
                or not re.fullmatch(r"GOCSPX-[A-Za-z0-9_-]{20,128}", web["client_secret"])):
            raise ValueError
        return value
    except (KeyError, TypeError, ValueError):
        raise Failure("Expected the dedicated Google Web client and exact callback") from None


def store(path):
    private = module("fleet-airvpn-setup.py")
    value = credential(json.loads(private.read_private_text(path, 4096)))
    metadata = json.loads(command([
        "aws", "ssm", "describe-parameters", "--region", REGION,
        "--parameter-filters", f"Key=Name,Option=Equals,Values={PARAMETER}", "--output", "json",
    ])).get("Parameters", [])
    if (len(metadata) != 1 or metadata[0].get("Name") != PARAMETER
            or metadata[0].get("Type") != "SecureString"
            or metadata[0].get("KeyId") != "alias/aws/ssm"):
        raise Failure("Apply the declared operator-only Google OAuth SecureString first")
    with tempfile.TemporaryDirectory(prefix="fleet-google-ssm-") as directory:
        target = Path(directory) / "parameter.json"
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"Name": PARAMETER, "Type": "SecureString", "KeyId": "alias/aws/ssm",
                       "Value": json.dumps(value), "Overwrite": True}, stream)
        result = json.loads(command(["aws", "ssm", "put-parameter", "--region", REGION,
                                     "--cli-input-json", f"file://{target}", "--output", "json"]))
    if type(result.get("Version")) is not int or result["Version"] < 1:
        raise Failure("Credential write was not confirmed; inspect before retrying")
    print("Google OAuth stored in the declared operator-only SecureString; values withheld.")


def read_credential():
    parameter = json.loads(command([
        "aws", "ssm", "get-parameter", "--region", REGION, "--name", PARAMETER,
        "--with-decryption", "--output", "json",
    ]))["Parameter"]
    if parameter.get("Name") != PARAMETER or parameter.get("Type") != "SecureString":
        raise Failure("Google OAuth SecureString identity mismatch")
    return credential(json.loads(parameter["Value"]))


def profile(value):
    preferences = json.loads(PREFERENCES.read_text())
    web = credential(value)["web"]
    preferences.update(clientID=web["client_id"], clientSecret=web["client_secret"])
    payload = {
        **preferences, "PayloadType": "com.twocanoes.xcreds", "PayloadVersion": 1,
        "PayloadIdentifier": IDENTIFIER + ".preferences",
        "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_URL, IDENTIFIER + ".preferences")),
    }
    result = {
        "PayloadType": "Configuration", "PayloadVersion": 1, "PayloadScope": "System",
        "PayloadIdentifier": IDENTIFIER, "PayloadDisplayName": "Google Workspace Mac login",
        "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_URL, IDENTIFIER)),
        "PayloadRemovalDisallowed": False, "TargetDeviceType": 5,
        "PayloadContent": [payload],
    }
    return plistlib.dumps(result), result


def apply_profile(remove=False, host_id=None, native_login_restored=False):
    setup = module("fleet-free-setup.py")
    api = module("fleet-download-apple-csr.py")
    mdm = module("fleet-verify-apple-mdm.py")
    # Removal needs no usable OAuth credential, including after its revocation.
    if remove and host_id is None:
        rights = plistlib.loads(command(["/usr/bin/security", "authorizationdb", "read",
                                        "system.login.console"]).encode())
        if any("xcreds" in item.lower() for item in rights.get("mechanisms", [])):
            raise Failure("Restore native login with the vendor rollback command before removing settings")
    if remove:
        if host_id is not None and not native_login_restored:
            raise Failure("Confirm native login on the selected Mac before remote profile removal")
        desired = [(b"", {"PayloadIdentifier": IDENTIFIER})]
    else:
        desired = [profile(read_credential())]
    api.MAX_RESPONSE = 16 * 1024 * 1024
    token = api.request("POST", "/api/v1/fleet/login", {
        "email": api.ADMIN_EMAIL, "password": api.initial_password(),
    }).get("token")
    if not isinstance(token, str) or not token:
        raise Failure("Fleet login did not return a session")
    try:
        host = setup.mac_host(api, mdm, token, host_id) if host_id is not None else mdm.local_host(api, token)
        setup.apply_profiles(api, mdm, token, host, desired, remove=remove)
    finally:
        api.request("POST", "/api/v1/fleet/logout", token=token)
    print("Selected Mac profile delivery verified; sign-in acceptance is still required.")


def install_software(path):
    catalog = json.loads(PREFERENCES.with_name("google-login-installer.json").read_text())
    if command(["/usr/bin/uname", "-s"]).strip() != "Darwin":
        raise Failure("Installer requires the enrolled Mac")
    # Activate the replacement login window only after MDM delivered its settings.
    if command(["/usr/bin/defaults", "read", "/Library/Managed Preferences/com.twocanoes.xcreds",
                "clientID"]).strip() != CLIENT_ID:
        raise Failure("Install and verify the Google login profile before activating XCreds")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise Failure("Installer must be a regular package file")
        raw = source.read(100 * 1024 * 1024 + 1)
    if len(raw) > 100 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != catalog["sha256"]:
        raise Failure("Installer digest does not match the reviewed stable release")
    with tempfile.TemporaryDirectory(prefix="fleet-xcreds-package-") as directory:
        verified = Path(directory) / "XCreds.pkg"
        descriptor = os.open(verified, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(raw)
        signature = command(["/usr/sbin/pkgutil", "--check-signature", str(verified)])
        if catalog["installer_identity"] not in signature:
            raise Failure("Installer signing identity mismatch")
        command(["/usr/sbin/spctl", "--assess", "--type", "install", str(verified)])
        command(["/usr/bin/sudo", "-n", "/usr/sbin/installer", "-pkg", str(verified), "-target", "/"])
    info = plistlib.loads(Path("/Applications/XCreds.app/Contents/Info.plist").read_bytes())
    if info.get("CFBundleShortVersionString") != catalog["version"] or info.get("CFBundleVersion") != catalog["build"]:
        raise Failure("Installed XCreds version differs from the reviewed package")
    command(["/usr/bin/codesign", "--verify", "--deep", "--strict", "/Applications/XCreds.app"])
    print("Pinned XCreds installed and verified; Google sign-in and FileVault acceptance remain interactive.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "store", "install-profile", "remove-profile", "install-software"))
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--package-file", type=Path)
    parser.add_argument("--host-id", type=int, help="Explicit enrolled Fleet Mac ID for profile delivery or removal")
    parser.add_argument("--native-login-restored", action="store_true", help="Attest native login was verified on the selected remote Mac before profile removal")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if (args.action == "store") != (args.credential_file is not None):
        parser.error("Only store requires --credential-file with an owner-only absolute file")
    if (args.action == "install-software") != (args.package_file is not None):
        parser.error("Only install-software requires --package-file with the pinned vendor installer")
    if args.host_id is not None and (args.action not in ("install-profile", "remove-profile") or args.host_id < 1):
        parser.error("Profile delivery and removal require a positive Fleet Mac ID")
    if args.native_login_restored and (args.action != "remove-profile" or args.host_id is None):
        parser.error("--native-login-restored applies only to remote profile removal")
    try:
        json.loads(PREFERENCES.read_text())
        if not args.execute:
            print("Dry run: settings parse; no credential, cloud or device access. "
                  "All writes require clean, signed, current main and --execute.")
            return 0
        if args.action == "validate":
            return 0
        validate_context()
        if args.action == "store":
            store(args.credential_file)
        elif args.action == "install-software":
            install_software(args.package_file)
        else:
            apply_profile(remove=args.action == "remove-profile", host_id=args.host_id,
                          native_login_restored=args.native_login_restored)
        return 0
    except Exception:  # noqa: BLE001 - credential-bearing transport and parser failures must be redacted.
        print("Google login setup failed or is incomplete; private details withheld.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
