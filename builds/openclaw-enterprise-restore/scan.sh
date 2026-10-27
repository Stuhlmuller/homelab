#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo 'Usage: scan.sh (no arguments)' >&2; exit 2; }
[[ "${GITHUB_ACTIONS:-}" == true && "$(uname -s)" == Linux ]]
: "${RUNNER_TEMP:?GitHub runner temporary directory required}"
: "${GITHUB_OUTPUT:?GitHub output required}"
umask 077
scratch="$(mktemp -d "${RUNNER_TEMP}/oce-restore-scan.XXXXXX")"
trap 'rm -rf -- "$scratch"' EXIT
image_id="$(docker image inspect --format '{{.Id}}' homelab-oce-restore:build)"
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
docker save --output "$scratch/image.tar" "$image_id"
nix build --out-link "$scratch/grype" --impure --expr \
  '(builtins.getFlake (toString ./.)).inputs.nixpkgs.legacyPackages.x86_64-linux.grype'
printf 'check-for-app-update: false\nmatch-upstream-kernel-headers: true\ndb:\n  cache-dir: %s/db\n  auto-update: true\n' "$scratch" >"$scratch/grype.yaml"
"$scratch/grype/bin/grype" --config "$scratch/grype.yaml" --by-cve \
  --platform linux/amd64 -o json --file "$scratch/report.json" "docker-archive:$scratch/image.tar"
python3 -I scripts/ci/harbor-core-scan-check.py --expected-distro debian:12 \
  --archive "$scratch/image.tar" "$scratch/report.json" "$image_id"
[[ "$(docker image inspect --format '{{.Id}}' homelab-oce-restore:build)" == "$image_id" ]]
printf 'restore_image_id=%s\n' "$image_id" >>"$GITHUB_OUTPUT"
