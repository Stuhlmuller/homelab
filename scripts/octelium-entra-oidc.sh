#!/usr/bin/env bash
set -euo pipefail

domain="stinkyboi.com"
region="us-west-2"
idp_name="entra"
idp_display_name="Login with Microsoft Entra"
secret_name="entra-oidc-client-secret"
client_id_parameter="/homelab/octelium/entra/client-id"
client_secret_parameter="/homelab/octelium/entra/client-secret"
issuer_url_parameter="/homelab/octelium/entra/issuer-url"
admin_user_name=""
admin_email=""

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-entra-oidc.sh [options]

Configures the Octelium Microsoft Entra OIDC IdentityProvider from the
Terragrunt-managed SSM parameters. The client secret is copied into an
Octelium native Secret and is never written to git.

Options:
  --domain DOMAIN                    Octelium Cluster domain. Default: stinkyboi.com
  --region REGION                    AWS region for SSM. Default: us-west-2
  --idp-name NAME                    Octelium IdentityProvider name. Default: entra
  --secret-name NAME                 Octelium Secret name for the client secret.
                                     Default: entra-oidc-client-secret
  --client-id-parameter NAME         SSM parameter containing the client ID.
  --client-secret-parameter NAME     SSM parameter containing the client secret.
  --issuer-url-parameter NAME        SSM parameter containing the issuer URL.
  --admin-user-name NAME             Optional HUMAN user name to apply.
  --admin-email EMAIL                Optional Entra identifier for the HUMAN user.
  -h, --help                         Show this help.

If --admin-user-name and --admin-email are both set, the script also applies a
HUMAN user with an explicit Entra identity and the built-in allow-all policy.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      domain="$2"
      shift 2
      ;;
    --region)
      region="$2"
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
    --client-id-parameter)
      client_id_parameter="$2"
      shift 2
      ;;
    --client-secret-parameter)
      client_secret_parameter="$2"
      shift 2
      ;;
    --issuer-url-parameter)
      issuer_url_parameter="$2"
      shift 2
      ;;
    --admin-user-name)
      admin_user_name="$2"
      shift 2
      ;;
    --admin-email)
      admin_email="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown option $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 1
  fi
}

validate_name() {
  local value="$1"
  local label="$2"
  if [[ ! "$value" =~ ^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$ ]]; then
    echo "error: $label must use lowercase DNS-style characters: $value" >&2
    exit 1
  fi
}

validate_email() {
  local value="$1"
  if [[ ! "$value" =~ ^[^[:space:]\"\'\<\>]+@[^[:space:]\"\'\<\>]+$ ]]; then
    echo "error: --admin-email does not look like a safe email identifier" >&2
    exit 1
  fi
}

read_parameter() {
  local name="$1"
  aws ssm get-parameter \
    --region "$region" \
    --name "$name" \
    --with-decryption \
    --query 'Parameter.Value' \
    --output text
}

apply_identity_resources() {
  local apply_output

  if ! apply_output="$(octeliumctl apply --domain "$domain" "$identity_file" 2>&1)"; then
    printf '%s\n' "$apply_output" >&2
    exit 1
  fi

  printf '%s\n' "$apply_output"

  if grep -Eq '(^|[[:space:]])Could not (create|update|apply)|gRPC error' <<<"$apply_output"; then
    echo "error: octeliumctl reported one or more failed resource changes" >&2
    exit 1
  fi
}

require_command aws
require_command octeliumctl
validate_name "$idp_name" "--idp-name"
validate_name "$secret_name" "--secret-name"
if [[ -n "$admin_user_name" ]]; then
  validate_name "$admin_user_name" "--admin-user-name"
fi
if [[ -n "$admin_email" ]]; then
  validate_email "$admin_email"
fi
if [[ -n "$admin_user_name" && -z "$admin_email" ]] || [[ -z "$admin_user_name" && -n "$admin_email" ]]; then
  echo "error: --admin-user-name and --admin-email must be supplied together" >&2
  exit 1
fi

client_id="$(read_parameter "$client_id_parameter")"
client_secret="$(read_parameter "$client_secret_parameter")"
issuer_url="$(read_parameter "$issuer_url_parameter")"

for pair in \
  "client ID:$client_id" \
  "client secret:$client_secret" \
  "issuer URL:$issuer_url"
do
  label="${pair%%:*}"
  value="${pair#*:}"
  if [[ -z "$value" || "$value" == "REPLACE_ME" ]]; then
    echo "error: SSM returned an empty or placeholder $label" >&2
    exit 1
  fi
done

identity_file="$(mktemp "${TMPDIR:-/tmp}/octelium-entra-identity.XXXXXX.yaml")"
chmod 600 "$identity_file"
trap 'rm -f "$identity_file"' EXIT

if octeliumctl get secret "$secret_name" --domain "$domain" >/dev/null 2>&1; then
  printf '%s' "$client_secret" | octeliumctl update secret "$secret_name" --domain "$domain" --file - >/dev/null
else
  printf '%s' "$client_secret" | octeliumctl create secret "$secret_name" --domain "$domain" --file - >/dev/null
fi

cat >"$identity_file" <<YAML
kind: IdentityProvider
metadata:
  name: ${idp_name}
  displayName: Microsoft Entra
spec:
  displayName: ${idp_display_name}
  oidc:
    issuerURL: ${issuer_url}
    clientID: ${client_id}
    clientSecret:
      fromSecret: ${secret_name}
    identifierClaim: preferred_username
    scopes:
      - openid
      - email
      - profile
YAML

if [[ -n "$admin_user_name" ]]; then
  cat >>"$identity_file" <<YAML
---
kind: User
metadata:
  name: ${admin_user_name}
spec:
  type: HUMAN
  email: ${admin_email}
  authentication:
    identities:
      - identityProvider: ${idp_name}
        identifier: ${admin_email}
  authorization:
    policies:
      - allow-all
YAML
fi

apply_identity_resources

echo "Configured Octelium IdentityProvider ${idp_name} for ${domain}."
if [[ -n "$admin_user_name" ]]; then
  echo "Applied HUMAN user ${admin_user_name} with Entra identifier ${admin_email}."
fi
