#!/usr/bin/env python3
"""Create Fleet's first administrator through the private Service exactly once.

Passwords and API tokens stay in memory; no response bodies enter Job logs.
Fleet closes both setup routes once any user exists. Repeated syncs preserve
accounts, passwords, enrollment secrets, and settings changed in Fleet.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "http://fleet.fleet.svc.cluster.local:8080"
SERVER_URL = "https://fleet.stinkyboi.com"
ADMIN_EMAIL = "rodman@stuhlmuller.net"
MAX_RESPONSE = 1024 * 1024


class BootstrapError(Exception):
    """Only fixed, credential-free diagnostics may escape bootstrap."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )

    def request(self, method, path, body=None, token=None):
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            ENDPOINT + path, data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=120) as response:
                status, raw = response.status, response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            return status, None
        except (OSError, ValueError):
            raise BootstrapError("Fleet bootstrap transport failed") from None
        if len(raw) > MAX_RESPONSE:
            raise BootstrapError("Fleet bootstrap response exceeded its limit")
        if not raw:
            return status, None
        try:
            return status, json.loads(raw)
        except (UnicodeError, ValueError):
            raise BootstrapError("Fleet bootstrap returned invalid JSON") from None


def bootstrap(client, password):
    if len(password) < 32 or password == "REPLACE_ME":
        raise BootstrapError("Fleet administrator password is missing or invalid")
    status, result = client.request("POST", "/api/v1/setup", {
        "admin": {"email": ADMIN_EMAIL, "name": "Rodman", "password": password},
        "org_info": {"org_name": "Stuhlmuller Family"},
        "server_url": SERVER_URL,
    })
    if status == 404:
        # Unlike the setup router's blanket 404, the configured API enforces
        # authentication on this endpoint. This also rejects a wrong backend.
        status, _ = client.request("GET", "/api/v1/fleet/me")
        if status != 401:
            raise BootstrapError("Fleet setup closure could not be verified")
        print("Fleet already initialized; existing accounts preserved")
        return
    if (status != 200 or not isinstance(result, dict)
            or not isinstance(result.get("token"), str) or not result["token"]):
        raise BootstrapError("Fleet first-administrator creation was not verified")
    token = result["token"]
    try:
        if (result.get("error") or not isinstance(result.get("admin"), dict)
                or result["admin"].get("email") != ADMIN_EMAIL
                or result["admin"].get("global_role") != "admin"):
            raise BootstrapError("Fleet first-administrator creation was not verified")
        status, account = client.request("GET", "/api/v1/fleet/me", token=token)
        if (status != 200 or not isinstance(account, dict)
                or not isinstance(account.get("user"), dict)
                or account["user"].get("email") != ADMIN_EMAIL
                or account["user"].get("global_role") != "admin"):
            raise BootstrapError("Fleet administrator authentication was not verified")
    finally:
        status, _ = client.request("POST", "/api/v1/fleet/logout", token=token)
        if status != 200:
            raise BootstrapError("Fleet bootstrap session cleanup failed")
    print("Fleet administrator created and authenticated; bootstrap session revoked")


def main():
    try:
        password = Path("/secrets/admin-password").read_text().strip()
        bootstrap(Client(), password)
    except BootstrapError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - Never log credential-bearing exception details.
        print("Fleet bootstrap failed; private details withheld", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
