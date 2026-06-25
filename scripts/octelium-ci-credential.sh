#!/usr/bin/env bash
set -euo pipefail

domain="stinkyboi.com"
github_repo="Stuhlmuller/homelab"
catalog="docs/examples/octelium/homelab-services.yaml"
credential_name="homelab-ci"
user_name="homelab-ci"
policy_name="homelab-ci-kubernetes-api-access"
secret_name="OCTELIUM_CI_AUTH_TOKEN"
octelium_homedir=""
octelium_proxy=""
apply_catalog="true"
update_github="true"
rotate_credential="true"
delete_user_sessions="false"
dry_run="false"
environments=("homelab-plan" "homelab-production")

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-ci-credential.sh [options]

Apply the Octelium CI service catalog and rotate the policy-bound GitHub
Actions Octelium credential used by Terragrunt plan/apply and diagnostics.

The script requires an authenticated Octelium admin session for octeliumctl.
It captures the generated credential token in a 0600 temporary file, pipes it
directly into the GitHub environment secrets, and removes the temporary file
before exit. The token is not printed.

Options:
  --domain DOMAIN              Octelium Cluster domain. Default: stinkyboi.com
  --repo OWNER/REPO            GitHub repository. Default: Stuhlmuller/homelab
  --catalog PATH               Octelium catalog path.
                               Default: docs/examples/octelium/homelab-services.yaml
  --credential-name NAME       Credential resource name. Default: homelab-ci
  --user NAME                  Octelium User name. Default: homelab-ci
  --policy NAME                Octelium Policy name.
                               Default: homelab-ci-kubernetes-api-access
  --secret-name NAME           GitHub environment secret name.
                               Default: OCTELIUM_CI_AUTH_TOKEN
  --homedir PATH               Octelium CLI homedir to use for authentication.
                               Useful for bootstrap recovery sessions.
  --octelium-proxy URL         Proxy URL used only for octeliumctl commands.
                               Useful with a local CONNECT proxy during recovery.
  --delete-user-sessions       Delete active Octelium sessions for --user before
                               rotating the credential.
  --delete-user-sessions-only  Delete active Octelium sessions for --user without
                               applying the catalog, rotating a credential, or
                               updating GitHub.
  --env NAME                   GitHub environment to update. May be repeated.
                               Defaults: homelab-plan, homelab-production
  --skip-catalog               Do not apply the catalog before rotating.
  --skip-github                Create/rotate the credential but do not update GitHub.
                               This is intended only for debugging token parsing.
  --dry-run                    Print intended actions without creating a credential.
  -h, --help                   Show this help.
USAGE
}

custom_envs="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      domain="$2"
      shift 2
      ;;
    --repo)
      github_repo="$2"
      shift 2
      ;;
    --catalog)
      catalog="$2"
      shift 2
      ;;
    --credential-name)
      credential_name="$2"
      shift 2
      ;;
    --user)
      user_name="$2"
      shift 2
      ;;
    --policy)
      policy_name="$2"
      shift 2
      ;;
    --secret-name)
      secret_name="$2"
      shift 2
      ;;
    --homedir)
      octelium_homedir="$2"
      shift 2
      ;;
    --octelium-proxy)
      octelium_proxy="$2"
      shift 2
      ;;
    --delete-user-sessions)
      delete_user_sessions="true"
      shift
      ;;
    --delete-user-sessions-only)
      delete_user_sessions="true"
      apply_catalog="false"
      update_github="false"
      rotate_credential="false"
      shift
      ;;
    --env)
      if [[ "$custom_envs" == "false" ]]; then
        environments=()
        custom_envs="true"
      fi
      environments+=("$2")
      shift 2
      ;;
    --skip-catalog)
      apply_catalog="false"
      shift
      ;;
    --skip-github)
      update_github="false"
      shift
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: $1 is required" >&2
    exit 127
  fi
}

validate_name() {
  local value="$1"
  local label="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$ ]]; then
    echo "error: ${label} contains unsupported characters: ${value}" >&2
    exit 1
  fi
}

require_command octeliumctl
require_command jq
if [[ "$update_github" == "true" && "$rotate_credential" == "true" ]]; then
  require_command gh
fi

octeliumctl_cmd=(octeliumctl)
if [[ -n "$octelium_homedir" ]]; then
  octeliumctl_cmd+=(--homedir "$octelium_homedir")
fi

run_octeliumctl() {
  if [[ -n "$octelium_proxy" ]]; then
    HTTPS_PROXY="$octelium_proxy" ALL_PROXY="$octelium_proxy" NO_PROXY= \
      "${octeliumctl_cmd[@]}" "$@"
  else
    "${octeliumctl_cmd[@]}" "$@"
  fi
}

if [[ ! -f "$catalog" ]]; then
  echo "error: catalog does not exist: ${catalog}" >&2
  exit 1
fi
if [[ "${#environments[@]}" -eq 0 ]]; then
  echo "error: at least one --env value is required" >&2
  exit 1
fi

validate_name "$credential_name" "--credential-name"
validate_name "$user_name" "--user"
validate_name "$policy_name" "--policy"
validate_name "$secret_name" "--secret-name"
for env_name in "${environments[@]}"; do
  validate_name "$env_name" "--env"
done

if [[ "$dry_run" == "true" ]]; then
  if [[ "$apply_catalog" == "true" ]]; then
    echo "DRY-RUN would apply ${catalog} to ${domain}"
  fi
  if [[ "$delete_user_sessions" == "true" ]]; then
    echo "DRY-RUN would delete active Octelium sessions for User ${user_name}"
  fi
  if [[ "$rotate_credential" == "true" ]]; then
    echo "DRY-RUN would create or rotate Octelium credential ${credential_name} for User ${user_name} with Policy ${policy_name}"
  fi
  if [[ "$update_github" == "true" ]]; then
    printf 'DRY-RUN would update GitHub secret %s in environments:' "$secret_name"
    printf ' %s' "${environments[@]}"
    printf '\n'
  fi
  exit 0
fi

preflight_github_secret_targets() {
  local delete_path
  local env_name
  local preflight_secret_name
  local preflight_secret_value="ok"

  if [[ "$update_github" != "true" || "$rotate_credential" != "true" ]]; then
    return 0
  fi

  preflight_secret_name="OCTELIUM_CI_PREFLIGHT_$$_${RANDOM}"
  echo "Verifying GitHub environment secret write access for ${github_repo}..."
  gh auth status >/dev/null
  for env_name in "${environments[@]}"; do
    printf '%s' "$preflight_secret_value" |
      gh secret set "$preflight_secret_name" --repo "$github_repo" --env "$env_name" \
        >/dev/null
    delete_path="repos/${github_repo}/environments/${env_name}/secrets/${preflight_secret_name}"
    gh api \
      --method DELETE \
      "$delete_path" \
      >/dev/null
    echo "Verified GitHub environment ${env_name} accepts secret writes."
  done
}

if [[ "$apply_catalog" == "true" ]]; then
  apply_output=""
  echo "Applying Octelium catalog ${catalog} to ${domain}..."
  if ! apply_output="$(run_octeliumctl apply --domain "$domain" "$catalog" 2>&1)"; then
    printf '%s\n' "$apply_output" >&2
    exit 1
  fi
  printf '%s\n' "$apply_output"
  if grep -Eq '(^|[[:space:]])Could not (create|update|apply)|gRPC error' <<<"$apply_output"; then
    echo "error: octeliumctl reported one or more failed catalog changes" >&2
    exit 1
  fi
fi

preflight_github_secret_targets

delete_active_user_sessions() {
  local sessions_json
  local session_name
  local active_session_names=()

  sessions_json="$(
    run_octeliumctl get sessions \
      --user "$user_name" \
      --items-per-page 1000 \
      --domain "$domain" \
      -o json
  )"

  if grep -Eq '^No Sessions found$' <<<"$sessions_json"; then
    echo "No active Octelium sessions found for User ${user_name}."
    return 0
  fi
  if ! jq -e . >/dev/null 2>&1 <<<"$sessions_json"; then
    echo "error: octeliumctl returned non-JSON session output" >&2
    printf '%s\n' "$sessions_json" >&2
    exit 1
  fi

  while IFS= read -r session_name; do
    if [[ -n "$session_name" ]]; then
      active_session_names+=("$session_name")
    fi
  done < <(
    jq -r '
      .items[]? |
      select(.spec.state == "ACTIVE") |
      .metadata.name
    ' <<<"$sessions_json"
  )

  if [[ "${#active_session_names[@]}" -eq 0 ]]; then
    echo "No active Octelium sessions found for User ${user_name}."
    return 0
  fi

  echo "Deleting ${#active_session_names[@]} active Octelium sessions for User ${user_name}..."
  for session_name in "${active_session_names[@]}"; do
    run_octeliumctl delete session "$session_name" --domain "$domain" >/dev/null
    echo "Deleted Octelium session ${session_name}"
  done
}

if [[ "$delete_user_sessions" == "true" ]]; then
  delete_active_user_sessions
fi

if [[ "$rotate_credential" != "true" ]]; then
  echo "Octelium user session cleanup complete."
  exit 0
fi

credential_json="$(mktemp "${TMPDIR:-/tmp}/octelium-ci-credential.XXXXXX.json")"
cleanup() {
  rm -f "$credential_json"
}
trap cleanup EXIT
chmod 0600 "$credential_json"

credential_exists="false"
existing_credential_json=""
ensure_existing_credential_spec() {
  local credential_spec
  local spec_output

  if [[ "$credential_exists" != "true" ]]; then
    return 0
  fi

  if jq -e \
    --arg user "$user_name" \
    --arg policy "$policy_name" \
    '
      .spec.user == $user and
      .spec.sessionType == "CLIENT" and
      (.spec.authorization.policies // []) == [$policy]
    ' <<<"$existing_credential_json" >/dev/null; then
    echo "Existing Octelium credential ${credential_name} already targets User ${user_name} with Policy ${policy_name}."
    return 0
  fi

  credential_spec="$(mktemp "${TMPDIR:-/tmp}/octelium-ci-credential-spec.XXXXXX.yaml")"
  {
    printf 'kind: Credential\n'
    printf 'metadata:\n'
    printf '  name: %s\n' "$credential_name"
    printf 'spec:\n'
    printf '  type: AUTH_TOKEN\n'
    printf '  user: %s\n' "$user_name"
    printf '  sessionType: CLIENT\n'
    printf '  authorization:\n'
    printf '    policies:\n'
    printf '      - %s\n' "$policy_name"
  } >"$credential_spec"

  echo "Updating existing Octelium credential ${credential_name} binding before rotation..."
  if ! spec_output="$(run_octeliumctl apply --domain "$domain" "$credential_spec" 2>&1)"; then
    rm -f "$credential_spec"
    printf '%s\n' "$spec_output" >&2
    exit 1
  fi
  rm -f "$credential_spec"
  printf '%s\n' "$spec_output"
  if grep -Eq '(^|[[:space:]])Could not (create|update|apply)|gRPC error' <<<"$spec_output"; then
    echo "error: octeliumctl reported a failed credential binding update" >&2
    exit 1
  fi
}

create_args=(
  create cred
  --domain "$domain"
  --user "$user_name"
  --policy "$policy_name"
  -o json
)

if existing_credential_json="$(run_octeliumctl get cred "$credential_name" --domain "$domain" -o json 2>/dev/null)"; then
  credential_exists="true"
  if [[ "$update_github" != "true" ]]; then
    echo "error: refusing to rotate existing credential ${credential_name} while GitHub secret update is disabled" >&2
    exit 1
  fi
  ensure_existing_credential_spec
  echo "Rotating existing Octelium credential ${credential_name}..."
  create_args+=(--rotate)
else
  echo "Creating Octelium credential ${credential_name}..."
fi

run_octeliumctl "${create_args[@]}" "$credential_name" >"$credential_json"

credential_token="$(
  jq -er '
    [
      .. | objects | to_entries[] |
      select((.key | test("(?i)(token|credential)")) and (.value | type == "string") and (.value | length > 40)) |
      .value
    ][0]
  ' "$credential_json"
)"

if [[ -z "$credential_token" ]]; then
  echo "error: could not extract the generated credential token from octeliumctl JSON output" >&2
  exit 1
fi

if [[ "$update_github" == "true" ]]; then
  for env_name in "${environments[@]}"; do
    printf '%s' "$credential_token" |
      gh secret set "$secret_name" --repo "$github_repo" --env "$env_name" >/dev/null
    echo "Updated ${secret_name} in GitHub environment ${env_name}"
  done
else
  echo "Created/rotated ${credential_name}; GitHub secret update skipped."
fi

unset credential_token
echo "Octelium CI credential rotation complete."
