#!/usr/bin/env bash
set -euo pipefail
case "$#" in
  0) ;;
  1) [[ "$1" == "--require-zero-matches" ]] || { echo 'Usage: scan.sh [--require-zero-matches]' >&2; exit 2; } ;;
  *) echo 'Usage: scan.sh [--require-zero-matches]' >&2; exit 2 ;;
esac
[[ "${GITHUB_ACTIONS:-}" == true && "$(uname -s)" == Linux ]]
: "${RUNNER_TEMP:?GitHub runner temporary directory required}"
umask 077
scratch="$(mktemp -d "${RUNNER_TEMP}/harbor-core-scan.XXXXXX")"
trap 'rm -rf -- "$scratch"' EXIT
docker image inspect --format '{{.Id}}' homelab-harbor-core:build >"$scratch/image-id"
docker save --output "$scratch/image.tar" homelab-harbor-core:build
nix build --out-link "$scratch/grype" --impure --expr '(builtins.getFlake (toString ./.)).inputs.nixpkgs.legacyPackages.x86_64-linux.grype'
printf 'check-for-app-update: false\nmatch-upstream-kernel-headers: true\ndb:\n  cache-dir: %s/db\n  auto-update: true\n' "$scratch" >"$scratch/grype.yaml"
"$scratch/grype/bin/grype" --config "$scratch/grype.yaml" --by-cve \
  --platform linux/amd64 -o json --file "$scratch/report.json" "docker-archive:$scratch/image.tar"
python3 -I scripts/ci/harbor-core-scan-check.py "$scratch/report.json" "$(cat "$scratch/image-id")" "$@"
