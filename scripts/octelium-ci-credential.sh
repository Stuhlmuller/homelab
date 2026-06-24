#!/usr/bin/env bash
set -euo pipefail

domain="stinkyboi.com"
github_repo="Stuhlmuller/homelab"
catalog="docs/examples/octelium/homelab-services.yaml"
credential_name="homelab-ci"
user_name="homelab-ci"
policy_name="homelab-ci-kubernetes-api-access"
secret_name="OCTELIUM_CI_AUTH_TOKEN"
apply_catalog="true"
update_github="true"
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
if [[ "$update_github" == "true" ]]; then
  require_command gh
fi

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
  echo "DRY-RUN would create or rotate Octelium credential ${credential_name} for User ${user_name} with Policy ${policy_name}"
  if [[ "$update_github" == "true" ]]; then
    printf 'DRY-RUN would update GitHub secret %s in environments:' "$secret_name"
    printf ' %s' "${environments[@]}"
    printf '\n'
  fi
  exit 0
fi

if [[ "$apply_catalog" == "true" ]]; then
  echo "Applying Octelium catalog ${catalog} to ${domain}..."
  octeliumctl apply --domain "$domain" "$catalog"
fi

credential_json="$(mktemp "${TMPDIR:-/tmp}/octelium-ci-credential.XXXXXX.json")"
cleanup() {
  rm -f "$credential_json"
}
trap cleanup EXIT
chmod 0600 "$credential_json"

create_args=(
  create cred
  --domain "$domain"
  --user "$user_name"
  --policy "$policy_name"
  --out json
)

if octeliumctl get cred "$credential_name" --domain "$domain" >/dev/null 2>&1; then
  echo "Rotating existing Octelium credential ${credential_name}..."
  create_args+=(--rotate)
else
  echo "Creating Octelium credential ${credential_name}..."
fi

octeliumctl "${create_args[@]}" "$credential_name" >"$credential_json"

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
