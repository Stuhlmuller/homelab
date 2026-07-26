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

Reconcile Cloudflare DNS records for the public Octelium control plane,
public app hostnames, and reviewed callback hostnames.

The script reads the Cloudflare API token and Cloudflare Tunnel UUID from AWS
SSM Parameter Store, removes exact A/AAAA records for the Octelium control-plane
hostnames, and creates exact proxied CNAME records pointing at the named tunnel
target. It does not touch wildcard records.

Options:
  --domain DOMAIN                 Octelium Cluster domain. Default: stinkyboi.com
  --zone NAME                     Cloudflare zone name. Default: stinkyboi.com
  --aws-region REGION             AWS region for SSM. Default: us-west-2
  --token-parameter NAME          SSM parameter containing the Cloudflare API token.
                                  Default: /homelab/cert-manager/cloudflare-api-token
  --tunnel-id-parameter NAME      SSM parameter containing the Cloudflare Tunnel UUID.
                                  Default: /homelab/octelium/cloudflare-tunnel-id
  --dry-run                       Print intended changes without writing Cloudflare DNS.
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

tunnel_target="${tunnel_id}.cfargotunnel.com"
hostnames=(
  "$domain"
  "portal.${domain}"
  "octelium-api.${domain}"
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
  "litellm.${domain}"
  "n8n.${domain}"
  "n8n-webhook.${domain}"
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

upsert_cname_record() {
  local hostname="$1"
  local payload records record_id

  payload="$(
    jq -cn \
      --arg type "CNAME" \
      --arg name "$hostname" \
      --arg content "$tunnel_target" \
      '{type: $type, name: $name, content: $content, ttl: 1, proxied: true}'
  )"

  records="$(
    cf_api GET "/zones/${zone_id}/dns_records?type=CNAME&name=${hostname}" |
      jq -c '.result[]'
  )"

  if [[ -z "$records" ]]; then
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN create CNAME ${hostname} ${tunnel_target}"
    else
      cf_api POST "/zones/${zone_id}/dns_records" "$payload" >/dev/null
      echo "Created CNAME ${hostname} ${tunnel_target}"
    fi
    return 0
  fi

  record_id="$(jq -r '.id' <<<"$(head -n 1 <<<"$records")")"
  if [[ "$dry_run" == "true" ]]; then
    echo "DRY-RUN update CNAME ${hostname} ${tunnel_target}"
  else
    cf_api PUT "/zones/${zone_id}/dns_records/${record_id}" "$payload" >/dev/null
    echo "Updated CNAME ${hostname} ${tunnel_target}"
  fi

  tail -n +2 <<<"$records" | while IFS= read -r extra_record; do
    [[ -n "$extra_record" ]] || continue
    local extra_id extra_content
    extra_id="$(jq -r '.id' <<<"$extra_record")"
    extra_content="$(jq -r '.content' <<<"$extra_record")"
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN delete extra CNAME ${hostname} ${extra_content}"
    else
      cf_api DELETE "/zones/${zone_id}/dns_records/${extra_id}" >/dev/null
      echo "Deleted extra CNAME ${hostname} ${extra_content}"
    fi
  done
}

for hostname in "${hostnames[@]}"; do
  delete_exact_records "$hostname" A
  delete_exact_records "$hostname" AAAA
  upsert_cname_record "$hostname"
done
