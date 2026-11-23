#!/bin/sh
set -eu

socket=/run/tailscale/tailscaled.sock
for _ in $(seq 1 60); do
  if test -S "$socket"; then
    break
  fi
  sleep 1
done
test -S "$socket"

# A saved device reconnects without rereading the signed enrollment key.
for _ in $(seq 1 60); do
  state=$(tailscale --socket="$socket" status --json 2>/dev/null || true)
  if printf '%s' "$state" | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"Running"'; then
    break
  fi
  if printf '%s' "$state" | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"(Stopped|NeedsLogin)"'; then
    set --
    if printf '%s' "$state" | grep -q '"NeedsLogin"'; then
      test -s /var/run/secrets/renovate-registry/auth-key
      set -- --auth-key=file:/var/run/secrets/renovate-registry/auth-key
    fi
    tailscale --socket="$socket" up --timeout=90s \
      --hostname=homelab-harbor-registry \
      --advertise-tags=tag:homelab-harbor-registry \
      --accept-dns=false --accept-routes=false --netfilter-mode=off "$@"
    break
  fi
  sleep 1
done
tailscale --socket="$socket" status --json | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"Running"'
tailscale --socket="$socket" serve --yes --bg --tcp=443 tcp://127.0.0.1:8443
