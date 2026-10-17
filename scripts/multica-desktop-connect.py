#!/usr/bin/env python3
"""Migrate the current macOS Multica profile from Octelium to the Tailscale mesh."""
import argparse
import http.client
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import plistlib
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

API = "https://multica.stinkyboi.com"
LABEL = "com.stuhlmuller.multica-octelium"
TAILNET = "tail67beb.ts.net"
INGRESS = "homelab-ingress." + TAILNET
TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
CARRIER_PATH = Path(__file__).with_name("octelium-macos-api-carrier.py")


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=45).stdout


def mesh_addresses(resume=False):
    def status():
        return json.loads(run(TAILSCALE, "status", "--json"))
    before = status()
    own = before.get("Self", {})
    if (before.get("CurrentTailnet", {}).get("MagicDNSSuffix") != TAILNET
            or not own.get("ID") or not own.get("UserID") or not own.get("TailscaleIPs")
            or own.get("Expired") or before.get("AuthURL")):
        raise RuntimeError("An existing authenticated homelab Tailscale profile is required")
    reconnecting = before.get("BackendState") == "Stopped" and resume
    if reconnecting:
        # No flags: reconnect the current profile without changing saved preferences.
        run(TAILSCALE, "up")
    after = status()
    # The macOS CLI can return before its network extension finishes connecting.
    for _ in range(20):
        if not reconnecting or (after.get("BackendState") == "Running" and after.get("Self", {}).get("Online")):
            break
        if (after.get("Self", {}).get("ID") != own["ID"]
                or after.get("Self", {}).get("UserID") != own["UserID"]
                or after.get("CurrentTailnet", {}).get("MagicDNSSuffix") != TAILNET):
            break
        time.sleep(0.5)
        after = status()
    if (after.get("BackendState") != "Running" or not after.get("Self", {}).get("Online")
            or after.get("Self", {}).get("ID") != own["ID"]
            or after.get("Self", {}).get("UserID") != own["UserID"]
            or after.get("CurrentTailnet", {}).get("MagicDNSSuffix") != TAILNET):
        raise RuntimeError("The existing Tailscale profile must be online; use --resume-tailscale if stopped")
    peers = [peer for peer in after.get("Peer", {}).values()
             if peer.get("DNSName", "").rstrip(".") == INGRESS and peer.get("Online")]
    if len(peers) != 1:
        raise RuntimeError("The declared homelab-ingress Tailscale peer is not uniquely online")
    addresses = {str(ipaddress.ip_address(value)) for value in peers[0].get("TailscaleIPs", [])}
    carrier = carrier_module()
    if not addresses or any(not carrier.is_mesh_address(value) for value in addresses):
        raise RuntimeError("The ingress peer has no valid Tailscale addresses")
    return sorted(addresses, key=lambda value: (ipaddress.ip_address(value).version, value))


def authenticated_ready(addresses, token, user_id):
    host = urlsplit(API).hostname
    resolved = {str(ipaddress.ip_address(item[4][0])) for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    if not resolved or not resolved.issubset(set(addresses)):
        raise RuntimeError("Canonical Multica DNS must resolve only to the declared mesh ingress addresses")
    if not isinstance(token, str) or not token:
        raise RuntimeError("The current Desktop profile has no saved token; authenticate before migrating")
    # Pin the checked mesh IP while retaining canonical SNI and normal CA validation.
    connection = http.client.HTTPSConnection(host, timeout=10, context=ssl.create_default_context())
    address = next(value for value in addresses if value in resolved)
    connection._create_connection = lambda _target, timeout, *_args: socket.create_connection((address, 443), timeout)
    try:
        connection.request("GET", "/api/me", headers={"Authorization": "Bearer " + token})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError("Canonical Multica authentication failed; local configuration is unchanged")
        identity = json.loads(response.read(65536))
        if str(identity.get("id")) != user_id:
            raise RuntimeError("Canonical Multica returned a different user; local configuration is unchanged")
    finally:
        connection.close()


def atomic_write(path, content):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def backup(path):
    destination = path.with_name(path.name + ".before-tailscale")
    if path.is_file() and not destination.exists():
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(path.read_bytes())


def carrier_module():
    spec = importlib.util.spec_from_file_location("carrier", CARRIER_PATH)
    carrier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(carrier)
    return carrier


def migrate(home, addresses):
    profile = home / ".multica"
    desktop = profile / "desktop.json"
    config = json.loads(desktop.read_text())
    previous_api = config.get("apiUrl")
    if previous_api not in ("http://127.0.0.1:18080", "http://multica", API):
        raise RuntimeError("Refusing to change an unrecognized Desktop endpoint")
    source = profile / "profiles" / ("desktop-" + urlsplit(previous_api).netloc.replace(":", "-").lower())
    target = profile / "profiles" / "desktop-multica.stinkyboi.com"
    credentials = json.loads((source / "config.json").read_text())
    if credentials.get("server_url") != previous_api:
        raise RuntimeError("Current Desktop profile does not match its configured endpoint")
    desired = dict(credentials, server_url=API)
    current = json.loads((target / "config.json").read_text()) if (target / "config.json").exists() else {}
    if current.get("server_url", API) != API:
        raise RuntimeError("Canonical profile has an unexpected endpoint")
    if current.get("token") and current["token"] != credentials.get("token"):
        raise RuntimeError("Canonical profile already holds a different token; refusing to overwrite it")
    if any(key not in desired or desired[key] != value for key, value in current.items() if key != "server_url"):
        raise RuntimeError("Canonical profile has conflicting settings; refusing to overwrite it")
    marker = source / ".desktop-user-id"
    if not marker.is_file() or not marker.read_text().strip():
        raise RuntimeError("The current Desktop user marker is missing")
    target_marker = target / marker.name
    if target_marker.exists() and target_marker.read_bytes() != marker.read_bytes():
        raise RuntimeError("Canonical profile belongs to a different Desktop user")
    plist = home / "Library/LaunchAgents" / (LABEL + ".plist")
    runner = profile / "octelium-client.py"
    if plist.exists():
        launch = plistlib.loads(plist.read_bytes())
        arguments = launch.get("ProgramArguments", [])
        if launch.get("Label") != LABEL or str(runner) not in arguments or "--supervise" not in arguments:
            raise RuntimeError("The old LaunchAgent has unexpected ownership or arguments")
    if runner.exists() and LABEL not in runner.read_text():
        raise RuntimeError("The old supervisor has unexpected contents")
    authenticated_ready(addresses, credentials.get("token"), marker.read_text().strip())
    carrier = carrier_module()
    if not all(carrier.probe(protocol, addresses[0]) for protocol in ("application/grpc", "application/grpc-web+proto")):
        raise RuntimeError("Canonical Octelium API TLS/gRPC over the mesh is not ready")
    if carrier.PLIST.exists() or carrier.MARKER in Path("/etc/hosts").read_text():
        # Complete the reversible privileged cutover before retiring the user transport.
        subprocess.run(["sudo", sys.executable, "-I", str(CARRIER_PATH), "migrate-to-tailscale",
                        *[item for address in addresses for item in ("--mesh-address", address)]], check=True)
    for path in (desktop, target / "config.json", target_marker, plist, runner):
        backup(path)
    atomic_write(target / "config.json", (json.dumps(desired, indent=2) + "\n").encode())
    atomic_write(target_marker, marker.read_bytes())
    config.update(apiUrl=API, wsUrl="wss://multica.stinkyboi.com/ws")
    atomic_write(desktop, (json.dumps(config, indent=2) + "\n").encode())
    job = f"gui/{os.getuid()}/{LABEL}"
    if subprocess.run(["launchctl", "print", job], capture_output=True, check=False).returncode == 0:
        run("launchctl", "bootout", job)
    plist.unlink(missing_ok=True)
    runner.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume-tailscale", action="store_true", help="Reconnect the existing homelab app profile if stopped, then migrate Desktop")
    mode.add_argument("--resume-only", action="store_true", help="Reconnect the saved homelab profile and verify ingress; keep Desktop and carrier unchanged")
    args = parser.parse_args()
    if sys.platform != "darwin" or os.geteuid() == 0:
        parser.error("Run as the signed-in macOS user, without sudo")
    addresses = mesh_addresses(args.resume_tailscale or args.resume_only)
    if args.resume_only:
        print("Existing Tailscale profile and ingress are online; Desktop and carrier are unchanged.")
        return
    migrate(Path.home(), addresses)
    print("Multica now uses the mesh endpoint; token and user marker preserved. Restart Multica to load it.")


if __name__ == "__main__":
    main()
