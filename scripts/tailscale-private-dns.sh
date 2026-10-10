#!/usr/bin/env bash
# Explicit mesh DNS cutover; keep legacy tunnel routing intact until acceptance.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
zone_name="stinkyboi.com"
aws_region="us-west-2"
token_parameter="/homelab/cert-manager/cloudflare-api-token"
dry_run="true"
expected_sha=""

usage() {
  cat <<'USAGE'
Usage: scripts/tailscale-private-dns.sh [--dry-run | --execute --expected-sha SHA]

Preview the fixed private DNS inventory by default. Execution requires a clean
checkout at reviewed current main and a ready, reachable Traefik mesh service.
Cloudflare stores DNS-only A/AAAA records from the verified ingress Service; no Cloudflare Tunnel routing is configured.
This preparation helper cannot retire the legacy CI, callback, or carrier DNS.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run="true"; shift ;;
    --execute) dry_run="false"; shift ;;
    --expected-sha) expected_sha="${2:?Missing expected SHA}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

for command in aws curl jq python3; do
  command -v "$command" >/dev/null || { echo "error: $command is required" >&2; exit 127; }
done

preflight=(python3 -I "$root/scripts/tailscale-private-dns-check.py")
if [[ "$dry_run" == "false" ]]; then
  mesh="$("${preflight[@]}" --execute --expected-sha "$expected_sha" --addresses-json)"
else
  mesh="$("${preflight[@]}" --addresses-json)"
fi

cloudflare_token="$(aws ssm get-parameter --region "$aws_region" --name "$token_parameter" \
  --with-decryption --query Parameter.Value --output text)"

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

zone_response="$(cf_api GET "/zones?name=${zone_name}")"
zone_id="$(jq -er --arg name "$zone_name" '.result | select(length == 1) | .[0] | select(.name == $name) | .id' <<<"$zone_response")"
inventory="$root/scripts/config/tailscale-private-dns.json"
desired="$(jq -ce '[.addresses | to_entries[] | .key as $type | .value[] | {type:$type,content:.}] | sort_by(.type) | select(length > 0)' <<<"$mesh")"
previous_ttl="$(jq -er '.previous_ttl | select(type == "number" and . >= 0)' <<<"$mesh")"
echo "Observed authoritative cache TTL before cutover: ${previous_ttl} seconds"

records_for() {
  local hostname="$1" encoded response
  encoded="$(jq -rn --arg name "$hostname" '$name | @uri')"
  response="$(cf_api GET "/zones/${zone_id}/dns_records?name=${encoded}&per_page=100")"
  # Refuse incomplete pagination, unexpected names, or response shapes before any write.
  jq -ce --arg name "$hostname" '
    select(.result | type == "array") |
    select(.result_info.total_count == (.result | length)) |
    [.result[] | select(.type == "A" or .type == "AAAA" or .type == "CNAME")] |
    select(all(.[]; .name == $name and (.id | type == "string")))' <<<"$response"
}

# Snapshot every changing name before writes. Legacy CI/callback/carrier names stay
# intact until their clients have separately passed final retirement acceptance.
private_dir="$(mktemp -d)"
chmod 700 "$private_dir"
trap 'rm -rf -- "$private_dir"' EXIT
while IFS= read -r hostname; do
  records_for "$hostname" >"$private_dir/$hostname.json"
done < <(jq -r '.hostnames[]' "$inventory")

delete_record() {
  local hostname="$1" record="$2" id type
  id="$(jq -er '.id' <<<"$record")"
  type="$(jq -er '.type' <<<"$record")"
  if [[ "$dry_run" == "true" ]]; then
    echo "DRY-RUN delete ${type} ${hostname}"
  else
    cf_api DELETE "/zones/${zone_id}/dns_records/${id}" >/dev/null
  fi
}

while IFS= read -r hostname; do
  current="$(cat "$private_dir/$hostname.json")"
  # Reuse the CNAME id for the first address: Cloudflare forbids CNAME/address coexistence.
  plan="$(jq -cn --argjson current "$current" --argjson desired "$desired" '
    $desired | to_entries | map(.key as $index | .value | .type as $type |
      . + {id: ([$current[] | select(.type == $type)][0].id //
        (if $index == 0 then [$current[] | select(.type == "CNAME")][0].id else null end))})')"
  while IFS= read -r record; do
    [[ -n "$record" ]] && delete_record "$hostname" "$record"
  done < <(jq -c --argjson plan "$plan" '.[] | select(.id as $id | all($plan[]; .id != $id))' <<<"$current")
  while IFS= read -r record; do
    keep_id="$(jq -r '.id // empty' <<<"$record")"
    payload="$(jq -c --arg name "$hostname" 'del(.id) + {name:$name,ttl:60,proxied:false}' <<<"$record")"
    if [[ "$dry_run" == "true" ]]; then
      echo "DRY-RUN set DNS-only ${hostname} $(jq -r '.type + " " + .content' <<<"$record")"
    elif ! jq -e --arg keep "$keep_id" --argjson wanted "$payload" 'any(.[];
      .id == $keep and .type == $wanted.type and .content == $wanted.content and .proxied == false and .ttl == 60)' <<<"$current" >/dev/null; then
      if [[ -n "$keep_id" ]]; then
        cf_api PUT "/zones/${zone_id}/dns_records/${keep_id}" "$payload" >/dev/null
      else
        cf_api POST "/zones/${zone_id}/dns_records" "$payload" >/dev/null
      fi
    fi
  done < <(jq -c '.[]' <<<"$plan")
  if [[ "$dry_run" == "false" ]]; then
    records_for "$hostname" | jq -e --argjson desired "$desired" '
      all(.[]; .proxied == false and .ttl == 60) and
      ([.[] | {type,content}] | sort_by(.type)) == $desired' >/dev/null
    echo "Verified DNS-only mesh route: ${hostname}"
  fi
done < <(jq -r '.hostnames[]' "$inventory")

echo "Legacy CI, callback, and carrier DNS records preserved for separate final retirement."

if [[ "$dry_run" == "false" ]]; then
  echo "DNS records updated. Keep the old tunnel running for at least ${previous_ttl} seconds from now."
  echo "Then require authoritative/client DNS checks and authenticated clients before tunnel retirement."
  echo "After local carrier migration, run: python3 -I scripts/tailscale-private-dns-check.py --verify-dns"
fi
