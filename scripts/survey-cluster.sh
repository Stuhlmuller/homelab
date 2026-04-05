#!/usr/bin/env bash
set -euo pipefail

hosts=()
while IFS= read -r host; do
  hosts+=("${host}")
done < <(
  python3 <<'PY'
from pathlib import Path
import re

content = Path("ansible/inventories/production/hosts.yml").read_text().splitlines()

for line in content:
    ip_match = re.match(r"^\s{10}ansible_host:\s*([0-9.]+)\s*$", line)
    if ip_match:
        print(ip_match.group(1))
PY
)

for host in "${hosts[@]}"; do
  echo "=== ${host} ==="
  if ! ping -c 1 -W 1 "${host}" >/dev/null 2>&1; then
    echo "ping: failed"
    continue
  fi

  echo "ping: ok"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "${host}" \
    'hostnamectl --static; systemctl is-active nomad consul docker tailscaled 2>/dev/null || true; echo "---"; nomad node status -self 2>/dev/null || true; echo "---"; consul members 2>/dev/null || true'
  echo
done
