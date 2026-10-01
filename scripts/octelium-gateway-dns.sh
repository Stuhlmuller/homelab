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
Octelium Gateway status, and creates exact A and AAAA records for the advertised
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
    | [$hostname, (if test(":") then "AAAA" else "A" end), .]
    | @tsv
  ' <<<"$gateways_json"
)

if [[ "${#gateway_records[@]}" -eq 0 ]]; then
  echo "error: no Octelium gateway addresses found for ${domain}" >&2
  exit 1
fi

# Reconcile each hostname/type as a set: gateways can advertise multiple IPs.
reconcile_records() {
  local hostname="$1" record_type="$2" desired="$3"
  local records address record payload id content
  records="$(cf_api GET "/zones/${zone_id}/dns_records?type=${record_type}&name=${hostname}" | jq -c '.result')"
  while IFS= read -r address; do
    [[ -n "$address" ]] || continue
    payload="$(jq -cn --arg type "$record_type" --arg name "$hostname" --arg content "$address" \
      '{type: $type, name: $name, content: $content, ttl: 300, proxied: false}')"
    record="$(jq -c --arg address "$address" '[.[] | select(.content == $address)][0] // empty' <<<"$records")"
    if [[ -z "$record" ]]; then
      if [[ "$dry_run" == "true" ]]; then
        echo "DRY-RUN create ${record_type} ${hostname} ${address}"
      else
        cf_api POST "/zones/${zone_id}/dns_records" "$payload" >/dev/null
        echo "Created ${record_type} ${hostname} ${address}"
      fi
    elif ! jq -e '.proxied == false and .ttl == 300' >/dev/null <<<"$record"; then
      id="$(jq -r '.id' <<<"$record")"
      if [[ "$dry_run" == "true" ]]; then
        echo "DRY-RUN update ${record_type} ${hostname} ${address}"
      else
        cf_api PUT "/zones/${zone_id}/dns_records/${id}" "$payload" >/dev/null
        echo "Updated ${record_type} ${hostname} ${address}"
      fi
    fi
  done < <(jq -r '.[]' <<<"$desired")

  # Publish replacements before deleting obsolete addresses.
  while IFS= read -r record; do
    [[ -n "$record" ]] || continue
    id="$(jq -r '.id' <<<"$record")"
    content="$(jq -r '.content' <<<"$record")"
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN delete ${record_type} ${hostname} ${content}"
    else
      cf_api DELETE "/zones/${zone_id}/dns_records/${id}" >/dev/null
      echo "Deleted ${record_type} ${hostname} ${content}"
    fi
  done < <(jq -c --argjson desired "$desired" \
    'group_by(.content)[] | if (.[0].content as $ip | $desired | index($ip)) == null then .[] else .[1:][] end' <<<"$records")
}

records_json="$(printf '%s\n' "${gateway_records[@]}" | jq -Rn '[inputs | split("\t")] | unique')"
while IFS= read -r hostname; do
  for record_type in A AAAA; do
    desired="$(jq -c --arg hostname "$hostname" --arg type "$record_type" \
      '[.[] | select(.[0] == $hostname and .[1] == $type) | .[2]] | unique' <<<"$records_json")"
    reconcile_records "$hostname" "$record_type" "$desired"
  done
done < <(jq -r 'map(.[0]) | unique[]' <<<"$records_json")
