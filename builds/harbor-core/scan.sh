#!/usr/bin/env bash
set -euo pipefail
diagnostic_file=''
encrypted_report=''
if [[ "$#" -ge 2 && "$1" == '--encrypted-report' ]]; then
  encrypted_report="$2"
  rm -f -- "$encrypted_report"
  shift 2
fi
if [[ "$#" -ge 2 && "$1" == '--diagnostic-file' ]]; then
  diagnostic_file="$2"
  shift 2
fi
case "$#" in
  0) ;;
  1) [[ "$1" == "--require-zero-matches" ]] || { echo 'Usage: scan.sh [--encrypted-report PATH] [--diagnostic-file PATH] [--require-zero-matches]' >&2; exit 2; } ;;
  *) echo 'Usage: scan.sh [--encrypted-report PATH] [--diagnostic-file PATH] [--require-zero-matches]' >&2; exit 2 ;;
esac
record_stage() {
  if [[ -n "$diagnostic_file" ]]; then
    printf '%s\n' "$1" >"$diagnostic_file"
  fi
}
[[ "${GITHUB_ACTIONS:-}" == true && "$(uname -s)" == Linux ]]
: "${RUNNER_TEMP:?GitHub runner temporary directory required}"
umask 077
scratch="$(mktemp -d "${RUNNER_TEMP}/harbor-core-scan.XXXXXX")"
cleanup() {
  status=$?
  if [[ "$status" -ne 0 && -n "$encrypted_report" && -s "$scratch/report.json" ]]; then
    # Compress the complete report; the encryption helper rejects >1 MiB without truncation.
    if ! gzip -c -- "$scratch/report.json" >"$scratch/report.json.gz" ||
      ! python3 -I scripts/ci/harbor-encrypt-diagnostic.py "$scratch/report.json.gz" \
        "$encrypted_report" >/dev/null 2>&1; then
      rm -f -- "$encrypted_report"
      echo 'Encrypted runtime audit report unavailable; private details withheld.' >&2
    fi
  fi
  rm -rf -- "$scratch"
  exit "$status"
}
trap cleanup EXIT
record_stage image-inspect
docker image inspect --format '{{.Id}}' homelab-harbor-core:build >"$scratch/image-id"
record_stage image-export
docker save --output "$scratch/image.tar" "$(cat "$scratch/image-id")"
record_stage scanner-build
nix build --out-link "$scratch/grype" --impure --expr '(builtins.getFlake (toString ./.)).inputs.nixpkgs.legacyPackages.x86_64-linux.grype'
printf 'check-for-app-update: false\nmatch-upstream-kernel-headers: true\ndb:\n  cache-dir: %s/db\n  auto-update: true\n' "$scratch" >"$scratch/grype.yaml"
record_stage scanner-run
"$scratch/grype/bin/grype" --config "$scratch/grype.yaml" --by-cve \
  --platform linux/amd64 -o json --file "$scratch/report.json" "docker-archive:$scratch/image.tar"
record_stage report-validation
if [[ -n "$diagnostic_file" ]]; then
  python3 -I scripts/ci/harbor-core-scan-check.py --diagnostic-file "$diagnostic_file" \
    --archive "$scratch/image.tar" "$scratch/report.json" "$(cat "$scratch/image-id")" "$@"
else
  python3 -I scripts/ci/harbor-core-scan-check.py --archive "$scratch/image.tar" \
    "$scratch/report.json" "$(cat "$scratch/image-id")" "$@"
fi
