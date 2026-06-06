#!/usr/bin/env bash
set -euo pipefail

domain="octelium.stinkyboi.com"
aws_region="us-west-2"
idp_name="entra"
secret_name="entra-client-secret"
replace_secret="false"

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-entra-idp.sh [options]

Create or update the Octelium Microsoft Entra OIDC IdentityProvider from the
Terragrunt-managed Entra application values in AWS SSM Parameter Store.

Options:
  --domain DOMAIN       Octelium Cluster domain. Default: octelium.stinkyboi.com
  --aws-region REGION   AWS SSM region. Default: us-west-2
  --idp-name NAME       Octelium IdentityProvider name. Default: entra
  --secret-name NAME    Octelium Secret name for the Entra client secret.
                        Default: entra-client-secret
  --replace-secret      Delete and recreate the Octelium Secret before apply.
                        Use only when rotating the Entra client secret.
  -h, --help            Show this help text.

Prerequisites:
  - Apply IaC/live/azuread-applications/octelium through Terragrunt.
  - Authenticate aws CLI to read /homelab/octelium/entra/* from SSM.
  - Login to Octelium with octeliumctl for the target domain.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      domain="$2"
      shift 2
      ;;
    --aws-region)
      aws_region="$2"
      shift 2
      ;;
    --idp-name)
      idp_name="$2"
      shift 2
      ;;
    --secret-name)
      secret_name="$2"
      shift 2
      ;;
    --replace-secret)
      replace_secret="true"
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

ssm_value() {
  local name="$1"

  aws ssm get-parameter \
    --region "$aws_region" \
    --name "$name" \
    --with-decryption \
    --query Parameter.Value \
    --output text
}

require_command aws
require_command octeliumctl

client_id="$(ssm_value /homelab/octelium/entra/client-id)"
client_secret="$(ssm_value /homelab/octelium/entra/client-secret)"
issuer_url="$(ssm_value /homelab/octelium/entra/issuer-url)"

for name in client_id client_secret issuer_url; do
  value="${!name}"
  if [[ -z "$value" || "$value" == "REPLACE_ME" || "$value" == "None" ]]; then
    echo "error: ${name} is empty or still a placeholder" >&2
    exit 1
  fi
done

secret_file="$(mktemp "${TMPDIR:-/tmp}/octelium-entra-secret.XXXXXX")"
idp_file="$(mktemp "${TMPDIR:-/tmp}/octelium-entra-idp.XXXXXX")"

cleanup() {
  rm -f "$secret_file" "$idp_file"
}
trap cleanup EXIT

chmod 0600 "$secret_file" "$idp_file"
printf '%s' "$client_secret" >"$secret_file"

if octeliumctl get secret "$secret_name" --domain "$domain" >/dev/null 2>&1; then
  if [[ "$replace_secret" == "true" ]]; then
    octeliumctl delete secret "$secret_name" --domain "$domain"
    octeliumctl create secret "$secret_name" --file "$secret_file" --domain "$domain"
  else
    echo "Octelium Secret ${secret_name} already exists; leaving it unchanged."
    echo "Pass --replace-secret after Entra client-secret rotation."
  fi
else
  octeliumctl create secret "$secret_name" --file "$secret_file" --domain "$domain"
fi

cat >"$idp_file" <<EOF
kind: IdentityProvider
metadata:
  name: ${idp_name}
  displayName: Microsoft Entra
spec:
  displayName: Sign in with Microsoft
  oidc:
    issuerURL: ${issuer_url}
    clientID: ${client_id}
    clientSecret:
      fromSecret: ${secret_name}
    identifierClaim: preferred_username
    scopes:
      - profile
      - email
EOF

octeliumctl apply "$idp_file" --domain "$domain"
echo "Applied Octelium IdentityProvider ${idp_name} for ${domain}."
