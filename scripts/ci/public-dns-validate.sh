#!/usr/bin/env bash
set -euo pipefail

workflow=.github/workflows/mastodon-public-dns.yml
[[ "$GITHUB_REPOSITORY" == Stuhlmuller/homelab && "$GITHUB_REF" == refs/heads/main ]]
[[ "$GITHUB_EVENT_NAME" == workflow_dispatch && "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$GITHUB_SHA" == "$EXPECTED_SHA" && "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]

cache_policy="$(mktemp)"
trap 'rm -f "$cache_policy"' EXIT
for attempt in 1 2; do
  git fetch --no-tags origin refs/heads/main
  sha="$(git rev-parse FETCH_HEAD)"
  if ! git merge-base --is-ancestor "$GITHUB_SHA" "$sha"; then
    echo "::error::Current main does not descend from the dispatch revision."
    exit 1
  fi
  if ! git diff --quiet "$GITHUB_SHA" "$sha" -- "$workflow" scripts/ci/public-dns-validate.sh; then
    echo "::error::The DNS validation workflow changed. Dispatch from current main."
    exit 1
  fi
  git checkout --detach "$sha"

  git show "$sha:scripts/config/nix-cache.json" >"$cache_policy"
  bash scripts/ci/nix-checks.sh --policy "$cache_policy"
  nix develop --command bash scripts/ci/static-checks.sh --offline-verified

  current="$(git ls-remote --exit-code origin refs/heads/main)"
  if [[ "$current" == "$sha"$'\t'refs/heads/main ]]; then
    printf 'sha=%s\n' "$sha" >>"$GITHUB_OUTPUT"
    exit 0
  fi
  echo "Main advanced during validation attempt $attempt."
done
echo "::error::Main changed during both DNS validation attempts."
exit 1
