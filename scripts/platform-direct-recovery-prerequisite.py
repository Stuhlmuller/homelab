#!/usr/bin/env python3
"""Stage a private direct-LAN Talos recovery candidate from read-only probes.

This helper neither issues a certificate nor publishes a platform prerequisite.
Its candidate needs a separate protected, reviewed publisher before maintenance.
"""

import argparse
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
VERSION_TAG = re.compile(r"v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?\Z")
RECEIPT = "direct-recovery.json"
MIN_CERT_LIFETIME = timedelta(hours=24)


def load_platform():
    spec = importlib.util.spec_from_file_location(
        "platform_maintenance", ROOT / "scripts/platform-maintenance.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


platform = load_platform()


class ProbeFailure(ValueError):
    def __init__(self, category, node=None):
        super().__init__(category)
        self.category = category
        self.node = node


def reviewed_context(source_sha):
    """Require the committed helper and platform contract at current main."""
    if not isinstance(source_sha, str) or not SOURCE_SHA.fullmatch(source_sha):
        raise ValueError("invalid reviewed source revision")
    config_path = ROOT / "scripts/config/platform-maintenance.json"
    config = json.loads(platform.require_reviewed_execution_config(config_path, source_sha))
    platform.validate_config(config)
    nodes = config["expectedStart"]["nodes"]
    if (set(nodes) != set(platform.NODES) or
            tuple(nodes[name]["address"] for name in platform.NODES) !=
            platform.ADDRESSES or
            nodes["acer"]["role"] != "control-plane" or
            any(nodes[name]["role"] != "worker" for name in platform.NODES[:-1])):
        raise ValueError("reviewed direct-LAN node addresses differ")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, timeout=15, check=True)
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                            cwd=ROOT, capture_output=True, text=True,
                            timeout=15, check=True)
    if head.stdout.strip() != source_sha or status.stdout.strip():
        raise ValueError("direct-recovery source differs from reviewed commit")
    for relative in ("scripts/platform-direct-recovery-prerequisite.py",
                     "scripts/platform-maintenance.py"):
        committed = subprocess.run(
            ["git", "--no-replace-objects", "show", f"{source_sha}:{relative}"],
            cwd=ROOT, capture_output=True, timeout=15, check=True)
        if committed.stdout != (ROOT / relative).read_bytes():
            raise ValueError("direct-recovery helper differs from reviewed commit")
    main = subprocess.run(
        ["git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
         "refs/heads/main"], cwd=ROOT, capture_output=True, text=True,
        timeout=30, check=True)
    if main.stdout.strip() != f"{source_sha}\trefs/heads/main":
        raise ValueError("reviewed revision is no longer current main")
    return nodes


def private_talosconfig(path):
    if path is None or not path.is_absolute():
        raise ProbeFailure("talosconfig-not-private")
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) != 0o600 or
            not 0 < info.st_size <= 1048576):
        raise ProbeFailure("talosconfig-not-private")
    return path


def run_talos(command, runner, timeout, category, node=None):
    try:
        result = runner(command, capture_output=True, text=True,
                        timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ProbeFailure(category, node) from None
    if (result.returncode != 0 or not isinstance(result.stdout, str) or
            len(result.stdout) > 65536):
        raise ProbeFailure(category, node)
    return result.stdout


def lan_source(address, node, connector):
    """Require a same-subnet source socket to the literal node Talos address."""
    try:
        with connector((address, 50000), timeout=5) as connection:
            source = connection.getsockname()[0]
    except (OSError, TimeoutError):
        raise ProbeFailure("direct-lan-unavailable", node) from None
    try:
        source_ip = ipaddress.IPv4Address(source)
    except ipaddress.AddressValueError:
        raise ProbeFailure("direct-lan-source-invalid", node) from None
    if (source_ip not in ipaddress.IPv4Network("10.1.0.0/24") or
            source == address or source in platform.ADDRESSES):
        raise ProbeFailure("direct-lan-source-invalid", node)
    return source


def client_expiry(output, now):
    try:
        info = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        raise ProbeFailure("talos-client-info-invalid") from None
    if not isinstance(info, dict) or info.get("roles") != ["os:admin"]:
        raise ProbeFailure("talos-client-role-invalid")
    value = info.get("certNotAfter")
    if not isinstance(value, str):
        raise ProbeFailure("talos-client-expiry-invalid")
    try:
        expires = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ProbeFailure("talos-client-expiry-invalid") from None
    if expires.tzinfo is None or expires <= now + MIN_CERT_LIFETIME:
        raise ProbeFailure("talos-client-expiry-too-soon")
    return expires.astimezone(timezone.utc)


def server_version(output, address, node):
    """Reject a client-only success or a response for a different node."""
    sections = re.split(r"(?m)^Server:\s*$", output)
    if len(sections) != 2:
        raise ProbeFailure("talos-server-response-invalid", node)
    server = sections[1]
    addresses = re.findall(r"(?m)^\s*NODE:\s*(\S+)\s*$", server)
    tags = re.findall(r"(?m)^\s*Tag:\s*(\S+)\s*$", server)
    if (addresses != [address] or len(tags) != 1 or
            not VERSION_TAG.fullmatch(tags[0])):
        raise ProbeFailure("talos-server-response-invalid", node)
    return tags[0]


def write_private_json(path, record):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(record, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def stage(source_sha, talosconfig, output_directory, runner=subprocess.run,
          connector=socket.create_connection, now=None, publication_id=None):
    nodes = reviewed_context(source_sha)
    output = platform.private_directory(output_directory)
    receipt = output / RECEIPT
    if receipt.exists() or receipt.is_symlink():
        raise ValueError("direct-recovery candidate already exists")
    talosconfig = private_talosconfig(talosconfig)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("direct-recovery clock is not timezone-aware")
    publication_id = publication_id or secrets.token_hex(16)
    if not re.fullmatch(r"[0-9a-f]{32}", publication_id):
        raise ValueError("invalid direct-recovery publication ID")
    try:
        info = run_talos(
            ["talosctl", "--talosconfig", str(talosconfig), "config", "info",
             "-o", "json"], runner, 15, "talos-client-info-unavailable")
        expires = client_expiry(info, now)
        observed = {}
        local_sources = {}
        for name in platform.NODES:
            address = nodes[name]["address"]
            local_sources[name] = lan_source(address, name, connector)
            output_text = run_talos(
                ["talosctl", "--talosconfig", str(talosconfig),
                 "--endpoints", address, "--nodes", address, "version"],
                runner, 30, "direct-node-unavailable", name)
            observed[name] = server_version(output_text, address, name)
        # No stale candidate is staged if main advances while direct probes run.
        reviewed_context(source_sha)
        if len(set(local_sources.values())) != 1:
            raise ProbeFailure("direct-lan-source-changed")
        candidate = {
            "sourceSha": source_sha, "verified": False,
            "candidateVerified": True,
            "capturedAt": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "publicationId": publication_id,
            "transport": "direct-lan-authenticated-talos",
            "endpoint": "10.1.0.199:50000", "nodes": list(platform.NODES),
            "talosMtls": True,
            "clientRole": "os:admin",
            "clientCertNotAfter": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "serverVersions": observed,
            "lanSourceAddress": next(iter(local_sources.values())),
        }
        write_private_json(receipt, candidate)
        return receipt
    except ProbeFailure as failure:
        # Keep a bounded private category, never raw Talos output or credentials.
        write_private_json(output / f"direct-recovery-{publication_id}-failure.json", {
            "sourceSha": source_sha, "publicationId": publication_id,
            "capturedAt": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "category": failure.category, "node": failure.node,
        })
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--talosconfig", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    original_umask = os.umask(0o077)
    try:
        stage(args.expected_sha, args.talosconfig, args.output_directory)
        print("Private direct-LAN recovery candidate staged; publication remains disabled.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("Direct-LAN recovery candidate failed; inspect private diagnostics. No platform receipt was published.",
              file=sys.stderr)
        return 1
    finally:
        os.umask(original_umask)


if __name__ == "__main__":
    sys.exit(main())
