#!/usr/bin/env bash
set -euo pipefail
test "$#" -eq 0 || { echo "Usage: build.sh (no arguments)" >&2; exit 2; }
recipe_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
build_context="$(mktemp -d "${TMPDIR:-/tmp}/nofx-build.XXXXXX")"
trap 'rm -rf -- "${build_context}"' EXIT
python3 -I "${recipe_dir}/prepare-source.py" "${build_context}"
source_sha="$(cat "${build_context}/homelab-build/revision.txt")"
[[ "${source_sha}" =~ ^[0-9a-f]{40}$ ]]
docker build --label "org.opencontainers.image.revision=${source_sha}" \
  --file "${build_context}/Dockerfile.backend" --tag homelab-nofx-backend:build "${build_context}"
docker build --label "org.opencontainers.image.revision=${source_sha}" \
  --file "${build_context}/Dockerfile.frontend" --tag homelab-nofx-frontend:build "${build_context}"
