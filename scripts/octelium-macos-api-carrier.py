#!/usr/bin/env python3
"""Install the native Octelium API carrier on macOS; run with sudo."""

import argparse
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import time

HOST = "octelium-api.stinkyboi.com"
TRANSPORT = "octelium-transport.stinkyboi.com"
LABEL = "com.stuhlmuller.octelium-api-carrier"
PLIST = Path("/Library/LaunchDaemons") / f"{LABEL}.plist"
MARKER = "# homelab-octelium-api-carrier"


def hosts_content(original, install):
    lines = [line for line in original.splitlines() if not line.endswith(MARKER)]
    if install:
        for line in lines:
            if HOST in line.split("#", 1)[0].split()[1:]:
                raise ValueError("Existing Octelium API hosts entry must be reviewed first")
        lines.append(f"127.0.0.1 {HOST} {MARKER}")
    return "\n".join(lines) + "\n"


def replace_hosts(path, content):
    path = path.resolve()
    original = path.stat()
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.chmod(temporary, original.st_mode & 0o777)
            os.chown(temporary, original.st_uid, original.st_gid)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def probe(protocol):
    result = subprocess.run([
        "/usr/bin/curl", "--silent", "--show-error", "--http2", "--max-time", "10",
        "--connect-to", f"{HOST}:443:127.0.0.1:443", "--noproxy", "*",
        "--header", f"content-type: {protocol}", "--header", "x-grpc-web: 1",
        "--header", "TE: trailers", "--data-binary", "", "--dump-header", "-",  # codespell:ignore te
        "--output", "/dev/null", f"https://{HOST}/octelium.api.main.user.v1.MainService/GetStatus",
    ], capture_output=True, text=True, timeout=12)
    headers = [line.strip().lower() for line in result.stdout.splitlines()]
    return (result.returncode == 0 and "http/2 200" in headers
            and "grpc-status: 16" in headers and f"content-type: {protocol}" in headers)


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    args = parser.parse_args()
    if sys.platform != "darwin" or os.geteuid() != 0:
        parser.error("Run this script with sudo on macOS")
    hosts = Path("/etc/hosts")
    original = hosts.read_text()
    desired = hosts_content(original, args.action == "install")
    running = subprocess.run(["launchctl", "print", f"system/{LABEL}"], capture_output=True).returncode == 0
    if args.action == "uninstall":
        # Restore DNS before stopping the listener so browser requests stay usable.
        replace_hosts(hosts, desired)
        if running:
            run("launchctl", "bootout", f"system/{LABEL}")
        PLIST.unlink(missing_ok=True)
    else:
        binary = next((p for p in ("/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared") if Path(p).is_file()), None)
        if not binary:
            raise RuntimeError("Install cloudflared from its official distribution first")
        # Preserve existing installation; never replace another listener on 443.
        if not running:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 443))
            config = {
                "Label": LABEL,
                "ProgramArguments": [binary, "access", "tcp", "--hostname", TRANSPORT, "--url", "127.0.0.1:443"],
                "RunAtLoad": True,
                "KeepAlive": True,
                "ThrottleInterval": 30,
                "ProcessType": "Background",
            }
            PLIST.write_bytes(plistlib.dumps(config))
            PLIST.chmod(0o644)
            run("launchctl", "bootstrap", "system", str(PLIST))
        try:
            for attempt in range(5):
                if probe("application/grpc") and probe("application/grpc-web+proto"):
                    break
                if attempt == 4:
                    raise RuntimeError("API carrier failed TLS/gRPC checks; hosts file unchanged")
                time.sleep(1)
            replace_hosts(hosts, desired)
        except Exception:
            if not running:
                subprocess.run(["launchctl", "bootout", f"system/{LABEL}"], check=False)
                PLIST.unlink(missing_ok=True)
            raise
    run("dscacheutil", "-flushcache")
    run("killall", "-HUP", "mDNSResponder")
    print(f"Octelium API carrier {args.action} complete; public DNS and TLS verification unchanged")


if __name__ == "__main__":
    main()
