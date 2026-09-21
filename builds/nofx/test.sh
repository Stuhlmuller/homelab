#!/usr/bin/env bash
set -euo pipefail
test "$#" -eq 0 || { echo "Usage: test.sh (no arguments)" >&2; exit 2; }
recipe_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
build_context="$(mktemp -d "${TMPDIR:-/tmp}/nofx-tests.XXXXXX")"
trap 'rm -rf -- "${build_context}"' EXIT
python3 -I "${recipe_dir}/prepare-source.py" "${build_context}"
docker build --target tests --file "${build_context}/Dockerfile.backend" "${build_context}"
docker build --target tests --file "${build_context}/Dockerfile.frontend" "${build_context}"
