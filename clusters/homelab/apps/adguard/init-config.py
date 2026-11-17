#!/usr/bin/env python3
"""Reconstruct the writable config from the mounted, bcrypt-only secret."""
import argparse
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile

PRIVATE_DNS = "tailnet-dns.tailnet-dns.svc.cluster.local"
UPSTREAMS = ["1.1.1.2", "1.0.0.2", "[/stinkyboi.com/]PRIVATE_DNS_IP"]


def prepare_config(source, resolver=socket.getaddrinfo):
    config = copy.deepcopy(source)
    if type(config.get("schema_version")) is not int or config["schema_version"] != 34:
        raise ValueError("Unsupported configuration schema")
    users = config.get("users")
    if (not isinstance(users, list) or len(users) != 1
            or not isinstance(users[0], dict) or users[0].get("name") != "admin"):
        raise ValueError("Exactly one administrator is required")
    password = users[0].get("password", "")
    if not isinstance(password, str):
        raise ValueError("A bcrypt string is required")
    match = re.fullmatch(r"\$2[aby]\$(\d{2})\$[./A-Za-z0-9]{53}", password)
    if not match or not 4 <= int(match[1]) <= 31:
        raise ValueError("A nonempty bcrypt hash is required")
    if config.get("dns", {}).get("upstream_dns") != UPSTREAMS:
        raise ValueError("Unexpected upstream configuration")
    answers = resolver(PRIVATE_DNS, 53, socket.AF_INET, socket.SOCK_DGRAM)
    addresses = {ipaddress.ip_address(answer[4][0]) for answer in answers}
    if len(addresses) != 1:
        raise ValueError("Private resolver must have exactly one IPv4 address")
    address, = addresses
    if (address.version != 4 or not address.is_private or address.is_loopback
            or address.is_link_local or address.is_unspecified or address.is_multicast or address.is_reserved):
        raise ValueError("Invalid private resolver address")
    config["dns"]["upstream_dns"][-1] = f"[/stinkyboi.com/]{address}"
    return config


def initialize(source, destination, resolver=socket.getaddrinfo):
    config = prepare_config(json.loads(Path(source).read_text()), resolver)
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            json.dump(config, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="/run/secrets/adguard/config.json")
    parser.add_argument("--destination", default="/config/AdGuardHome.yaml")
    args = parser.parse_args()
    try:
        initialize(args.source, args.destination)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("AdGuard configuration initialization failed; secret contents withheld", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
