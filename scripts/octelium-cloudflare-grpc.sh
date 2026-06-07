#!/usr/bin/env bash
set -euo pipefail

zone_name="stinkyboi.com"
aws_region="us-west-2"
token_parameter="/homelab/octelium/cloudflare-zone-settings-token"
dry_run="false"

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-cloudflare-grpc.sh [options]

Enable and verify the Cloudflare zone gRPC setting required by the Octelium
public API hostname.

The script reads a Cloudflare API token from AWS SSM Parameter Store. That token
must have Zone:Read and Zone Settings:Edit permissions for the target zone. The
cert-manager DNS-01 token is intentionally not enough for this operation.

Options:
  --zone NAME              Cloudflare zone name. Default: stinkyboi.com
  --aws-region REGION      AWS region for SSM. Default: us-west-2
  --token-parameter NAME   SSM parameter containing the Cloudflare API token.
                           Default: /homelab/octelium/cloudflare-zone-settings-token
  --dry-run                Read the current setting without writing Cloudflare.
  -h, --help               Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --zone)
      zone_name="$2"
      shift 2
      ;;
    --aws-region)
      aws_region="$2"
      shift 2
      ;;
    --token-parameter)
      token_parameter="$2"
      shift 2
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

require_command aws
require_command curl
require_command jq

cloudflare_token="$(
  aws ssm get-parameter \
    --region "$aws_region" \
    --name "$token_parameter" \
    --with-decryption \
    --query Parameter.Value \
    --output text
)"

if [[ -z "$cloudflare_token" || "$cloudflare_token" == "REPLACE_ME" ]]; then
  echo "error: ${token_parameter} must contain a real Cloudflare API token" >&2
  exit 1
fi

cf_api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"

  if [[ -n "$data" ]]; then
    curl -fsS \
      -X "$method" \
      -H "Authorization: Bearer ${cloudflare_token}" \
      -H "Content-Type: application/json" \
      --data "$data" \
      "https://api.cloudflare.com/client/v4${path}"
  else
    curl -fsS \
      -X "$method" \
      -H "Authorization: Bearer ${cloudflare_token}" \
      -H "Content-Type: application/json" \
      "https://api.cloudflare.com/client/v4${path}"
  fi
}

zone_id="$(
  cf_api GET "/zones?name=${zone_name}" |
    jq -er '.result[0].id'
)"

current_value="$(
  cf_api GET "/zones/${zone_id}/settings/grpc" |
    jq -er '.result.value'
)"

if [[ "$dry_run" == "true" ]]; then
  echo "DRY-RUN Cloudflare gRPC setting for ${zone_name}: ${current_value}"
  exit 0
fi

if [[ "$current_value" == "on" ]]; then
  echo "Cloudflare gRPC setting for ${zone_name} is already on"
  exit 0
fi

cf_api PATCH "/zones/${zone_id}/settings/grpc" '{"value":"on"}' >/dev/null

updated_value="$(
  cf_api GET "/zones/${zone_id}/settings/grpc" |
    jq -er '.result.value'
)"

if [[ "$updated_value" != "on" ]]; then
  echo "error: Cloudflare gRPC setting for ${zone_name} is ${updated_value}, expected on" >&2
  exit 1
fi

echo "Enabled Cloudflare gRPC setting for ${zone_name}"
