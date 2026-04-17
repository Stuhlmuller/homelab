#!/usr/bin/env python3
"""Resolve the Nomad ingress Tailscale IP from the production inventory."""

from pathlib import Path
import re
import sys

INVENTORY_PATH = Path("ansible/inventories/production/hosts.yml")


def record_host(
    tailscale_ip: str | None,
    node_class: str | None,
    ingress_ip: str | None,
    first_nomad_ip: str | None,
) -> tuple[str | None, str | None]:
    if not tailscale_ip:
        return ingress_ip, first_nomad_ip

    if node_class == "ingress" and ingress_ip is None:
        ingress_ip = tailscale_ip

    if node_class and first_nomad_ip is None:
        first_nomad_ip = tailscale_ip

    return ingress_ip, first_nomad_ip


def main() -> int:
    if not INVENTORY_PATH.exists():
        print(f"Inventory file not found: {INVENTORY_PATH}", file=sys.stderr)
        return 1

    lines = INVENTORY_PATH.read_text(encoding="utf-8").splitlines()

    current_tailscale_ip: str | None = None
    current_node_class: str | None = None
    ingress_ip: str | None = None
    first_nomad_ip: str | None = None

    for line in lines:
        if re.match(r"^\s{8}([a-zA-Z0-9-]+):\s*$", line):
            ingress_ip, first_nomad_ip = record_host(
                current_tailscale_ip, current_node_class, ingress_ip, first_nomad_ip
            )
            current_tailscale_ip = None
            current_node_class = None
            continue

        tailscale_match = re.match(r"^\s{10}tailscale_ip:\s*([0-9.]+)\s*$", line)
        if tailscale_match:
            current_tailscale_ip = tailscale_match.group(1)
            continue

        class_match = re.match(r"^\s{10}nomad_node_class:\s*([a-zA-Z0-9_-]+)\s*$", line)
        if class_match:
            current_node_class = class_match.group(1)

    ingress_ip, first_nomad_ip = record_host(
        current_tailscale_ip, current_node_class, ingress_ip, first_nomad_ip
    )

    selected = ingress_ip or first_nomad_ip
    if not selected:
        print("Unable to resolve a Nomad Tailscale endpoint from inventory.", file=sys.stderr)
        return 1

    print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
