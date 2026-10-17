#!/usr/bin/env python3
"""Install the native Octelium API carrier on macOS; run with sudo."""

import argparse
import ipaddress
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


def probe(protocol, address="127.0.0.1"):
    target = f"[{address}]" if address and ":" in address else address
    connection = ["--connect-to", f"{HOST}:443:{target}:443"] if target else []
    result = subprocess.run([
        "/usr/bin/curl", "--silent", "--show-error", "--http2", "--max-time", "10",
        *connection, "--noproxy", "*",
        "--header", f"content-type: {protocol}", "--header", "x-grpc-web: 1",
        "--header", "TE: trailers", "--data-binary", "", "--dump-header", "-",  # codespell:ignore te
        "--output", "/dev/null", f"https://{HOST}/octelium.api.main.user.v1.MainService/GetStatus",
    ], capture_output=True, text=True, timeout=12)
    headers = [line.strip().lower() for line in result.stdout.splitlines()]
    return (result.returncode == 0 and "http/2 200" in headers
            and "grpc-status: 16" in headers and f"content-type: {protocol}" in headers)


def run(*args):
    subprocess.run(args, check=True)


def is_mesh_address(value):
    address = ipaddress.ip_address(value)
    return address in ipaddress.ip_network("100.64.0.0/10") or address in ipaddress.ip_network("fd7a:115c:a1e0::/48")


def public_addresses():
    # Query DNS directly: getaddrinfo still sees the owned loopback hosts stanza.
    # The fixed public resolver sees the published A/AAAA records, not MagicDNS.
    addresses = set()
    for kind in ("A", "AAAA"):
        result = subprocess.run(["/usr/bin/dig", "@1.1.1.1", HOST, kind, "+noall", "+comments", "+answer", "+time=3", "+tries=1"],
                                capture_output=True, text=True, check=True, timeout=5)
        if "status: NOERROR," not in result.stdout:
            raise RuntimeError("Canonical API public DNS lookup failed; carrier unchanged")
        for line in result.stdout.splitlines():
            if not line.strip() or line.startswith(";"):
                continue
            fields = line.split()
            try:
                if len(fields) != 5 or fields[0].rstrip(".") != HOST or fields[2:4] != ["IN", kind]:
                    raise ValueError
                address = ipaddress.ip_address(fields[4])
                if address.version != (4 if kind == "A" else 6):
                    raise ValueError
                addresses.add(str(address))
            except (ValueError, IndexError):
                raise RuntimeError("Canonical API public DNS must contain direct mesh A/AAAA records") from None
    return addresses


def flush_dns():
    run("dscacheutil", "-flushcache")
    run("killall", "-HUP", "mDNSResponder")


def migrate_to_tailscale(hosts, addresses, running):
    allowed = {str(ipaddress.ip_address(value)) for value in addresses}
    if not allowed or any(not is_mesh_address(value) for value in allowed):
        raise RuntimeError("Migration requires the verified ingress Tailscale addresses")
    original = hosts.read_text()
    desired = hosts_content(original, False)
    for line in desired.splitlines():
        fields = line.split("#", 1)[0].split()
        if HOST in fields[1:] and fields[0] not in allowed:
            raise RuntimeError("An unrelated hosts entry would override canonical API mesh DNS")
    resolved = public_addresses()
    if not resolved or not resolved.issubset(allowed):
        raise RuntimeError("Canonical API public DNS does not point exclusively to the verified mesh peer")
    protocols = ("application/grpc", "application/grpc-web+proto")
    if not all(probe(protocol, address) for address in sorted(resolved) for protocol in protocols):
        raise RuntimeError("Canonical native API TLS/gRPC over Tailscale failed; carrier unchanged")
    migration_backup(original)
    daemon = PLIST.read_bytes() if PLIST.exists() else None
    mode = PLIST.stat().st_mode & 0o777 if daemon else None
    try:
        replace_hosts(hosts, desired)
        flush_dns()
        native = {str(ipaddress.ip_address(item[4][0])) for item in socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)}
        if not native or not native.issubset(allowed) or not all(probe(protocol, None) for protocol in protocols):
            raise RuntimeError("Canonical native API check failed after removing the hosts override")
        if running:
            run("launchctl", "bootout", f"system/{LABEL}")
        PLIST.unlink(missing_ok=True)
    except Exception:
        # Restore this invocation's state, never an older .before-tailscale backup.
        current = hosts.read_text()
        owned = "".join(line + "\n" for line in original.splitlines() if line.endswith(MARKER))
        replace_hosts(hosts, original if current == desired else hosts_content(current, False) + owned)
        if daemon is not None:
            PLIST.write_bytes(daemon)
            PLIST.chmod(mode)
        if running and subprocess.run(["launchctl", "print", f"system/{LABEL}"], capture_output=True).returncode:
            run("launchctl", "bootstrap", "system", str(PLIST))
        flush_dns()
        raise


def migration_backup(original):
    snapshots = {PLIST.with_suffix(".hosts.before-tailscale"):
                 "".join(line + "\n" for line in original.splitlines() if line.endswith(MARKER)).encode()}
    if PLIST.exists():
        config = plistlib.loads(PLIST.read_bytes())
        if config.get("Label") != LABEL or TRANSPORT not in config.get("ProgramArguments", []):
            raise RuntimeError("Existing carrier LaunchDaemon has unexpected ownership or arguments")
        snapshots[PLIST.with_suffix(".plist.before-tailscale")] = PLIST.read_bytes()
    for path, content in snapshots.items():
        if not path.exists() and content:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall", "migrate-to-tailscale"))
    parser.add_argument("--mesh-address", action="append", default=[], help="Verified homelab-ingress Tailscale address; repeat for IPv4 and IPv6")
    args = parser.parse_args()
    if sys.platform != "darwin" or os.geteuid() != 0:
        parser.error("Run this script with sudo on macOS")
    hosts = Path("/etc/hosts")
    original = hosts.read_text()
    desired = hosts_content(original, args.action == "install")
    running = subprocess.run(["launchctl", "print", f"system/{LABEL}"], capture_output=True).returncode == 0
    if args.action == "migrate-to-tailscale":
        migrate_to_tailscale(hosts, args.mesh_address, running)
    elif args.action == "uninstall":
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
    flush_dns()
    print(f"Octelium API carrier {args.action} complete; canonical DNS and TLS verification retained")


if __name__ == "__main__":
    main()
