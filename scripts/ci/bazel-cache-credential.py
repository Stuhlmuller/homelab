#!/usr/bin/env python3
"""Return the Bazel write credential only for the Homelab cache host."""
import base64
import json
import subprocess
import sys
from urllib.parse import urlsplit


def main():
    if sys.argv[1:] != ["get"]:
        raise ValueError("Unsupported credential helper command")
    target = urlsplit(json.load(sys.stdin)["uri"])
    if target.scheme != "https" or target.netloc != "bazel-cache.stinkyboi.com":
        raise ValueError("Unexpected credential target")

    name = "/homelab/bazel-cache/writer-password"
    result = subprocess.run(
        ["aws", "ssm", "get-parameter", "--region", "us-west-2", "--name", name,
         "--with-decryption", "--output", "json", "--no-cli-pager"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    parameter = json.loads(result.stdout)["Parameter"]
    password = parameter["Value"]
    if parameter["Name"] != name or parameter["Type"] != "SecureString" or not password:
        raise ValueError("Unexpected credential response")
    encoded = base64.b64encode(f"bazel-writer:{password}".encode()).decode("ascii")
    print(json.dumps({"headers": {"Authorization": [f"Basic {encoded}"]}}))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.SubprocessError):
        sys.exit("Bazel cache credential unavailable. Check the authorized AWS session.")
