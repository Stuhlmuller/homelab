#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo 'Usage: build.sh (no arguments)' >&2; exit 2; }
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo 'Restore image build requires a Linux amd64 runner.' >&2
  exit 1
}

cd "$(dirname "$0")/../.."
source_sha="$(git rev-parse HEAD)"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ && -z "$(git status --porcelain)" &&
   "${GITHUB_SHA:-$source_sha}" == "$source_sha" ]] || {
  echo 'Restore image requires a clean reviewed checkout.' >&2
  exit 1
}
base='docker.io/library/postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c'
[[ "$(sed -n 's/^FROM --platform=linux\/amd64 //p' builds/openclaw-enterprise-restore/Dockerfile)" == "$base" ]]
jq -e --arg source "$base" 'any(.images[]; .source == $source)' \
  scripts/config/harbor-images.json >/dev/null

docker buildx build --load --platform linux/amd64 \
  --file builds/openclaw-enterprise-restore/Dockerfile \
  --label "org.opencontainers.image.revision=$source_sha" \
  --tag homelab-oce-restore:build .
[[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    homelab-oce-restore:build)" == "$source_sha" ]]
run=(docker run --rm --network none --read-only --user 999:999)
[[ "$("${run[@]}" --entrypoint age homelab-oce-restore:build --version)" == v1.3.1 ]]
"${run[@]}" --entrypoint python3 homelab-oce-restore:build --version >/dev/null
"${run[@]}" --entrypoint jq homelab-oce-restore:build --version >/dev/null
"${run[@]}" --entrypoint mountpoint homelab-oce-restore:build --version >/dev/null
"${run[@]}" --entrypoint pg_restore homelab-oce-restore:build --version >/dev/null
"${run[@]}" --entrypoint pg_dump homelab-oce-restore:build --version >/dev/null
source_hash="$(sha256sum builds/openclaw-enterprise-restore/safe-extract.py | cut -d ' ' -f 1)"
image_hash="$("${run[@]}" --entrypoint sha256sum homelab-oce-restore:build \
  /usr/local/libexec/occ-safe-extract.py | cut -d ' ' -f 1)"
[[ "$source_hash" == "$image_hash" ]]
