#!/usr/bin/env python3
"""Check the joined node's key-scoped identity without printing status data."""
import argparse
import json
import subprocess
import sys


TAILNET = "tail67beb.ts.net"


def matches(status, identity):
    if not isinstance(status, dict):
        return False
    node = status.get("Self")
    tailnet = status.get("CurrentTailnet")
    return (
        status.get("BackendState") == "Running"
        and isinstance(node, dict)
        and node.get("Online") is True
        and node.get("Tags") == [f"tag:homelab-ci-{identity}"]
        and isinstance(tailnet, dict)
        and tailnet.get("MagicDNSSuffix") == TAILNET
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identity", choices=("plan", "apply", "cordium"))
    args = parser.parse_args(argv)
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"], capture_output=True, text=True,
            check=True, timeout=20,
        )
        if not matches(json.loads(result.stdout), args.identity):
            raise ValueError("unexpected identity")
    except (OSError, subprocess.SubprocessError, ValueError):
        print("Tailscale identity verification failed; status output withheld.", file=sys.stderr)
        return 1
    print(f"Tailscale {args.identity} identity verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
