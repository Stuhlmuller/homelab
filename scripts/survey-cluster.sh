#!/usr/bin/env bash
set -euo pipefail

hosts=(10.1.0.200 10.1.0.201 10.1.0.202)

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
