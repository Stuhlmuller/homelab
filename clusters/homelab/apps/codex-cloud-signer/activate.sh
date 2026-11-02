#!/bin/sh
set -eu
socket=/run/tailscale/tailscaled.sock
for _ in $(seq 1 90); do
  state=$(tailscale --socket="$socket" status --json 2>/dev/null || true)
  if printf '%s' "$state" | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"Running"'; then
    exit 0
  fi
  if printf '%s' "$state" | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"(NeedsLogin|Stopped)"'; then
    exec tailscale --socket="$socket" up --timeout=90s \
      --auth-key=file:/auth/auth-key --hostname=codex-cloud-signer \
      --advertise-tags=tag:codex-cloud-signer --accept-dns=false --netfilter-mode=off
  fi
  sleep 1
done
exit 1
