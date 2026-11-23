#!/usr/bin/env bash
set -euo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fixture="$(mktemp -d)"
trap 'rm -rf -- "$fixture"' EXIT
openssl req -x509 -newkey rsa:2048 -noenc -days 1 -sha256 \
  -subj /CN=deluge-vpn-fixture \
  -addext 'subjectAltName=DNS:cloudflare-dns.com,DNS:dns.google' \
  -keyout "$fixture/key.pem" -out "$fixture/cert.pem" 2>/dev/null

# Namespace creation and packet capture need privilege inside this disposable
# container. Network none keeps the simulated internet entirely off the host.
docker run --rm --privileged --user 0:0 --network none --entrypoint python3 \
  -v "$here/test-network.py:/fixture.py:ro" -v "$fixture:/tls:ro" \
  homelab-deluge-vpn:build -B /fixture.py
