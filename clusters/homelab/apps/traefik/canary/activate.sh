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
# A restored state reconnects without consuming the enrollment key again.
# Only a new or expired device identity enters NeedsLogin and uses the key.
for _ in $(seq 1 60); do
  state=$(tailscale --socket="$socket" status --json 2>/dev/null || true)
  if printf '%s' "$state" | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"Running"'; then
    break
  fi
  if printf '%s' "$state" | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"Stopped"'; then
    tailscale --socket="$socket" up --timeout=90s \
      --hostname=homelab-ingress-canary \
      --advertise-tags=tag:homelab-ingress-canary \
      --accept-dns=false \
      --netfilter-mode=off
    break
  fi
  if printf '%s' "$state" | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"NeedsLogin"'; then
    test -s /var/run/secrets/tailscale-auth/auth-key
    tailscale --socket="$socket" up --timeout=90s \
      --auth-key=file:/var/run/secrets/tailscale-auth/auth-key \
      --hostname=homelab-ingress-canary \
      --advertise-tags=tag:homelab-ingress-canary \
      --accept-dns=false \
      --netfilter-mode=off
    break
  fi
  sleep 1
done
tailscale --socket="$socket" status --json | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"Running"'
tailscale --socket="$socket" serve --yes --bg --tcp=443 tcp://127.0.0.1:8443
