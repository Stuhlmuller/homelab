#!/usr/bin/env python3
"""Download Fleet's Apple CSR or activate Apple MDM with its APNs certificate."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import base64
import json
import os
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FLEET_URL = "https://fleet.stinkyboi.com"
ADMIN_EMAIL = "rodman@stuhlmuller.net"
MAX_RESPONSE = 1024 * 1024
MAX_CERTIFICATE = 64 * 1024
CERTIFICATE_BEGIN = b"-----BEGIN " + b"CERTIFICATE-----"
CERTIFICATE_END = b"-----END " + b"CERTIFICATE-----"


class DownloadError(Exception):
    """Fixed diagnostics only; API responses and credentials remain private."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(method, path, body=None, token=None, content_type="application/json", accepted_status=200):
    headers = {"Accept": "application/json", "User-Agent": "Fleet-Apple-Setup/1.0"}
    data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(urllib.request.Request(
                FLEET_URL + path, data=data, headers=headers, method=method), timeout=60) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if response.status != accepted_status or len(raw) > MAX_RESPONSE:
                raise DownloadError("Fleet API returned an invalid or oversized response")
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        raise DownloadError(f"Fleet API request failed (HTTP {status})") from None
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("error"):
        raise DownloadError("Fleet API returned an invalid response")
    return result


def initial_password():
    result = subprocess.run(
        ["kubectl", "-n", "fleet", "get", "secret", "fleet-admin", "-o", "json"],
        capture_output=True, check=True, timeout=30,
    )
    value = json.loads(result.stdout)["data"]["admin-password"]
    password = base64.b64decode(value, validate=True).decode()
    if not password or password == "REPLACE_ME":
        raise DownloadError("Fleet initial administrator credential is unavailable")
    return password


def download(output):
    # Reserve the destination before login or the stateful CSR request. O_EXCL
    # also rejects existing symlinks without following them.
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise DownloadError("Output already exists; choose a new path") from None
    except OSError:
        raise DownloadError("CSR output could not be created") from None

    complete = False
    try:
        with os.fdopen(descriptor, "wb") as destination:
            result = request("POST", "/api/v1/fleet/login", {
                "email": ADMIN_EMAIL, "password": initial_password(),
            })
            token = result.get("token")
            if not isinstance(token, str) or not token:
                raise DownloadError("Fleet login did not return a session")
            try:
                result = request("GET", "/api/v1/fleet/mdm/apple/request_csr", token=token)
                csr = base64.b64decode(result["csr"], validate=True)
                if not csr:
                    raise DownloadError("Fleet returned empty CSR data")
            finally:
                request("POST", "/api/v1/fleet/logout", token=token)
            # The JSON field encodes signed CSR bytes once. Preserve those bytes
            # exactly; the Apple upload artifact can itself contain base64 text.
            destination.write(csr)
        complete = True
    finally:
        if not complete:
            output.unlink(missing_ok=True)


def upload(certificate):
    with certificate.open("rb") as source:
        pem = source.read(MAX_CERTIFICATE + 1)
    if (not pem or len(pem) > MAX_CERTIFICATE or b"PRIVATE KEY" in pem
            or pem.count(CERTIFICATE_BEGIN) != 1
            or not pem.strip().startswith(CERTIFICATE_BEGIN)
            or not pem.strip().endswith(CERTIFICATE_END)):
        raise DownloadError("A single PEM certificate without private keys is required")
    # Parse certificate syntax locally. Fleet verifies its match to the CSR key.
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=pem.decode("ascii"))
    result = request("POST", "/api/v1/fleet/login", {
        "email": ADMIN_EMAIL, "password": initial_password(),
    })
    token = result.get("token")
    if not isinstance(token, str) or not token:
        raise DownloadError("Fleet login did not return a session")
    try:
        config = request("GET", "/api/v1/fleet/config", token=token)
        enabled = config.get("mdm", {}).get("enabled_and_configured")
        if enabled is True:
            raise DownloadError("Apple MDM is already enabled; use a reviewed certificate renewal workflow")
        if enabled is not False:
            raise DownloadError("Fleet Apple MDM configuration could not be verified")
        boundary = "fleet-apple-apns-certificate"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="certificate"; filename="apns.pem"\r\n'
                'Content-Type: application/x-pem-file\r\n\r\n').encode() + pem + f"\r\n--{boundary}--\r\n".encode()
        request("POST", "/api/v1/fleet/mdm/apple/apns_certificate", body, token,
                content_type=f"multipart/form-data; boundary={boundary}", accepted_status=202)
        config = request("GET", "/api/v1/fleet/config", token=token)
        if config.get("mdm", {}).get("enabled_and_configured") is not True:
            raise DownloadError("Fleet did not confirm Apple MDM activation")
        apns = request("GET", "/api/v1/fleet/apns", token=token)
        renew_date = datetime.fromisoformat(apns["renew_date"].replace("Z", "+00:00"))
        if renew_date.tzinfo is None or renew_date <= datetime.now(timezone.utc):
            raise DownloadError("Fleet did not return a valid future APNs renewal date")
        return renew_date.isoformat()
    finally:
        request("POST", "/api/v1/fleet/logout", token=token)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path,
                      help="New private output file, conventionally fleet-mdm-apple.csr")
    mode.add_argument("--certificate", type=Path, help="Apple APNs PEM certificate for initial activation")
    args = parser.parse_args(argv)
    try:
        if args.certificate:
            renew_date = upload(args.certificate)
        else:
            download(args.output)
    except DownloadError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - Never log credential-bearing exception details.
        print("Fleet Apple setup failed; private details withheld", file=sys.stderr)
        return 1
    print(f"Apple MDM enabled; APNs renewal date: {renew_date}" if args.certificate
          else f"Signed Apple CSR saved to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
