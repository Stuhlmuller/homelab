#!/usr/bin/env bash
set -euo pipefail

[[ "${GITHUB_ACTIONS:-}" == true ]] || exit 0

if [[ "${GITHUB_REF:-}" != refs/heads/main ||
  "${GITHUB_REPOSITORY:-}" != Stuhlmuller/homelab ||
  ! "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid production commit context; refusing to change live state." >&2
  exit 1
fi

if ! current_main="$(GIT_TERMINAL_PROMPT=0 git ls-remote --exit-code \
  "https://github.com/${GITHUB_REPOSITORY}.git" refs/heads/main 2>/dev/null)"; then
  echo "Unable to verify current main; refusing to change live state." >&2
  exit 1
fi

if [[ "$current_main" != "${GITHUB_SHA}"$'\t'refs/heads/main ]]; then
  echo "Main advanced after dispatch; refusing to change live state." >&2
  exit 1
fi
