#!/usr/bin/env bash
set -euo pipefail
test "$#" -eq 0 || { echo 'Usage: build.sh (no arguments)' >&2; exit 2; }
recipe_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
docker build --platform=linux/amd64 --tag homelab-deluge-vpn:build "$recipe_dir"
test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' homelab-deluge-vpn:build)" = linux/amd64
docker run --rm --network none homelab-deluge-vpn:build sh -ec '
    ip -Version
    nft --version
    wg --version
    python3 -B -c "
import ast
from pathlib import Path

for name in (\"network.py\", \"lease.py\", \"health.py\"):
    ast.parse(Path(name).read_text())
"
'
