#!/usr/bin/env bash
set -euo pipefail

allowed_signers_file="${ALLOWED_SIGNERS_FILE:-.github/allowed_signers}"
expected_fingerprint="${EXPECTED_SIGNING_KEY_FINGERPRINT:-SHA256:aEGjgIntjDt20o2jFQdaHHEzDEYq5Vcm3oJ5qOFhFpA}"
base_sha="${BASE_SHA:-}"
head_sha="${HEAD_SHA:-HEAD}"

if [[ ! -f "$allowed_signers_file" ]]; then
  echo "Allowed signers file not found: ${allowed_signers_file}" >&2
  exit 1
fi

if [[ -z "$base_sha" ]]; then
  if [[ -n "${GITHUB_BASE_REF:-}" ]]; then
    git fetch --no-tags --prune --depth=1 origin "${GITHUB_BASE_REF}:refs/remotes/origin/${GITHUB_BASE_REF}"
    base_sha="$(git merge-base HEAD "origin/${GITHUB_BASE_REF}")"
  else
    echo "BASE_SHA must be set when GITHUB_BASE_REF is unavailable." >&2
    exit 1
  fi
fi

ensure_commit_available() {
  local commit_sha="$1"

  if git cat-file -e "${commit_sha}^{commit}" 2>/dev/null; then
    return
  fi

  git fetch --no-tags --depth=1 origin "$commit_sha"
}

ensure_commit_available "$base_sha"
ensure_commit_available "$head_sha"

mapfile -t commits < <(git rev-list --reverse "${base_sha}..${head_sha}")

if [[ "${#commits[@]}" -eq 0 ]]; then
  echo "No commits to verify in ${base_sha}..${head_sha}."
  exit 0
fi

for commit_sha in "${commits[@]}"; do
  if ! verify_output="$(
    git \
      -c gpg.format=ssh \
      -c "gpg.ssh.allowedSignersFile=${allowed_signers_file}" \
      verify-commit --raw "$commit_sha" 2>&1
  )"; then
    echo "Commit ${commit_sha} is not signed by the required key." >&2
    printf '%s\n' "$verify_output" >&2
    exit 1
  fi

  if [[ "$verify_output" != *"$expected_fingerprint"* ]]; then
    echo "Commit ${commit_sha} was signed by a different key." >&2
    echo "Expected signing key fingerprint: ${expected_fingerprint}" >&2
    printf '%s\n' "$verify_output" >&2
    exit 1
  fi

  echo "Verified ${commit_sha} with ${expected_fingerprint}."
done
