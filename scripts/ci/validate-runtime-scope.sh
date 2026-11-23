#!/usr/bin/env bash
set -euo pipefail

base_sha="${1:?pass the pull request base SHA}"
[[ "$base_sha" =~ ^[0-9a-f]{40}$ ]]

changed_paths="$(mktemp)"
trap 'rm -f "$changed_paths"' EXIT
# Include both ends of renames so moving an input out of scope also runs its check.
git diff --name-only --no-renames -z "$base_sha" HEAD >"$changed_paths"

image_policy=false
network_policy=false
harbor_core=false
while IFS= read -r -d '' path; do
  case "$path" in
    .github/workflows/validate.yml|flake.nix|flake.lock|scripts/ci/validate-runtime-scope.sh)
      image_policy=true
      network_policy=true
      harbor_core=true
      ;;
    clusters/homelab/platform/image-policy/*|scripts/ci/image-policy-check.py)
      image_policy=true
      ;;
    clusters/homelab/platform/network-policy*|clusters/homelab/platform/cilium/*|scripts/ci/network-policy-*|scripts/ci/fixtures/network-policy-*)
      network_policy=true
      ;;
    .github/workflows/harbor-core-images.yml|builds/harbor-core/*|scripts/ci/harbor-core-*|scripts/ci/harbor-encrypt-diagnostic*)
      harbor_core=true
      ;;
  esac
done <"$changed_paths"

printf 'image-policy=%s\nnetwork-policy=%s\nharbor-core=%s\n' \
  "$image_policy" "$network_policy" "$harbor_core" >>"$GITHUB_OUTPUT"
