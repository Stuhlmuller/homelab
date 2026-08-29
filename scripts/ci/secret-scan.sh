#!/usr/bin/env bash
set -euo pipefail

explicit_secret_marker_files() {
  rg -l -I \
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
    "$@" \
    --glob '!**/.terraform.lock.hcl' \
    --glob '!**/flake.lock' \
    --glob '!**/.terragrunt-cache/**' \
    --glob '!**/plan.out' \
    --glob '!**/plan.json' \
    --glob '!scripts/ci/secret-scan.sh' || true
}

is_sensitive_iac_artifact_path() {
  local path="$1"

  case "${path##*/}" in
    plan.out|plan.json|tfplan.json|*.plan|*tfplan*|*.tfstate|*.tfstate.*) return 0 ;;
    *) return 1 ;;
  esac
}

saved_plan_content_files() {
  python3 - <<'PY'
import io
import json
import os
import subprocess
import zipfile


def is_plan_archive(source):
    try:
        with zipfile.ZipFile(source) as archive:
            names = set(archive.namelist())
        return {"tfplan", "tfstate"}.issubset(names)
    except (OSError, zipfile.BadZipFile):
        return False


def is_iac_json(source):
    try:
        if hasattr(source, "read"):
            source.seek(0)
            prefix = source.read(4096)
            source.seek(0)
            if not prefix.lstrip().startswith(b"{"):
                return False
            document = json.load(source)
        else:
            with open(source, "rb") as handle:
                prefix = handle.read(4096)
                handle.seek(0)
                if not prefix.lstrip().startswith(b"{"):
                    return False
                document = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return False

    if not isinstance(document, dict):
        return False

    plan_or_shown_state = (
        isinstance(document.get("format_version"), str)
        and any(key in document for key in ("planned_values", "resource_changes", "values"))
    )
    raw_state = (
        isinstance(document.get("version"), int)
        and isinstance(document.get("serial"), int)
        and isinstance(document.get("lineage"), str)
        and isinstance(document.get("resources"), list)
    )
    return plan_or_shown_state or raw_state


def is_saved_plan(source):
    return is_plan_archive(source) or is_iac_json(source)


matches = set()
for root, dirs, files in os.walk("."):
    dirs[:] = [name for name in dirs if name != ".git"]
    for name in files:
        path = os.path.join(root, name)
        if not os.path.islink(path) and is_saved_plan(path):
            matches.add(path)

if subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
).returncode == 0:
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for raw_path in staged:
        if not raw_path:
            continue
        path = os.fsdecode(raw_path)
        blob = subprocess.run(
            ["git", "show", f":{path}"],
            check=False,
            capture_output=True,
        )
        if blob.returncode == 0 and is_saved_plan(io.BytesIO(blob.stdout)):
            matches.add(f"./{path}")

for path in sorted(matches):
    print(path)
PY
}

sensitive_iac_artifacts() {
  {
    find . -type f \( -name plan.out -o -name plan.json -o -name tfplan.json \
      -o -name '*.plan' -o -name '*tfplan*' -o -name '*.tfstate' \
      -o -name '*.tfstate.*' \) \
      -not -path './.git/*' -print

    saved_plan_content_files

    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      while IFS= read -r -d '' staged_path; do
        if is_sensitive_iac_artifact_path "$staged_path"; then
          printf './%s\n' "$staged_path"
        fi
      done < <(git diff --cached --name-only --diff-filter=ACMR -z)
    fi
  } | sort -u
}

is_private_commit_email() {
  [[ "$1" == "noreply@github.com" ||
    "$1" =~ ^[^[:space:]@]+@users\.noreply\.github\.com$ ]]
}

if [[ "${1:-}" == "--artifacts-only" ]]; then
  iac_artifacts="$(sensitive_iac_artifacts)"
  if [[ -n "$iac_artifacts" ]]; then
    printf 'Saved OpenTofu plan or state artifacts are forbidden because they can contain plaintext secrets:\n%s\n' "$iac_artifacts" >&2
    exit 1
  fi
  exit 0
fi

if [[ "${1:-}" == "--self-check" ]]; then
  canary_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-secret-scan.XXXXXX")"
  trap 'rm -rf "$canary_dir"' EXIT
  canary_file="${canary_dir}/canary.txt"
  canary_plan="${canary_dir}/plan.out"
  canary_named_plan="${canary_dir}/change.plan"
  canary_archive="${canary_dir}/innocent.bin"
  canary_state="${canary_dir}/terraform.tfstate"
  canary_backend_state="${canary_dir}/.terraform/terraform.tfstate"
  canary_staged="${canary_dir}/staged.tfplan.json"
  canary_staged_archive="${canary_dir}/review.txt"
  canary_json="${canary_dir}/review.json"
  canary_staged_json="${canary_dir}/notes.json"
  canary_state_json="${canary_dir}/export.json"
  canary_staged_state_json="${canary_dir}/snapshot.json"
  mkdir -p "${canary_dir}/.terraform"
  printf -v canary_value 'AKIA%016d' 0
  printf '%s\n' "$canary_value" >"$canary_file"
  printf '%s\n' "$canary_value" >"$canary_plan"
  printf '%s\n' "$canary_value" >"$canary_named_plan"
  printf '%s\n' "$canary_value" >"$canary_state"
  printf '%s\n' "$canary_value" >"$canary_backend_state"
  printf '%s\n' "$canary_value" >"$canary_staged"
  python3 - "$canary_archive" "$canary_staged_archive" "$canary_json" "$canary_staged_json" "$canary_state_json" "$canary_staged_state_json" <<'PY'
import json
import sys
import zipfile

for path in sys.argv[1:3]:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("tfplan", "binary plan")
        archive.writestr("tfstate", "state snapshot")

for path in sys.argv[3:]:
    with open(path, "w", encoding="utf-8") as handle:
        if path in sys.argv[3:5]:
            document = {
                "format_version": "1.2",
                "planned_values": {"root_module": {}},
                "resource_changes": [],
            }
        elif path == sys.argv[5]:
            document = {
                "version": 4,
                "terraform_version": "1.10.0",
                "serial": 1,
                "lineage": "canary",
                "outputs": {},
                "resources": [],
            }
        else:
            document = {
                "format_version": "1.0",
                "terraform_version": "1.10.0",
                "values": {"root_module": {}},
            }
        json.dump(document, handle)
PY

  self_check_output="$(explicit_secret_marker_files "$canary_file")"
  if [[ "$self_check_output" != "$canary_file" || "$self_check_output" == *"$canary_value"* ]]; then
    echo "Secret scan redaction self-check failed." >&2
    exit 1
  fi

  (
    cd "$canary_dir"
    git init -q
    git add notes.json review.txt snapshot.json staged.tfplan.json
    rm notes.json review.txt snapshot.json staged.tfplan.json
  )
  artifact_output="$(cd "$canary_dir" && sensitive_iac_artifacts)"
  if [[ "$artifact_output" != $'./.terraform/terraform.tfstate\n./change.plan\n./export.json\n./innocent.bin\n./notes.json\n./plan.out\n./review.json\n./review.txt\n./snapshot.json\n./staged.tfplan.json\n./terraform.tfstate' || "$artifact_output" == *"$canary_value"* ]]; then
    echo "Saved OpenTofu artifact self-check failed." >&2
    exit 1
  fi
  is_private_commit_email '57728706+rstuhlmuller@users.noreply.github.com'
  is_private_commit_email 'noreply@github.com'
  if is_private_commit_email 'operator@example.com'; then
    echo "Commit email privacy self-check failed." >&2
    exit 1
  fi

  echo "Secret scan redaction self-check passed."
  exit 0
fi

iac_artifacts="$(sensitive_iac_artifacts)"
if [[ -n "$iac_artifacts" ]]; then
  printf 'Saved OpenTofu plan or state artifacts are forbidden because they can contain plaintext secrets:\n%s\n' "$iac_artifacts" >&2
  exit 1
fi

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
secret_files="$(explicit_secret_marker_files "${existing_scan_paths[@]}")"

if [[ -n "$secret_files" ]]; then
  printf 'Secret-looking material or kubeconfig credential fields were found in:\n%s\n' "$secret_files" >&2
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
    workflow_dispatch)
      printf 'HEAD^..HEAD\n'
      return 0
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

  if git rev-parse --verify --quiet HEAD^ >/dev/null; then
    printf 'HEAD^..HEAD\n'
  else
    printf 'HEAD\n'
  fi
}

history_log_opts=""
if [[ "$is_git_work_tree" == "true" ]]; then
  ensure_ci_git_history
  history_log_opts="$(git_history_log_opts)"

  echo "::group::Commit email privacy"
  exposed_commit_emails="$({
    git log "$history_log_opts" --format='%ae%n%ce' |
      sort -u |
      while IFS= read -r email; do
        is_private_commit_email "$email" || printf '%s\n' "$email"
      done
  })"
  if [[ -n "$exposed_commit_emails" ]]; then
    printf 'Commit author and committer emails must use GitHub noreply addresses:\n%s\n' \
      "$exposed_commit_emails" >&2
    exit 1
  fi
  echo "::endgroup::"
fi

if command -v gitleaks >/dev/null 2>&1; then
  echo "::group::Gitleaks working tree scan"
  gitleaks detect --no-git --redact --source . --verbose
  echo "::endgroup::"

  if [[ "$is_git_work_tree" == "true" ]]; then
    echo "::group::Gitleaks git history scan"
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
