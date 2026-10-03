#!/usr/bin/env python3
"""Synthetic-only Linux network namespace check. Accepts no production inputs."""

import argparse
import errno
import json
import os
import socket
import subprocess
import sys
from pathlib import Path


def inside(parent_namespace):
    if os.readlink("/proc/self/ns/net") == parent_namespace:
        raise RuntimeError("Still in the parent network namespace")
    interfaces = [name for _, name in socket.if_nameindex()]
    if interfaces != ["lo"]:
        raise RuntimeError("Unexpected interface: " + str(interfaces))
    # An isolated, down loopback namespace has no path even to a local node.
    results = []
    for family, address in [
        (socket.AF_INET, ("10.1.0.199", 6443)),
        (socket.AF_INET, ("10.1.0.2", 443)),
        (socket.AF_INET, ("1.1.1.1", 443)),
        (socket.AF_INET6, ("2606:4700:4700::1111", 443)),
    ]:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            try:
                s.connect(address)
            except OSError as e:
                if e.errno not in (errno.ENETUNREACH, errno.EHOSTUNREACH):
                    raise RuntimeError(
                        "Unexpected result, not proof of no route"
                    ) from e
                results.append({"address": address[0], "result": "no-route"})
            else:
                raise RuntimeError("Network unexpectedly reachable")
    print(
        json.dumps(
            {"interfaces": interfaces, "checks": results, "scope": "synthetic-only"}
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inside-parent-namespace")
    args = p.parse_args()
    if args.inside_parent_namespace:
        inside(args.inside_parent_namespace)
    else:
        # close_fds prevents a preconnected network socket from crossing the boundary.
        # This does not mount/isolate files and must never process real archives.
        subprocess.run(
            [
                "unshare",
                "--user",
                "--map-root-user",
                "--net",
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--inside-parent-namespace",
                os.readlink("/proc/self/ns/net"),
            ],
            check=True,
            timeout=20,
            close_fds=True,
        )


if __name__ == "__main__":
    main()
