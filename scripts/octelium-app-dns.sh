#!/usr/bin/env bash
set -euo pipefail

domain="stinkyboi.com"
zone_name="stinkyboi.com"
aws_region="us-west-2"
token_parameter="/homelab/cert-manager/cloudflare-api-token"
dry_run="false"
gateway_service="homelab-app-gateway.homelab"

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-app-dns.sh [options]

Reconcile exact Cloudflare DNS records for app hostnames served by Octelium.

The script reads the Cloudflare API token from AWS SSM Parameter Store, queries
Octelium Service status, and creates exact A and AAAA records for hostnames
declared in spec.attrs.appHostname, such as grafana.stinkyboi.com. Those records
point at a shared Octelium private app-gateway service address so the normal app
FQDNs route through authenticated Octelium VPN sessions while Istio keeps doing
hostname/SNI routing behind that single address.

Options:
  --domain DOMAIN             Octelium Cluster domain. Default: stinkyboi.com
  --zone NAME                 Cloudflare zone name. Default: stinkyboi.com
  --aws-region REGION         AWS region for SSM. Default: us-west-2
  --token-parameter NAME      SSM parameter containing the Cloudflare API token.
                              Default: /homelab/cert-manager/cloudflare-api-token
  --gateway-service NAME      Octelium TCP Service whose address should back all
                              app hostnames. Default: homelab-app-gateway.homelab
  --dry-run                   Print intended changes without writing Cloudflare DNS.
  -h, --help                  Show this help.
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
    --gateway-service)
      gateway_service="$2"
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
require_command octeliumctl

cloudflare_token="$(
  aws ssm get-parameter \
    --region "$aws_region" \
    --name "$token_parameter" \
    --with-decryption \
    --query Parameter.Value \
    --output text
)"

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

services_json="$(octeliumctl get service --domain "$domain" -o json)"

gateway_record="$(
  jq -r --arg service "$gateway_service" '
    .items[]
    | select(.metadata.name == $service)
    | .status.addresses[0].dualStackIP.ipv4 as $ipv4
    | .status.addresses[0].dualStackIP.ipv6 as $ipv6
    | select(($ipv4 | startswith("100.64.")) and ($ipv6 | startswith("fdee:")))
    | [$ipv4, $ipv6]
    | @tsv
  ' <<<"$services_json"
)"

if [[ -z "$gateway_record" ]]; then
  echo "error: no Octelium gateway service address found for ${gateway_service}" >&2
  exit 1
fi
IFS=$'\t' read -r gateway_ipv4 gateway_ipv6 <<<"$gateway_record"

app_records=()
while IFS= read -r app_record; do
  [[ -n "$app_record" ]] || continue
  app_records+=("$app_record")
done < <(
  jq -r --arg zone "$zone_name" '
    .items[]
    | (.spec.attrs.appHostname // "") as $hostname
    | select($hostname | endswith("." + $zone))
    | $hostname
  ' <<<"$services_json"
)

if [[ "${#app_records[@]}" -eq 0 ]]; then
  echo "error: no Octelium app service addresses found for ${zone_name}" >&2
  exit 1
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
      '{type: $type, name: $name, content: $content, ttl: 300, proxied: false}'
  )"

  records="$(
    cf_api GET "/zones/${zone_id}/dns_records?type=${record_type}&name=${hostname}" |
      jq -c '.result[]'
  )"

  if [[ -z "$records" ]]; then
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN create ${record_type} ${hostname} ${content}"
    else
      cf_api POST "/zones/${zone_id}/dns_records" "$payload" >/dev/null
      echo "Created ${record_type} ${hostname} ${content}"
    fi
    return 0
  fi

  record_id="$(jq -r '.id' <<<"$(head -n 1 <<<"$records")")"
  if [[ "$dry_run" == "true" ]]; then
    echo "DRY-RUN update ${record_type} ${hostname} ${content}"
  else
    cf_api PUT "/zones/${zone_id}/dns_records/${record_id}" "$payload" >/dev/null
    echo "Updated ${record_type} ${hostname} ${content}"
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

for app_record in "${app_records[@]}"; do
  hostname="$app_record"

  delete_exact_records "$hostname" CNAME
  upsert_record A "$hostname" "$gateway_ipv4"
  upsert_record AAAA "$hostname" "$gateway_ipv6"
done
