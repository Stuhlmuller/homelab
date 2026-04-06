#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-${TG_AWS_REGION:-us-east-1}}"
AWS_PROFILE_HINT="${AWS_PROFILE:-default}"

# AWS get-parameters accepts at most 10 names per request.
required_parameters=(
  "/homelab/dokploy/postgres_password"
  "/homelab/paperclip/better_auth_secret"
  "/homelab/paperclip/openrouter_api_key"
  "/homelab/paperclip/postgres_password"
  "/homelab/policy-bot/github_app_integration_id"
  "/homelab/policy-bot/github_app_private_key"
  "/homelab/policy-bot/github_app_webhook_secret"
  "/homelab/policy-bot/github_oauth_client_id"
  "/homelab/policy-bot/github_oauth_client_secret"
  "/homelab/policy-bot/sessions_key"
  "/homelab/traefik/cf_dns_api_token"
)

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required for SSM validation" >&2
  exit 1
fi

if ! aws sts get-caller-identity --output json >/dev/null 2>&1; then
  echo "AWS authentication is unavailable. Refresh it with: aws sso login --profile ${AWS_PROFILE_HINT}" >&2
  exit 1
fi

invalid=()
total=${#required_parameters[@]}
for ((i = 0; i < total; i += 10)); do
  batch=( "${required_parameters[@]:i:10}" )
  response="$(
    aws ssm get-parameters \
      --region "${AWS_REGION}" \
      --with-decryption \
      --names "${batch[@]}" \
      --output json
  )"
  while IFS= read -r name; do
    [[ -n "${name}" ]] && invalid+=("${name}")
  done < <(python3 -c "import json,sys; print('\n'.join(json.load(sys.stdin).get('InvalidParameters', [])))" <<<"${response}")
  while IFS= read -r line; do
    [[ -n "${line}" ]] && printf '%s\n' "${line}"
  done < <(
    python3 -c "
import json, sys
for p in json.load(sys.stdin).get('Parameters', []):
    print(f\"validated SSM parameter: {p['Name']}\")
" <<<"${response}"
  )
done

if ((${#invalid[@]})); then
  echo "Missing required AWS SSM parameters:" >&2
  for name in "${invalid[@]}"; do
    echo "  - ${name}" >&2
  done
  exit 1
fi
