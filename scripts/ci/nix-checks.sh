#!/usr/bin/env bash
set -euo pipefail

policy=scripts/config/nix-cache.json
case "${1:-}" in
  --policy) policy="$2"; shift 2 ;;
esac
[[ $# == 0 ]] || { echo 'Usage: nix-checks.sh [--policy FILE]' >&2; exit 2; }

cache="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["url"])' "$policy")"
key="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["publicKey"])' "$policy")"
system="$(nix eval --impure --raw --expr builtins.currentSystem)"

# The policy comes from the protected base in CI, never from the PR's key list.
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
status=0
build_checks() {
  nix build --print-build-logs --no-link --print-out-paths --no-update-lock-file \
    --option sandbox true --option require-sigs true \
    --option extra-substituters "$cache" --option extra-trusted-public-keys "$key" \
    --option narinfo-cache-negative-ttl 0 "$@" 2>>"$log"
}
# Conftest's verification has an evaluation deadline. Keep its derivation
# separate from the CPU-heavy offline fixture suite on small CI runners.
build_checks ".#checks.${system}.manifest-policy" || status=$?
if ((status == 0)); then
  build_checks ".#checks.${system}.offline-tests" \
    ".#checks.${system}.openwiki-setup" || status=$?
fi
cat "$log" >&2
if grep -Eq 'ignoring (the client-specified setting|untrusted substituter)' "$log"; then
  echo 'Nix daemon rejected cache/sandbox policy. Use a trusted builder; these results are not publishable.' >&2
  exit 1
fi
exit "$status"
