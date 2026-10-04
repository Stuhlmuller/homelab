#!/usr/bin/env python3
"""Verify reversible Apple MDM profile delivery to this local Mac only."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import base64
import importlib.util
import json
import plistlib
import re
import signal
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode


class VerificationError(Exception):
    """Only fixed, non-sensitive diagnostics are allowed."""


def timeout(_signum, _frame):
    raise VerificationError("Apple MDM command timed out; delivery may still be pending")


def device_identifier(value):
    """Validate Apple UUID/UDID forms; normalize only hex letter case."""
    if (not isinstance(value, str) or len(value) not in (25, 36, 40)
            or re.fullmatch(r"(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{16}|[0-9a-fA-F]{40}|"
                            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})", value) is None):
        raise VerificationError("Apple device identifier has an invalid format")
    return value.lower()


def command(api, token, host_uuid, contents):
    expected_device = device_identifier(host_uuid)
    command_uuid = str(uuid.uuid4())
    payload = plistlib.dumps({"CommandUUID": command_uuid, "Command": contents})
    old_handler = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, 90)
    print("Checking Apple MDM command: " + contents["RequestType"], flush=True)
    try:
        queued = api.request("POST", "/api/v1/fleet/commands/run", {
            "host_uuids": [host_uuid], "command": base64.b64encode(payload).decode(),
        }, token)
        if (queued.get("command_uuid") != command_uuid
                or queued.get("request_type") != contents["RequestType"]
                or queued.get("failed_uuids")):
            raise VerificationError("Fleet did not confirm the exact MDM command")
        query = urlencode({"command_uuid": command_uuid, "host_identifier": host_uuid})
        while True:
            results = api.request("GET", "/api/v1/fleet/commands/results?" + query, token=token).get("results", [])
            if results:
                if len(results) != 1:
                    raise VerificationError("Fleet returned ambiguous MDM command results")
                result = results[0]
                if (device_identifier(result.get("host_uuid")) != expected_device or result.get("command_uuid") != command_uuid
                        or result.get("request_type") != contents["RequestType"]):
                    raise VerificationError("Fleet MDM result identity did not match")
                if result.get("status") == "Acknowledged":
                    reply = plistlib.loads(base64.b64decode(result["result"], validate=True))
                    if (reply.get("Status") != "Acknowledged" or reply.get("CommandUUID") != command_uuid
                            or device_identifier(reply.get("UDID")) != expected_device):
                        raise VerificationError("Apple MDM acknowledgement identity did not match")
                    return reply
                if result.get("status") not in ("Pending", "NotNow"):
                    raise VerificationError("Apple device rejected the MDM command")
            time.sleep(3)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def profile_identifiers(reply):
    profiles = reply.get("ProfileList")
    if not isinstance(profiles, list):
        raise VerificationError("Apple device did not return its profile inventory")
    identifiers = [profile.get("PayloadIdentifier") for profile in profiles]
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise VerificationError("Apple profile inventory contains invalid identifiers")
    return set(identifiers)


def local_host(api, token):
    if sys.platform != "darwin":
        raise VerificationError("This verifier must run on the enrolled Mac")
    hardware = subprocess.run(
        ["/usr/sbin/system_profiler", "-json", "SPHardwareDataType"],
        capture_output=True, check=True, timeout=30,
    )
    hardware = json.loads(hardware.stdout)["SPHardwareDataType"]
    if len(hardware) != 1:
        raise VerificationError("Local Mac hardware identity is ambiguous")
    serial = hardware[0].get("serial_number")
    hardware_uuid = uuid.UUID(hardware[0]["platform_UUID"])
    if not isinstance(serial, str) or not serial:
        raise VerificationError("Local Mac serial number is unavailable")
    query = urlencode({"query": serial, "per_page": 100})
    listing = api.request("GET", "/api/v1/fleet/hosts?" + query, token=token)
    hosts = listing["hosts"]
    if not isinstance(hosts, list) or len(hosts) >= 100:
        raise VerificationError("Fleet identity search is incomplete")
    matches = [host for host in hosts if host.get("platform") == "darwin"
               and host.get("hardware_serial") == serial and uuid.UUID(host["uuid"]) == hardware_uuid]
    if len(matches) != 1:
        raise VerificationError("Exactly one Fleet Mac must match both local serial and hardware UUID")
    print("Exact local Mac identity matched: true", flush=True)
    return matches[0]["uuid"]


def verify(api, token, host_uuid):
    baseline = profile_identifiers(command(api, token, host_uuid, {"RequestType": "ProfileList"}))
    identifier = "com.stinkyboi.fleet.smoketest." + str(uuid.uuid4())
    profile = {
        "PayloadType": "Configuration", "PayloadVersion": 1,
        "PayloadUUID": str(uuid.uuid4()), "PayloadIdentifier": identifier,
        "PayloadDisplayName": "Fleet temporary MDM verification",
        "PayloadScope": "System", "PayloadRemovalDisallowed": False,
        "PayloadContent": [{
            "PayloadType": "com.apple.ManagedClient.preferences", "PayloadVersion": 1,
            "PayloadUUID": str(uuid.uuid4()), "PayloadIdentifier": identifier + ".preferences",
            "PayloadContent": {identifier: {"Forced": [{"mcx_preference_settings": {"SmokeTest": True}}]}},
        }],
    }
    try:
        command(api, token, host_uuid, {"RequestType": "InstallProfile", "Payload": plistlib.dumps(profile)})
        installed = profile_identifiers(command(api, token, host_uuid, {"RequestType": "ProfileList"}))
        if identifier not in installed or not baseline <= installed:
            raise VerificationError("Apple device did not confirm the isolated test profile installation")
        print("Test profile installation acknowledged and present: true", flush=True)
    finally:
        # Also remove after an uncertain install response: the original write may
        # have succeeded. Each command is sent once; no automatic write retries.
        try:
            try:
                command(api, token, host_uuid, {"RequestType": "RemoveProfile", "Identifier": identifier})
            finally:
                remaining = profile_identifiers(command(api, token, host_uuid, {"RequestType": "ProfileList"}))
            if identifier in remaining or not baseline <= remaining:
                raise VerificationError("Apple device profile cleanup could not be verified")
        except BaseException:  # noqa: BLE001 - report interrupted cleanup without private device responses
            raise VerificationError(
                "MDM cleanup failed or is unconfirmed; inspect this Mac's temporary Fleet verification profile"
            ) from None
        print("Test profile absent and pre-existing profiles retained: true", flush=True)


def execute():
    spec = importlib.util.spec_from_file_location("fleet_apple_setup", Path(__file__).with_name("fleet-download-apple-csr.py"))
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    api.MAX_RESPONSE = 16 * 1024 * 1024
    login = api.request("POST", "/api/v1/fleet/login", {
        "email": api.ADMIN_EMAIL, "password": api.initial_password(),
    })
    token = login.get("token")
    if not isinstance(token, str) or not token:
        raise VerificationError("Fleet login did not return a session")
    try:
        verify(api, token, local_host(api, token))
    finally:
        failed = sys.exc_info()[0] is not None
        try:
            api.request("POST", "/api/v1/fleet/logout", token=token)
        except Exception:  # noqa: BLE001 - never log credential-bearing logout failures
            print("Fleet session revocation failed", file=sys.stderr)
            if not failed:
                raise VerificationError("Verification not accepted because session revocation failed") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Run the profile test on this exact enrolled Mac")
    if not parser.parse_args(argv).execute:
        print("Dry run: no credentials read and no API requests sent.\n"
              "With --execute: privately match this Mac's serial and hardware UUID to exactly one Fleet Mac;\n"
              "read ProfileList; install a unique removable com.stinkyboi.fleet.smoketest profile setting\n"
              "only SmokeTest=true in an unused preference domain; verify its presence; remove it;\n"
              "verify its absence and retention of every pre-existing profile; revoke the API session.\n"
              "Each command targets only that Mac, is submitted once, and waits at most 90 seconds.\n"
              "Run outside the agent sandbox so macOS can expose the correct hardware identity.")
        return 0
    try:
        execute()
    except VerificationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 - redact unexpected operator-boundary failures
        print("Fleet Apple MDM verification failed; private details withheld", file=sys.stderr)
        return 1
    print("Apple MDM profile install/remove acceptance passed for this Mac")
    return 0


if __name__ == "__main__":
    sys.exit(main())
