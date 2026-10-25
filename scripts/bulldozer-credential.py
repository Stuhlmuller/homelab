#!/usr/bin/env python3
"""Store the fixed Bulldozer GitHub App identity from protected CI secrets."""

import json
import os
import re
import subprocess


def main():
    app_id = os.environ["BULLDOZER_APP_ID"].strip()
    private_key = os.environ["BULLDOZER_PRIVATE_KEY"]
    if not re.fullmatch(r"[1-9][0-9]*", app_id):
        raise ValueError("BULLDOZER_APP_ID must be a positive numeric GitHub App ID")
    if len(private_key) > 4000 or "-----BEGIN " not in private_key:
        raise ValueError("BULLDOZER_PRIVATE_KEY must be a PEM private key below the SSM standard limit")
    subprocess.run(["openssl", "pkey", "-noout", "-in", "/dev/stdin"],
                   input=private_key, text=True, capture_output=True, check=True)

    for suffix, value in (("integration-id", app_id), ("private-key", private_key)):
        payload = {"Name": f"/homelab/bulldozer/github-app/{suffix}",
                   "Type": "SecureString", "Value": value, "Overwrite": True}
        subprocess.run(["aws", "ssm", "put-parameter", "--region", "us-west-2",
                        "--cli-input-json", "file:///dev/stdin", "--query", "Version",
                        "--output", "text"], input=json.dumps(payload), text=True,
                       capture_output=True, check=True)
    print("Stored Bulldozer GitHub App ID and private key in fixed SSM parameters")


if __name__ == "__main__":
    main()
