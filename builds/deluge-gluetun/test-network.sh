#!/usr/bin/env bash
set -euo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# This disposable container has a private, synthetic network. The test needs
# CAP_SYS_ADMIN for namespaces and kernel WireGuard/nftables for forwarding.
docker run --rm --privileged --user 0:0 --network none --entrypoint python3 \
  -v "$here/test-network.py:/fixture.py:ro" homelab-deluge-vpn:build -B /fixture.py
