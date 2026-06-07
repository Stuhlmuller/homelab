#!/usr/bin/env bash
set -euo pipefail

domain="stinkyboi.com"
zone_name="stinkyboi.com"
aws_region="us-west-2"
token_parameter="/homelab/cert-manager/cloudflare-api-token"
dry_run="false"

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-gateway-dns.sh [options]

Reconcile Cloudflare DNS records for Octelium gateway hostnames.

The script reads the Cloudflare API token from AWS SSM Parameter Store, queries
Octelium Gateway status, and creates exact AAAA records for the advertised
_gw-* hostnames. Exact gateway records prevent those names from falling through
to a wildcard A record that points at the tailnet.

Options:
  --domain DOMAIN             Octelium Cluster domain. Default: stinkyboi.com
  --zone NAME                 Cloudflare zone name. Default: stinkyboi.com
  --aws-region REGION         AWS region for SSM. Default: us-west-2
  --token-parameter NAME      SSM parameter containing the Cloudflare API token.
                              Default: /homelab/cert-manager/cloudflare-api-token
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

gateways_json="$(octeliumctl get gateway --domain "$domain" -o json)"

gateway_records=()
while IFS= read -r gateway_record; do
  [[ -n "$gateway_record" ]] || continue
  gateway_records+=("$gateway_record")
done < <(
  jq -r '
    .items[]
    | .status.hostname as $hostname
    | .status.publicIPs[]?
    | select(test(":"))
    | [$hostname, .]
    | @tsv
  ' <<<"$gateways_json"
)

if [[ "${#gateway_records[@]}" -eq 0 ]]; then
  echo "error: no Octelium gateway IPv6 addresses found for ${domain}" >&2
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

upsert_aaaa_record() {
  local hostname="$1"
  local ipv6="$2"
  local payload records record_id

  payload="$(
    jq -cn \
      --arg type "AAAA" \
      --arg name "$hostname" \
      --arg content "$ipv6" \
      '{type: $type, name: $name, content: $content, ttl: 300, proxied: false}'
  )"

  records="$(
    cf_api GET "/zones/${zone_id}/dns_records?type=AAAA&name=${hostname}" |
      jq -c '.result[]'
  )"

  if [[ -z "$records" ]]; then
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN create AAAA ${hostname} ${ipv6}"
    else
      cf_api POST "/zones/${zone_id}/dns_records" "$payload" >/dev/null
      echo "Created AAAA ${hostname} ${ipv6}"
    fi
    return 0
  fi

  record_id="$(jq -r '.id' <<<"$(head -n 1 <<<"$records")")"
  if [[ "$dry_run" == "true" ]]; then
    echo "DRY-RUN update AAAA ${hostname} ${ipv6}"
  else
    cf_api PUT "/zones/${zone_id}/dns_records/${record_id}" "$payload" >/dev/null
    echo "Updated AAAA ${hostname} ${ipv6}"
  fi

  tail -n +2 <<<"$records" | while IFS= read -r extra_record; do
    [[ -n "$extra_record" ]] || continue
    local extra_id extra_content
    extra_id="$(jq -r '.id' <<<"$extra_record")"
    extra_content="$(jq -r '.content' <<<"$extra_record")"
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN delete extra AAAA ${hostname} ${extra_content}"
    else
      cf_api DELETE "/zones/${zone_id}/dns_records/${extra_id}" >/dev/null
      echo "Deleted extra AAAA ${hostname} ${extra_content}"
    fi
  done
}

for gateway_record in "${gateway_records[@]}"; do
  hostname="${gateway_record%%$'\t'*}"
  ipv6="${gateway_record#*$'\t'}"

  delete_exact_records "$hostname" A
  upsert_aaaa_record "$hostname" "$ipv6"
done
