#!/usr/bin/env bash
set -euo pipefail
umask 077

mode="${1:-}"
[[ $# -eq 1 && ("$mode" == "rollout" || "$mode" == "revoke") ]] || {
  echo "usage: scripts/octelium-private-kubernetes-credential.sh rollout|revoke" >&2
  exit 2
}

domain="stinkyboi.com"
repo="Stuhlmuller/homelab"
environment="homelab-production"
secret_name="OCTELIUM_CATALOG_AUTH_TOKEN"
user_name="homelab-catalog-ci"
credential_name="homelab-private-kubernetes-ci"
workflow="octelium-private-kubernetes-apply.yml"
catalog="docs/examples/octelium/homelab-services.yaml"
credential_template="docs/examples/octelium/homelab-private-kubernetes-ci-credential.yaml"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

for command in octeliumctl gh git jq yq; do
  command -v "$command" >/dev/null || {
    echo "error: $command is required" >&2
    exit 127
  }
done

run_apply() {
  local output
  if ! output="$(octeliumctl apply --domain "$domain" "$@" 2>&1)"; then
    printf '%s\n' "$output" >&2
    return 1
  fi
  if grep -Eq 'Could not (list|create|update|apply)|gRPC error' <<<"$output"; then
    printf '%s\n' "$output" >&2
    return 1
  fi
}

list_credentials() {
  local output
  if ! output="$(octeliumctl get creds --items-per-page 1000 --domain "$domain" -o json 2>&1)"; then
    echo "error: could not list Octelium Credentials" >&2
    printf '%s\n' "$output" >&2
    return 1
  fi
  if grep -Eq '^[[:space:]]*No Credentials found[[:space:]]*$' <<<"$output"; then
    printf '{"items":[]}\n'
    return
  fi
  jq -ce '
    if type == "object" and (.items | type == "array") then .
    else error("invalid Credential list") end
  ' <<<"$output" 2>/dev/null || {
    echo "error: Octelium returned an invalid Credential list" >&2
    return 1
  }
}

target_credential() {
  local count credentials
  credentials="$(list_credentials)" || return
  count="$(jq -r --arg name "$credential_name" '[.items[] | select(.metadata.name == $name)] | length' <<<"$credentials")"
  [[ "$count" -le 1 ]] || {
    echo "error: multiple Octelium Credentials named ${credential_name}" >&2
    return 1
  }
  jq -c --arg name "$credential_name" '.items[] | select(.metadata.name == $name)' <<<"$credentials"
}

catalog_credential_spec() {
  yq -o=json -I=0 '.' "$credential_template" |
    jq -ce '
      if .kind == "Credential" and
        .metadata.name == "homelab-private-kubernetes-ci" and
        .spec.expiresAt == "1970-01-01T00:00:00Z"
      then .spec | del(.expiresAt)
      else error("invalid catalog Credential") end
    '
}

validate_live_credential() {
  local credential_json="$1"
  local expected_spec="$2"
  jq -e --arg name "$credential_name" --argjson expected "$expected_spec" '
    .metadata.name == $name and .spec == $expected
  ' >/dev/null <<<"$credential_json"
}

validate_revocable_credential() {
  local credential_json="$1"
  local expected_spec
  expected_spec="$(catalog_credential_spec)" || return
  jq -e --arg name "$credential_name" --argjson expected "$expected_spec" '
    .metadata.name == $name and
    (.spec.expiresAt | fromdateiso8601? | type == "number") and
    (.spec | del(.expiresAt)) == $expected
  ' >/dev/null <<<"$credential_json"
}

delete_sessions() {
  bash scripts/octelium-ci-credential.sh \
    --delete-user-sessions-only \
    --user "$user_name" \
    --credential-name "$credential_name" \
    --policy unused \
    --secret-name "$secret_name" \
    --env "$environment"
}

session_count() {
  local output
  if ! output="$(octeliumctl get sessions --user "$user_name" --items-per-page 1000 --domain "$domain" -o json 2>&1)"; then
    echo "error: could not list Octelium Sessions for ${user_name}" >&2
    printf '%s\n' "$output" >&2
    return 1
  fi
  if grep -Eq '^[[:space:]]*No Sessions found[[:space:]]*$' <<<"$output"; then
    printf '0\n'
    return
  fi
  jq -er '
    if type == "object" and (.items | type == "array") and
      all(.items[]; (.metadata.name | type == "string" and length > 0))
    then .items | length
    else error("invalid Session list") end
  ' <<<"$output" 2>/dev/null || {
    echo "error: Octelium returned an invalid Session list" >&2
    return 1
  }
}

secret_exists() {
  local secrets
  if ! secrets="$(gh secret list --repo "$repo" --env "$environment" --json name 2>&1)"; then
    echo "error: could not list GitHub environment secrets" >&2
    printf '%s\n' "$secrets" >&2
    return 1
  fi
  jq -r --arg name "$secret_name" '
    if type == "array" and all(.[]; .name | type == "string")
    then any(.[]; .name == $name)
    else error("invalid GitHub secret list") end
  ' <<<"$secrets"
}

delete_github_secret() {
  local exists
  exists="$(secret_exists)" || return
  if [[ "$exists" == "true" ]]; then
    gh secret delete "$secret_name" --repo "$repo" --env "$environment"
  fi
  exists="$(secret_exists)" || return
  [[ "$exists" == "false" ]] || {
    echo "error: GitHub environment secret ${secret_name} still exists" >&2
    return 1
  }
}

revoke_access() {
  local current="" failed=0 remaining_sessions

  if current="$(target_credential)"; then
    if [[ -n "$current" ]]; then
      if validate_revocable_credential "$current"; then
        octeliumctl delete cred "$credential_name" --domain "$domain" >/dev/null || failed=1
      else
        echo "error: refusing to delete an unexpected Credential" >&2
        failed=1
      fi
    fi
  else
    failed=1
  fi

  if current="$(target_credential)"; then
    if [[ -n "$current" ]]; then
      echo "error: Octelium Credential ${credential_name} still exists" >&2
      failed=1
    fi
  else
    failed=1
  fi

  delete_sessions || failed=1
  if remaining_sessions="$(session_count)"; then
    if [[ "$remaining_sessions" != "0" ]]; then
      echo "error: ${remaining_sessions} Octelium Session(s) still exist for ${user_name}" >&2
      failed=1
    fi
  else
    failed=1
  fi

  delete_github_secret || failed=1
  [[ "$failed" -eq 0 ]] || return 1
  echo "Temporary Octelium catalog access revoked and verified."
}

if [[ "$mode" == "revoke" ]]; then
  status=0
  revoke_access || status=1
  exit "$status"
fi

main_sha="$(gh api "repos/${repo}/git/ref/heads/main" --jq .object.sha)"
[[ "$main_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo "error: GitHub returned an invalid main SHA" >&2
  exit 1
}
[[ "$(git rev-parse HEAD)" == "$main_sha" ]] || {
  echo "error: rollout checkout must be the current GitHub main commit ${main_sha}" >&2
  exit 1
}
[[ -z "$(git status --porcelain)" ]] || {
  echo "error: rollout checkout must be clean" >&2
  exit 1
}
gh auth status >/dev/null

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  set +e
  if ! revoke_access; then
    echo "error: rollout cleanup could not prove complete revocation" >&2
    status=1
  fi
  rm -rf "$tmpdir"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

user_catalog="${tmpdir}/user.yaml"
credential_catalog="${tmpdir}/credential.yaml"
yq ea 'select(.kind == "User" and .metadata.name == "homelab-catalog-ci")' \
  "$catalog" >"$user_catalog"
install -m 0600 "$credential_template" "$credential_catalog"
expires_at="$(jq -nr 'now + 1800 | todateiso8601')"
EXPIRY="$expires_at" yq -i '.spec.expiresAt = strenv(EXPIRY)' "$credential_catalog"
chmod 0600 "$user_catalog" "$credential_catalog"

run_apply --include User "$user_catalog"
delete_sessions
current="$(target_credential)"
if [[ -n "$current" ]]; then
  validate_revocable_credential "$current" || {
    echo "error: refusing to replace an unexpected Credential" >&2
    exit 1
  }
  octeliumctl delete cred "$credential_name" --domain "$domain" >/dev/null
fi
run_apply --include Credential "$credential_catalog"

current="$(target_credential)"
[[ -n "$current" ]] || {
  echo "error: Octelium did not create Credential ${credential_name}" >&2
  exit 1
}
expected_spec="$(yq -o=json -I=0 '.spec' "$credential_catalog")"
validate_live_credential "$current" "$expected_spec" || {
  echo "error: live Credential does not match the complete reviewed specification" >&2
  exit 1
}

token_json="${tmpdir}/token.json"
octeliumctl create cred --rotate "$credential_name" --domain "$domain" -o json >"$token_json"
chmod 0600 "$token_json"
token="$(jq -er '.authenticationToken.authenticationToken' "$token_json")"
printf '%s' "$token" |
  gh secret set "$secret_name" --repo "$repo" --env "$environment"
unset token
[[ "$(secret_exists)" == "true" ]] || {
  echo "error: GitHub environment secret ${secret_name} was not stored" >&2
  exit 1
}

dispatch_id="${tmpdir##*/}"
expected_title="Private Kubernetes @ ${main_sha} / ${dispatch_id}"
gh workflow run "$workflow" --repo "$repo" --ref main \
  -f expected_sha="$main_sha" \
  -f dispatch_id="$dispatch_id"

run_id=""
run_url=""
for _ in {1..30}; do
  runs="$(gh run list --repo "$repo" --workflow "$workflow" --branch main \
    --event workflow_dispatch --commit "$main_sha" --limit 30 \
    --json databaseId,displayTitle,headSha,url)"
  matches="$(jq -c --arg title "$expected_title" --arg sha "$main_sha" \
    '[.[] | select(.displayTitle == $title and .headSha == $sha)]' <<<"$runs")"
  if [[ "$(jq 'length' <<<"$matches")" == "1" ]]; then
    run_id="$(jq -r '.[0].databaseId' <<<"$matches")"
    run_url="$(jq -r '.[0].url' <<<"$matches")"
    break
  fi
  [[ "$(jq 'length' <<<"$matches")" == "0" ]] || {
    echo "error: multiple GitHub Actions runs matched dispatch ${dispatch_id}" >&2
    exit 1
  }
  sleep 2
done
[[ -n "$run_id" ]] || {
  echo "error: could not resolve GitHub Actions run ${dispatch_id}" >&2
  exit 1
}

echo "Watching GitHub Actions run ${run_url}"
gh run watch "$run_id" --repo "$repo" --exit-status
echo "GitHub Actions rollout succeeded: ${run_url}"
