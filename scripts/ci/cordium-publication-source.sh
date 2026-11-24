#!/usr/bin/env bash
set -euo pipefail

repository="https://github.com/Stuhlmuller/homelab.git"
[[ "${GITHUB_ACTIONS:-}" == true &&
   "${GITHUB_REPOSITORY:-}" == Stuhlmuller/homelab &&
   "${GITHUB_REF:-}" == refs/heads/main &&
   "${GITHUB_WORKFLOW_REF:-}" == Stuhlmuller/homelab/.github/workflows/cordium-runner-publish.yml@refs/heads/main &&
   "${GITHUB_EVENT_NAME:-}" == workflow_dispatch &&
   "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ &&
   "${EXPECTED_SHA:-}" == "$GITHUB_SHA" ]] || {
  echo 'Invalid Cordium publication dispatch context.' >&2
  exit 1
}
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]] || {
  echo 'Cordium publication checkout differs from the dispatch commit.' >&2
  exit 1
}

export GIT_TERMINAL_PROMPT=0
remote_main="$(git ls-remote --exit-code "$repository" refs/heads/main)"
[[ "$remote_main" == "$GITHUB_SHA"$'\t'refs/heads/main ]] && exit 0

# Checkout uses a shallow clone. Fetch ancestry before comparing reviewed trees.
fetch_options=(--no-tags --no-recurse-submodules)
if [[ "$(git rev-parse --is-shallow-repository)" == true ]]; then
  fetch_options+=(--unshallow)
fi
git fetch "${fetch_options[@]}" "$repository" refs/heads/main
current_main="$(git rev-parse --verify 'FETCH_HEAD^{commit}')"
if ! git merge-base --is-ancestor "$GITHUB_SHA" "$current_main"; then
  echo 'The Cordium dispatch commit is no longer an ancestor of main.' >&2
  exit 1
fi
# Compare the complete tree except documentation prose. Keep all workflow,
# build, transport, credentials, and signing inputs in the verification.
if ! git diff --quiet --no-ext-diff --no-textconv --no-renames "$GITHUB_SHA" "$current_main" -- . \
    ':(exclude,top)README.md' ':(exclude,top,glob)docs/**/*.md' ':(exclude,top,glob)openwiki/**/*.md'; then
  echo 'Cordium publication inputs changed after dispatch. Dispatch again from current main.' >&2
  exit 1
fi
printf 'Cordium publication inputs match current main %s. Images remain pinned to %s.\n' "$current_main" "$GITHUB_SHA"
