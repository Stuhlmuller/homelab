#!/usr/bin/env python3
"""Store the fixed Bulldozer GitHub App identity from protected CI secrets."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    app_id = os.environ.pop("BULLDOZER_APP_ID").strip()
    private_key = os.environ.pop("BULLDOZER_PRIVATE_KEY")
    if not re.fullmatch(r"[1-9][0-9]*", app_id):
        raise ValueError("BULLDOZER_APP_ID must be a positive numeric GitHub App ID")
    if len(private_key) > 4000 or "-----BEGIN " not in private_key:
        raise ValueError("BULLDOZER_PRIVATE_KEY must be a PEM private key below the SSM standard limit")
    subprocess.run(["openssl", "pkey", "-noout", "-in", "/dev/stdin"],
                   input=private_key, text=True, capture_output=True, check=True)

    for suffix, value in (("integration-id", app_id), ("private-key", private_key)):
        payload = {"Name": f"/homelab/bulldozer/github-app/{suffix}",
                   "Type": "SecureString", "Value": value, "Overwrite": True}
        # AWS CLI's file:// loader cannot parse a non-seekable stdin pipe.
        with tempfile.TemporaryDirectory(prefix="bulldozer-ssm-") as directory:
            path = Path(directory) / "parameter.json"
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                           "w", encoding="utf-8") as stream:
                json.dump(payload, stream)
            subprocess.run(["aws", "ssm", "put-parameter", "--region", "us-west-2",
                            "--cli-input-json", f"file://{path}", "--query", "Version",
                            "--output", "text"], text=True, capture_output=True, check=True)
    print("Stored Bulldozer GitHub App ID and private key in fixed SSM parameters")


if __name__ == "__main__":
    main()
