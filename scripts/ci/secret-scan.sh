#!/usr/bin/env bash
set -euo pipefail

scan_paths=(
  .agents
  .github
  .talos
  IaC
  clusters
  docs
  policy
  scripts
  AGENTS.md
  ONBOARDING.md
  README.md
  flake.nix
  renovate.json
)

existing_scan_paths=()
for path in "${scan_paths[@]}"; do
  if [[ -e "$path" ]]; then
    existing_scan_paths+=("$path")
  fi
done

if ((${#existing_scan_paths[@]} == 0)); then
  echo "No repository paths were available for secret scanning." >&2
  exit 1
fi

echo "::group::Explicit secret marker scan"
secret_matches="$(
  rg -n -I \
    -e '-----BEGIN (RSA |EC |OPENSSH |DSA |PRIVATE )?PRIVATE KEY-----' \
    -e '-----BEGIN CERTIFICATE-----' \
    -e 'AGE-SECRET-KEY-' \
    -e 'AKIA[0-9A-Z]{16}' \
    -e 'ASIA[0-9A-Z]{16}' \
    -e 'github_pat_[0-9A-Za-z_]{20,}' \
    -e 'gh[pousr]_[0-9A-Za-z_]{20,}' \
    -e 'xox[baprs]-[0-9A-Za-z-]+' \
    -e 'tskey-[0-9A-Za-z_-]+' \
    -e 'client-key-data:' \
    -e 'client-certificate-data:' \
    -e 'certificate-authority-data:' \
    -e 'id_rsa' \
    -e 'id_ed25519' \
    "${existing_scan_paths[@]}" \
    --glob '!**/.terraform.lock.hcl' \
    --glob '!**/flake.lock' \
    --glob '!**/.terragrunt-cache/**' \
    --glob '!**/plan.out' \
    --glob '!**/plan.json' \
    --glob '!scripts/ci/secret-scan.sh' || true
)"

if [[ -n "$secret_matches" ]]; then
  printf '%s\n' "$secret_matches" >&2
  echo "Secret-looking material or kubeconfig credential fields were found. Commit only safe references, placeholders, or encrypted material." >&2
  exit 1
fi
echo "::endgroup::"

is_git_work_tree=false
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  is_git_work_tree=true
fi

github_event_value() {
  local key="$1"

  if [[ -z "${GITHUB_EVENT_PATH:-}" || ! -f "${GITHUB_EVENT_PATH}" ]]; then
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$key" <<'PY'
import json
import sys

key = sys.argv[1]
try:
    with open(__import__("os").environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
        value = json.load(handle).get(key, "")
except (OSError, json.JSONDecodeError):
    value = ""

if value is not None:
    print(value)
PY
    return 0
  fi

  sed -nE "s/^[[:space:]]*\"${key}\":[[:space:]]*\"?([^\",}]+)\"?.*/\\1/p" "${GITHUB_EVENT_PATH}" | head -n 1
}

github_pr_number() {
  if [[ "${GITHUB_REF:-}" =~ ^refs/pull/([0-9]+)/ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi

  github_event_value number
}

ensure_ci_git_history() {
  if [[ "$is_git_work_tree" != "true" || "${CI:-}" != "true" ]]; then
    return 0
  fi

  if [[ "$(git rev-parse --is-shallow-repository 2>/dev/null || echo false)" == "true" ]]; then
    git fetch --no-tags --prune --unshallow origin
  fi

  case "${GITHUB_EVENT_NAME:-}" in
    pull_request|pull_request_target)
      if [[ -n "${GITHUB_BASE_REF:-}" ]]; then
        git fetch --no-tags --prune origin \
          "+refs/heads/${GITHUB_BASE_REF}:refs/remotes/origin/${GITHUB_BASE_REF}"
      fi

      local pr_number
      pr_number="$(github_pr_number)"
      if [[ -n "$pr_number" ]]; then
        git fetch --no-tags --prune origin \
          "+refs/pull/${pr_number}/head:refs/remotes/origin/pull/${pr_number}/head"
      fi
      ;;
    push)
      if [[ -n "${GITHUB_REF_NAME:-}" ]]; then
        git fetch --no-tags --prune origin \
          "+refs/heads/${GITHUB_REF_NAME}:refs/remotes/origin/${GITHUB_REF_NAME}"
      fi
      ;;
  esac
}

git_history_log_opts() {
  if [[ -n "${GITLEAKS_LOG_OPTS:-}" ]]; then
    printf '%s\n' "$GITLEAKS_LOG_OPTS"
    return 0
  fi

  if [[ "$is_git_work_tree" != "true" ]]; then
    return 0
  fi

  case "${GITHUB_EVENT_NAME:-}" in
    pull_request|pull_request_target)
      local pr_ref="HEAD"
      local pr_number
      pr_number="$(github_pr_number)"
      if [[ -n "$pr_number" ]] && git rev-parse --verify --quiet "refs/remotes/origin/pull/${pr_number}/head" >/dev/null; then
        pr_ref="refs/remotes/origin/pull/${pr_number}/head"
      fi

      if [[ -n "${GITHUB_BASE_REF:-}" ]] && git rev-parse --verify --quiet "refs/remotes/origin/${GITHUB_BASE_REF}" >/dev/null; then
        local merge_base
        merge_base="$(git merge-base "refs/remotes/origin/${GITHUB_BASE_REF}" "$pr_ref" 2>/dev/null || true)"
        if [[ -n "$merge_base" ]]; then
          printf '%s..%s\n' "$merge_base" "$pr_ref"
          return 0
        fi
      fi
      ;;
    push)
      local before after zero_sha
      before="$(github_event_value before)"
      after="${GITHUB_SHA:-HEAD}"
      zero_sha="0000000000000000000000000000000000000000"

      if [[ -n "$before" && "$before" != "$zero_sha" ]] && git cat-file -e "${before}^{commit}" 2>/dev/null; then
        printf '%s..%s\n' "$before" "$after"
        return 0
      fi
      ;;
  esac

  if git rev-parse --verify --quiet refs/remotes/origin/main >/dev/null; then
    local merge_base
    merge_base="$(git merge-base refs/remotes/origin/main HEAD 2>/dev/null || true)"
    if [[ -n "$merge_base" && "$merge_base" != "$(git rev-parse HEAD)" ]]; then
      printf '%s..HEAD\n' "$merge_base"
      return 0
    fi
  fi

  printf 'HEAD\n'
}

if command -v gitleaks >/dev/null 2>&1; then
  echo "::group::Gitleaks working tree scan"
  gitleaks detect --no-git --redact --source . --verbose
  echo "::endgroup::"

  if [[ "$is_git_work_tree" == "true" ]]; then
    echo "::group::Gitleaks git history scan"
    ensure_ci_git_history

    history_log_opts="$(git_history_log_opts)"
    if [[ -n "$history_log_opts" ]]; then
      echo "Scanning git history range: ${history_log_opts}"
      gitleaks detect --redact --source . --verbose --log-opts "$history_log_opts"
    else
      gitleaks detect --redact --source . --verbose
    fi
    echo "::endgroup::"
  fi
elif [[ "${CI:-}" == "true" ]]; then
  echo "gitleaks is required in CI but was not found in PATH" >&2
  exit 1
else
  echo "::warning::gitleaks is not available in this local shell; GitHub Actions runs it from the Nix dev shell."
fi
