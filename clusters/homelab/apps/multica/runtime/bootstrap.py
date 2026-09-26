"""Initialize the persistent Multica profile without logging credentials."""

import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


def request(server, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(server + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def bootstrap(settings, directory, code_file, api=request):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "config.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    server = settings["server_url"]
    token = config.get("token")
    if token:
        # Fail closed on revoked/expired credentials; do not silently undo revocation.
        user = api(server, "/api/me", token)
    else:
        code = code_file.read_text().strip()
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ValueError("bootstrap code must contain six ASCII digits")
        email = {"email": settings["email"]}
        try:
            api(server, "/auth/send-code", body=email)
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise
            time.sleep(61)
            api(server, "/auth/send-code", body=email)
        login = api(server, "/auth/verify-code", body={**email, "code": code})
        user = login["user"]
        if user["email"] != settings["email"]:
            raise ValueError("bootstrap returned a different user")
        token = api(server, "/api/tokens/", login["token"], {
            "name": "multica-server-runtime", "expires_in_days": 90,
        })["token"]
    if user["email"] != settings["email"]:
        raise ValueError("stored runtime token belongs to a different user")
    config.update({key: value for key, value in settings.items() if key != "email"})
    config["token"] = token
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)
    print("Multica runtime profile ready")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        bootstrap(
            json.loads(Path("/etc/multica-runtime/settings.json").read_text()),
            Path.home() / ".multica",
            Path("/run/multica-bootstrap/code"),
        )
    except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
        # HTTP bodies and response tokens must never reach Kubernetes logs.
        print(f"Runtime bootstrap failed: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
