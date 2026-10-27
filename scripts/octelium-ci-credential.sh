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
apply_catalog="false"
apply_catalog_requested="false"
update_github="true"
rotate_credential="true"
delete_user_sessions="true"
dry_run="false"
environments=("homelab-plan" "homelab-production")
preflight_secret_name=""
preflight_env_name=""
credential_json=""

cleanup() {
  if [[ -n "$preflight_secret_name" && -n "$preflight_env_name" ]]; then
    if ! gh api --method DELETE \
      "repos/${github_repo}/environments/${preflight_env_name}/secrets/${preflight_secret_name}" \
      >/dev/null 2>&1; then
      echo "warning: temporary GitHub preflight secret ${preflight_secret_name} may remain in ${preflight_env_name}" >&2
    fi
  fi
  if [[ -n "$credential_json" ]]; then
    rm -f "$credential_json"
  fi
}
trap cleanup EXIT

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-ci-credential.sh [options]

Rotate the policy-bound GitHub Actions Octelium credential used by Terragrunt
plan/apply and diagnostics. Existing CI access resources are verified before
rotation. Bootstrap catalog application requires --apply-catalog.

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
  --delete-user-sessions       Delete all Octelium sessions for --user before
                               rotating the credential. This is the default.
  --delete-user-sessions-only  Delete all Octelium sessions for --user without
                               applying the catalog, rotating a credential, or
                               updating GitHub. Incompatible with --apply-catalog.
  --env NAME                   GitHub environment to update. May be repeated.
                               Defaults: homelab-plan, homelab-production
  --apply-catalog              Apply the full catalog before rotating. Use only
                               for bootstrap or a separately reviewed change.
  --skip-catalog               Do not apply the catalog (default).
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
    --apply-catalog)
      apply_catalog="true"
      apply_catalog_requested="true"
      shift
      ;;
    --skip-github)
      update_github="false"
      delete_user_sessions="false"
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

if [[ "$rotate_credential" != "true" && "$apply_catalog_requested" == "true" ]]; then
  echo "error: --delete-user-sessions-only cannot be combined with --apply-catalog" >&2
  exit 2
fi

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
    HTTPS_PROXY="$octelium_proxy" ALL_PROXY="$octelium_proxy" NO_PROXY='' \
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
    echo "DRY-RUN would delete all Octelium sessions for User ${user_name}"
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

if [[ "$delete_user_sessions" == "true" &&
  "$rotate_credential" == "true" &&
  "$update_github" != "true" ]]; then
  echo "error: refusing to reset User ${user_name} sessions while GitHub secret updates are disabled" >&2
  exit 1
fi

preflight_github_secret_targets() {
  local delete_path
  local env_name
  local preflight_secret_value="ok"

  if [[ "$update_github" != "true" || "$rotate_credential" != "true" ]]; then
    return 0
  fi

  preflight_secret_name="OCTELIUM_CI_PREFLIGHT_$$_${RANDOM}"
  echo "Verifying GitHub environment secret write access for ${github_repo}..."
  gh auth status >/dev/null
  for env_name in "${environments[@]}"; do
    preflight_env_name="$env_name"
    printf '%s' "$preflight_secret_value" |
      gh secret set "$preflight_secret_name" --repo "$github_repo" --env "$env_name" \
        >/dev/null
    delete_path="repos/${github_repo}/environments/${env_name}/secrets/${preflight_secret_name}"
    gh api \
      --method DELETE \
      "$delete_path" \
      >/dev/null
    preflight_env_name=""
    echo "Verified GitHub environment ${env_name} accepts secret writes."
  done
}

validate_target_user() {
  local user_json

  if [[ "$rotate_credential" != "true" && "$delete_user_sessions" != "true" ]]; then
    return 0
  fi

  if ! user_json="$(
    run_octeliumctl get user "$user_name" --domain "$domain" -o json 2>&1
  )"; then
    echo "error: could not read Octelium User ${user_name}" >&2
    printf '%s\n' "$user_json" >&2
    exit 1
  fi
  if ! jq -e \
    --arg user "$user_name" \
    --argjson require_enabled "$rotate_credential" \
    'type == "object" and .metadata.name == $user and .spec.type == "WORKLOAD" and
      ($require_enabled == false or (
        (.spec.isDisabled // false) == false and
        .spec.session.clientlessDuration == {"days": 30} and
        .spec.session.accessTokenDuration == {"days": 30}
      ))' \
    >/dev/null 2>&1 <<<"$user_json"; then
    echo "error: Octelium User ${user_name} differs from the dedicated CI access contract" >&2
    exit 1
  fi

  echo "Verified Octelium User ${user_name} is a dedicated WORKLOAD User."
}

validate_ci_access() {
  local policy_json service_json

  if [[ "$rotate_credential" != "true" ]]; then
    return 0
  fi

  if ! policy_json="$(run_octeliumctl get policy "$policy_name" --domain "$domain" -o json 2>/dev/null)"; then
    echo "error: could not read Octelium Policy ${policy_name}" >&2
    exit 1
  fi
  if ! jq -e --arg user "$user_name" --arg policy "$policy_name" '
    .metadata.name == $policy and
    (.spec.isDisabled // false) == false and
    (.spec.rules | length) == 1 and
    .spec.rules[0].effect == "ALLOW" and
    (.spec.rules[0].condition | keys) == ["all"] and
    (.spec.rules[0].condition.all | keys) == ["of"] and
    all(.spec.rules[0].condition.all.of[]; keys == ["match"]) and
    ([.spec.rules[0].condition.all.of[].match] | sort) == ([
      "ctx.user.metadata.name == \"\($user)\"",
      "ctx.user.spec.type == \"WORKLOAD\"",
      "ctx.session.status.type == \"CLIENTLESS\"",
      "ctx.service.metadata.name == \"kubernetes-api-ci.default\"",
      "ctx.service.spec.mode == \"KUBERNETES\""
    ] | sort)
  ' >/dev/null 2>&1 <<<"$policy_json"; then
    echo "error: Octelium Policy ${policy_name} differs from the dedicated CI access contract" >&2
    exit 1
  fi

  if ! service_json="$(run_octeliumctl get service kubernetes-api-ci --domain "$domain" -o json 2>/dev/null)"; then
    echo "error: could not read Octelium Service kubernetes-api-ci" >&2
    exit 1
  fi
  if ! jq -e --arg policy "$policy_name" '
    .metadata.name == "kubernetes-api-ci.default" and
    (.spec.isDisabled // false) == false and
    (.spec.isAnonymous // false) == false and
    .spec.isPublic == true and
    .spec.mode == "KUBERNETES" and
    .spec.port == 6443 and
    (.spec.authorization.policies | index($policy)) != null and
    .spec.config.upstream.url == "https://10.1.0.199:6443" and
    .spec.config.kubernetes.kubeconfig.fromSecret == "homelab-ci-kubeconfig"
  ' >/dev/null 2>&1 <<<"$service_json"; then
    echo "error: Octelium Service kubernetes-api-ci differs from the dedicated CI access contract" >&2
    exit 1
  fi

  echo "Verified dedicated CI Policy and Kubernetes Service."
}

if [[ "$apply_catalog" != "true" ]]; then
  validate_target_user
  validate_ci_access
fi

preflight_github_secret_targets

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
  validate_target_user
  validate_ci_access
fi

list_octelium_items() {
  local resource="$1"
  shift
  local page=1 page_json item_count expected_total current_total
  local combined='{"items":[]}'

  # shortcut: 100 pages bounds a broken listing; raise after a large-inventory fixture.
  while [[ "$page" -le 100 ]]; do
    if ! page_json="$(run_octeliumctl get "$resource" "$@" \
      --items-per-page 1000 --page "$page" --order-by-name \
      --domain "$domain" -o json 2>/dev/null)"; then
      echo "error: could not list Octelium ${resource} page ${page}" >&2
      return 1
    fi
    if grep -Eq '^[[:space:]]*No (Sessions|Credentials) found[[:space:]]*$' <<<"$page_json"; then
      if [[ "$page" -eq 1 ]]; then
        printf '%s\n' "$combined"
        return 0
      fi
      echo "error: Octelium ${resource} page ${page} disappeared after hasMore" >&2
      return 1
    fi
    if ! jq -se --argjson page "$page" '
      length == 1 and
      (.[0] | type == "object" and (.items | type == "array") and
        all(.items[]; (.metadata.name | type == "string" and length > 0)) and
        (.listResponseMeta | type == "object") and
        (.listResponseMeta.page // 0) == ($page - 1) and
        (.listResponseMeta.itemsPerPage | type == "number" and . > 0) and
        (.listResponseMeta.totalCount | type == "number") and
        .listResponseMeta.totalCount >= (.items | length) and
        (.listResponseMeta.hasMore == null or
          (.listResponseMeta.hasMore | type == "boolean")))
    ' >/dev/null 2>&1 <<<"$page_json"; then
      echo "error: invalid Octelium ${resource} page ${page}" >&2
      return 1
    fi
    item_count="$(jq '.items | length' <<<"$page_json")"
    if [[ "$item_count" -eq 0 ]]; then
      echo "error: empty Octelium ${resource} page ${page} with list metadata" >&2
      return 1
    fi
    current_total="$(jq '.listResponseMeta.totalCount' <<<"$page_json")"
    if [[ "$page" -eq 1 ]]; then
      expected_total="$current_total"
    elif [[ "$current_total" -ne "$expected_total" ]]; then
      echo "error: Octelium ${resource} total changed during listing" >&2
      return 1
    fi
    if ! combined="$(jq -cs '{items: (.[0].items + .[1].items)}' \
      <(printf '%s\n' "$combined") <(printf '%s\n' "$page_json"))"; then
      echo "error: could not combine Octelium ${resource} pages" >&2
      return 1
    fi
    if ! jq -e '
      [.items[].metadata.name] as $names |
      ($names | length) == ($names | unique | length)
    ' >/dev/null 2>&1 <<<"$combined"; then
      echo "error: duplicate Octelium ${resource} entries across pages" >&2
      return 1
    fi
    if [[ "$(jq -r '.listResponseMeta.hasMore // false' <<<"$page_json")" == "false" ]]; then
      break
    fi
    page=$((page + 1))
  done
  if [[ "$page" -gt 100 ]]; then
    echo "error: Octelium ${resource} listing exceeded 100 pages" >&2
    return 1
  fi
  if [[ "$(jq '.items | length' <<<"$combined")" -ne "$expected_total" ]]; then
    echo "error: incomplete Octelium ${resource} listing" >&2
    return 1
  fi
  printf '%s\n' "$combined"
}

delete_user_sessions_for_user() {
  local sessions_json
  local session_name
  local session_names=()

  sessions_json="$(list_octelium_items sessions --user "$user_name")"

  while IFS= read -r session_name; do
    if [[ -n "$session_name" ]]; then
      session_names+=("$session_name")
    fi
  done < <(
    jq -r '
      .items[] |
      .metadata.name
    ' <<<"$sessions_json"
  )

  if [[ "${#session_names[@]}" -eq 0 ]]; then
    echo "No Octelium sessions found for User ${user_name}."
    return 0
  fi

  echo "Deleting ${#session_names[@]} Octelium sessions for User ${user_name}..."
  for session_name in "${session_names[@]}"; do
    run_octeliumctl delete session "$session_name" --domain "$domain" >/dev/null
    echo "Deleted Octelium session ${session_name}"
  done
}

credential_exists="false"
existing_credential_json=""
ensure_existing_credential_spec() {
  local credential_spec
  local spec_output

  if [[ "$credential_exists" != "true" ]]; then
    return 0
  fi

  if ! jq -e --arg user "$user_name" '.spec.user == $user' \
    <<<"$existing_credential_json" >/dev/null; then
    echo "error: refusing to rebind existing credential ${credential_name} from another User" >&2
    exit 1
  fi

  if jq -e \
    --arg user "$user_name" \
    --arg policy "$policy_name" \
    '
      .spec.user == $user and
      .spec.type == "ACCESS_TOKEN" and
      .spec.sessionType == "CLIENTLESS" and
      (.spec.authorization.policies // []) == [$policy]
    ' <<<"$existing_credential_json" >/dev/null; then
    echo "Existing Octelium credential ${credential_name} already targets User ${user_name} with Policy ${policy_name}."
    return 0
  fi

  if [[ "$apply_catalog" != "true" ]]; then
    echo "error: existing Octelium credential ${credential_name} binding differs; review the catalog before rotation" >&2
    exit 1
  fi

  credential_spec="$(mktemp "${TMPDIR:-/tmp}/octelium-ci-credential-spec.XXXXXX.yaml")"
  {
    printf 'kind: Credential\n'
    printf 'metadata:\n'
    printf '  name: %s\n' "$credential_name"
    printf 'spec:\n'
    printf '  type: ACCESS_TOKEN\n'
    printf '  user: %s\n' "$user_name"
    printf '  sessionType: CLIENTLESS\n'
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
  --type access-token
  --session-type clientless
  -o json
)

if [[ "$rotate_credential" == "true" ]]; then
  credentials_json="$(list_octelium_items creds)"
  if [[ "$(jq '.items | length' <<<"$credentials_json")" -gt 0 ]]; then
    credential_count="$(
      jq -r \
        --arg name "$credential_name" \
        '[.items[] | select(.metadata.name == $name)] | length' \
        <<<"$credentials_json"
    )"
    if [[ "$credential_count" -gt 1 ]]; then
      echo "error: multiple Octelium credentials named ${credential_name}" >&2
      exit 1
    fi
    if [[ "$credential_count" -eq 1 ]]; then
      credential_exists="true"
      existing_credential_json="$(
        jq -c \
          --arg name "$credential_name" \
          '.items[] | select(.metadata.name == $name)' \
          <<<"$credentials_json"
      )"
    fi
  fi

  if [[ "$credential_exists" == "true" ]]; then
    if [[ "$update_github" != "true" ]]; then
      echo "error: refusing to rotate existing credential ${credential_name} while GitHub secret update is disabled" >&2
      exit 1
    fi
    ensure_existing_credential_spec
    create_args+=(--rotate)
  fi
fi

if [[ "$rotate_credential" == "true" ]]; then
  credential_json="$(mktemp "${TMPDIR:-/tmp}/octelium-ci-credential.XXXXXX.json")"
  chmod 0600 "$credential_json"
fi

if [[ "$delete_user_sessions" == "true" ]]; then
  delete_user_sessions_for_user
fi

if [[ "$rotate_credential" != "true" ]]; then
  echo "Octelium user session cleanup complete."
  exit 0
fi

if [[ "$credential_exists" == "true" ]]; then
  echo "Rotating existing Octelium credential ${credential_name}..."
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

set_github_environment_secret() {
  local env_name="$1"
  local attempt

  for attempt in 1 2 3 4 5; do
    if printf '%s' "$credential_token" |
      gh secret set "$secret_name" --repo "$github_repo" --env "$env_name" >/dev/null; then
      return 0
    fi
    if [[ "$attempt" -lt 5 ]]; then
      echo "GitHub environment ${env_name} update failed; retrying in 5 seconds." >&2
      sleep 5
    fi
  done
  echo "error: GitHub environment ${env_name} update failed after five attempts; rerun rotation for both environments" >&2
  return 1
}

if [[ "$update_github" == "true" ]]; then
  for env_name in "${environments[@]}"; do
    set_github_environment_secret "$env_name"
    echo "Updated ${secret_name} in GitHub environment ${env_name}"
  done
else
  echo "Created/rotated ${credential_name}; GitHub secret update skipped."
fi

unset credential_token
echo "Octelium CI credential rotation complete."
