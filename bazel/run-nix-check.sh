#!/bin/sh
set -eu

{
    IFS= read -r nix
    IFS= read -r derivation
    IFS= read -r cache_url
    IFS= read -r cache_key
} < "@RECIPE@"

log="$(mktemp)"
trap 'rm -f "$log"' EXIT
status=0
"$nix" --extra-experimental-features nix-command build "${derivation}^out" --print-build-logs --no-link --max-jobs 2 \
    --option sandbox true --option require-sigs true \
    --option extra-substituters "$cache_url" --option extra-trusted-public-keys "$cache_key" \
    --option narinfo-cache-negative-ttl 0 2>"$log" || status=$?
if grep -Eq 'ignoring (the client-specified setting|untrusted substituter)' "$log"; then
    cat "$log" >&2
    echo 'Nix daemon rejected cache/sandbox policy.' >&2
    exit 1
fi
if [ "$status" -ne 0 ]; then
    cat "$log" >&2
fi
exit "$status"
