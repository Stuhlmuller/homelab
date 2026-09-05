#!/usr/bin/env bash
set -euo pipefail

domain="stinkyboi.com"
zone_name="stinkyboi.com"
aws_region="us-west-2"
token_parameter="/homelab/cert-manager/cloudflare-api-token"
tunnel_id_parameter="/homelab/octelium/cloudflare-tunnel-id"
dry_run="false"

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-public-dns.sh [options]

Reconcile the public Octelium ingress route and Cloudflare DNS records.

The script reads the Cloudflare API token and Cloudflare Tunnel UUID from AWS
SSM Parameter Store. All declared hostnames, including the browser API and
native TCP carrier, become proxied CNAME records to the named Cloudflare
Tunnel. Only the declared Cordium wildcard is managed.

Options:
  --domain DOMAIN                 Octelium Cluster domain. Default: stinkyboi.com
  --zone NAME                     Cloudflare zone name. Default: stinkyboi.com
  --aws-region REGION             AWS region for SSM. Default: us-west-2
  --token-parameter NAME          SSM parameter containing the Cloudflare API token.
                                  Default: /homelab/cert-manager/cloudflare-api-token
  --tunnel-id-parameter NAME      SSM parameter containing the Cloudflare Tunnel UUID.
                                  Default: /homelab/octelium/cloudflare-tunnel-id
  --tunnel-only                   Deprecated compatibility flag; all records now use the tunnel.
  --dry-run                       Print intended DNS changes without writing.
  -h, --help                      Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      domain="$2"
      shift 2
      ;;
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
    --tunnel-id-parameter)
      tunnel_id_parameter="$2"
      shift 2
      ;;
    --tunnel-only)
      # All routes now use the tunnel.
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

tunnel_id="$(
  aws ssm get-parameter \
    --region "$aws_region" \
    --name "$tunnel_id_parameter" \
    --with-decryption \
    --query Parameter.Value \
    --output text
)"

if ! [[ "$tunnel_id" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "error: ${tunnel_id_parameter} does not look like a Cloudflare Tunnel UUID" >&2
  exit 1
fi

cf_api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local response
  local -a curl_args=(
    -fsS
    -X "$method"
    -H "Authorization: Bearer ${cloudflare_token}"
    -H "Content-Type: application/json"
  )

  if [[ -n "$data" ]]; then
    curl_args+=(--data "$data")
  fi

  if ! response="$(curl "${curl_args[@]}" "https://api.cloudflare.com/client/v4${path}")"; then
    echo "error: Cloudflare API transport failed for ${method} ${path}" >&2
    return 1
  fi

  if ! jq -e 'type == "object" and .success == true' >/dev/null 2>&1 <<<"$response"; then
    if jq -e 'type == "object" and (.errors | type) == "array"' >/dev/null 2>&1 <<<"$response"; then
      jq -r '
        .errors[]?
        | select(type == "object")
        | "Cloudflare API error \(.code // "unknown"): \(.message // "unspecified")"
      ' <<<"$response" >&2
    fi
    echo "error: Cloudflare API rejected or returned an invalid response for ${method} ${path}" >&2
    return 1
  fi

  printf '%s\n' "$response"
}

zone_id="$(
  cf_api GET "/zones?name=${zone_name}" |
    jq -er '.result[0].id'
)"

tunnel_target="${tunnel_id}.cfargotunnel.com"
api_hostname="octelium-api.${domain}"
hostnames=(
  "$domain"
  "portal.${domain}"
  "$api_hostname"
  "octelium-transport.${domain}"
  "affine.${domain}"
  "argocd.${domain}"
  "compass.${domain}"
  "cordium.${domain}"
  "*.cordium.${domain}"
  "console.${domain}"
  "deluge.${domain}"
  "dispatcharr.${domain}"
  "grafana.${domain}"
  "kiali.${domain}"
  "kubernetes-api-ci.${domain}"
  "litellm.${domain}"
  "multica.${domain}"
  "n8n.${domain}"
  "n8n-webhook.${domain}"
  "nofx.${domain}"
  "octobot.${domain}"
  "openclaw.${domain}"
  "policy-bot.${domain}"
  "policy-bot-hook.${domain}"
  "prowlarr.${domain}"
  "radarr.${domain}"
  "sonarr.${domain}"
)

if [[ "$domain" == "$zone_name" ]]; then
  hostnames+=("octelium.${domain}")
fi

# Retire the short-lived two-label CI endpoint. The certificate only covers
# first-level subdomains, so the replacement is kubernetes-api-ci.<domain>.
retired_hostnames=("kubernetes-api.ci.${domain}")

delete_exact_records() {
  local hostname="$1"
  local record_type="$2"
  local records

  records="$(
    cf_api GET "/zones/${zone_id}/dns_records?type=${record_type}&name=${hostname}" |
      jq -c '.result[]'
  )"

  if [[ -z "$records" ]]; then
    return 0
  fi

  while IFS= read -r record; do
    [[ -n "$record" ]] || continue
    local id content
    id="$(jq -r '.id' <<<"$record")"
    content="$(jq -r '.content' <<<"$record")"
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN delete ${record_type} ${hostname} ${content}"
    else
      cf_api DELETE "/zones/${zone_id}/dns_records/${id}" >/dev/null
      echo "Deleted ${record_type} ${hostname} ${content}"
    fi
  done <<<"$records"
}

upsert_record() {
  local record_type="$1"
  local hostname="$2"
  local content="$3"
  local payload records record_id

  payload="$(
    jq -cn \
      --arg type "$record_type" \
      --arg name "$hostname" \
      --arg content "$content" \
      '{type: $type, name: $name, content: $content, ttl: 1, proxied: true}'
  )"

  records="$(
    cf_api GET "/zones/${zone_id}/dns_records?type=${record_type}&name=${hostname}" |
      jq -c '.result[]'
  )"

  if [[ -z "$records" ]]; then
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN create ${record_type} ${hostname}"
    else
      cf_api POST "/zones/${zone_id}/dns_records" "$payload" >/dev/null
      echo "Created ${record_type} ${hostname}"
    fi
    return 0
  fi

  record_id="$(jq -r '.id' <<<"$(head -n 1 <<<"$records")")"
  if [[ "$dry_run" == "true" ]]; then
    echo "DRY-RUN update ${record_type} ${hostname}"
  else
    cf_api PUT "/zones/${zone_id}/dns_records/${record_id}" "$payload" >/dev/null
    echo "Updated ${record_type} ${hostname}"
  fi

  tail -n +2 <<<"$records" | while IFS= read -r extra_record; do
    [[ -n "$extra_record" ]] || continue
    local extra_id extra_content
    extra_id="$(jq -r '.id' <<<"$extra_record")"
    extra_content="$(jq -r '.content' <<<"$extra_record")"
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN delete extra ${record_type} ${hostname} ${extra_content}"
    else
      cf_api DELETE "/zones/${zone_id}/dns_records/${extra_id}" >/dev/null
      echo "Deleted extra ${record_type} ${hostname} ${extra_content}"
    fi
  done
}

for hostname in "${hostnames[@]}"; do
  delete_exact_records "$hostname" A
  delete_exact_records "$hostname" AAAA
  upsert_record CNAME "$hostname" "$tunnel_target"
done

for hostname in "${retired_hostnames[@]}"; do
  delete_exact_records "$hostname" A
  delete_exact_records "$hostname" AAAA
  delete_exact_records "$hostname" CNAME
done
