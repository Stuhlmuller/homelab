#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo 'Usage: build-operator.sh (no arguments)' >&2; exit 2; }
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo 'Operator image build requires a Linux amd64 runner.' >&2
  exit 1
}

cd "$(dirname "$0")/../.."
source_sha="$(git rev-parse HEAD)"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ && -z "$(git status --porcelain)" ]] || {
  echo 'Operator image requires a clean reviewed checkout.' >&2
  exit 1
}
context="$(mktemp -d "${TMPDIR:-/tmp}/oce-operator-build.XXXXXX")"
trap 'rm -rf -- "$context"' EXIT
mkdir -p "$context/bin" "$context/scripts" \
  "$context/clusters/homelab/apps/openclaw-enterprise"
cp -L "$(command -v kubectl)" "$context/bin/kubectl"
cp -L "$(command -v yq)" "$context/bin/yq"
cp scripts/openclaw-enterprise.py "$context/scripts/openclaw-enterprise.py"
cp clusters/homelab/apps/openclaw-enterprise/installation.yaml \
  clusters/homelab/apps/openclaw-enterprise/values.yaml \
  "$context/clusters/homelab/apps/openclaw-enterprise/"
printf '%s\n' "$source_sha" >"$context/operator-source.sha"

docker buildx build --load --platform linux/amd64 \
  --file "$PWD/builds/openclaw-enterprise/operator.Dockerfile" \
  --label "org.opencontainers.image.revision=$source_sha" \
  --tag homelab-oce-operator:build "$context"
[[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    homelab-oce-operator:build)" == "$source_sha" ]]
[[ "$(docker run --rm --network none --read-only --user 10001:10001 \
    --entrypoint cat homelab-oce-operator:build /opt/homelab/operator-source.sha)" == "$source_sha" ]]
docker run --rm --network none --read-only --user 10001:10001 \
  homelab-oce-operator:build --help >/dev/null
docker run --rm --network none --read-only --user 10001:10001 \
  --entrypoint kubectl homelab-oce-operator:build version --client --output=json >/dev/null
docker run --rm --network none --read-only --user 10001:10001 \
  --entrypoint yq homelab-oce-operator:build --version >/dev/null
