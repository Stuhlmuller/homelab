#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo 'Usage: build.sh (no arguments)' >&2; exit 2; }

cd "$(dirname "$0")/../.."
source_contract=builds/openclaw-enterprise/source.json
revision="$(jq -er '.revision | select(test("^[0-9a-f]{40}$"))' "$source_contract")"
expected_hash="$(jq -er '.archiveSha256 | select(test("^[0-9a-f]{64}$"))' "$source_contract")"
node_base="$(jq -er '.nodeBaseImage | select(test("^docker.io/library/node:24-bookworm@sha256:[0-9a-f]{64}$"))' "$source_contract")"
[[ "$(jq -er '.source.revision' scripts/config/openclaw-enterprise.json)" == "$revision" ]]
[[ "$(jq -er '.source.cli.buildRevision' scripts/config/openclaw-enterprise.json)" == "$revision" ]]
[[ "$(jq -er '.source.images.controller.repository' scripts/config/openclaw-enterprise.json)" == harbor.stinkyboi.com/homelab/homelab-oce-controller ]]
[[ "$(jq -er '.source.images.runtime.repository' scripts/config/openclaw-enterprise.json)" == harbor.stinkyboi.com/homelab/homelab-oce-runtime ]]

context="$(mktemp -d "${TMPDIR:-/tmp}/oce-build.XXXXXX")"
trap 'rm -rf -- "$context"' EXIT
curl --fail --location --silent --show-error \
  "https://codeload.github.com/openclaw/openclaw-enterprise/tar.gz/$revision" \
  --output "$context/source.tar.gz"
printf '%s  %s\n' "$expected_hash" "$context/source.tar.gz" | sha256sum --check --strict --status
mkdir "$context/source"
tar -xzf "$context/source.tar.gz" -C "$context/source" --strip-components=1
rm "$context/source.tar.gz"
cd "$context/source"

docker buildx build --load --platform linux/amd64 --target runtime \
  --build-arg "NODE_BASE_IMAGE=$node_base" \
  --build-arg "OCC_BUILD_REVISION=$revision" \
  --label "org.opencontainers.image.revision=$revision" \
  --tag homelab-oce-controller:build .
docker buildx build --load --platform linux/amd64 \
  --build-arg "NODE_BASE_IMAGE=$node_base" \
  --build-arg "OCC_BUILD_REVISION=$revision" \
  --file deploy/runtime/Dockerfile \
  --tag homelab-oce-runtime:build .
for image in homelab-oce-controller homelab-oce-runtime; do
  [[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image:build")" == "$revision" ]]
done
