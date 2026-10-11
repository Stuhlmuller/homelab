#!/usr/bin/env bash
set -euo pipefail
test "$#" -eq 0 || { echo 'Usage: build.sh (no arguments)' >&2; exit 2; }
recipe_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
context="$(mktemp -d "${TMPDIR:-/tmp}/harbor-core-build.XXXXXX")"
trap 'rm -rf -- "$context"' EXIT
python3 -I "$recipe_dir/prepare-source.py" "$context"
docker build --platform=linux/amd64 --file "$context/Dockerfile" \
  --tag homelab-harbor-core:build "$context"
test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' homelab-harbor-core:build)" = linux/amd64
python3 -I "$recipe_dir/registry-test.py" "$context"
