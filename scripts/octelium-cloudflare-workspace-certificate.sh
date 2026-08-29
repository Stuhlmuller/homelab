#!/usr/bin/env bash
set -euo pipefail

zone_name="stinkyboi.com"
workspace_wildcard="*.cordium.stinkyboi.com"
probe_hostname="tls-audit.cordium.stinkyboi.com"
action="${1:-check}"
token="${CLOUDFLARE_SSL_CERTIFICATES_TOKEN:-}"

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-cloudflare-workspace-certificate.sh [check|apply]

Check or order the Cloudflare Advanced Certificate Manager certificate pack
for Cordium workspace hostnames. The zone must already have the paid Advanced
Certificate Manager add-on.
USAGE
}

if [[ "$action" == "-h" || "$action" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$action" != "check" && "$action" != "apply" ]]; then
  echo "error: action must be check or apply" >&2
  exit 2
fi

if [[ -z "$token" || "$token" == "REPLACE_ME" ]]; then
  echo "error: CLOUDFLARE_SSL_CERTIFICATES_TOKEN is required" >&2
  exit 1
fi

cf_api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local response

  if [[ -n "$data" ]]; then
    response="$(
      curl -sS \
        --connect-timeout 10 \
        --max-time 45 \
        -X "$method" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$data" \
        "https://api.cloudflare.com/client/v4${path}"
    )"
  else
    response="$(
      curl -sS \
        --connect-timeout 10 \
        --max-time 45 \
        -X "$method" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        "https://api.cloudflare.com/client/v4${path}"
    )"
  fi

  if ! jq -e '.success == true' >/dev/null <<<"$response"; then
    jq -r '.errors[]? | "Cloudflare API error \(.code): \(.message)"' <<<"$response" >&2
    return 1
  fi

  printf '%s\n' "$response"
}

desired_hosts="$(
  jq -cn \
    --arg apex "$zone_name" \
    --arg first_level "*.${zone_name}" \
    --arg workspace "$workspace_wildcard" \
    '[$apex, $first_level, $workspace]'
)"

zone_id="$(
  cf_api GET "/zones?name=${zone_name}" |
    jq -er '.result[0].id'
)"
packs="$(cf_api GET "/zones/${zone_id}/ssl/certificate_packs?status=all&per_page=50")"
host_pack="$(
  jq -c \
    --argjson desired "$desired_hosts" \
    'first(.result[]? | select(
      .type == "advanced" and
      ((.hosts | sort) == ($desired | sort)) and
      .status != "deleted" and
      .status != "pending_deletion"
    )) // empty' \
    <<<"$packs"
)"
pack="$(
  jq -c \
    --argjson desired "$desired_hosts" \
    '[.result[]? | select(
      .type == "advanced" and
      ((.hosts | sort) == ($desired | sort)) and
      .certificate_authority == "lets_encrypt" and
      .validation_method == "txt" and
      .validity_days == 90 and
      .cloudflare_branding == false and
      .status != "deleted" and
      .status != "pending_deletion"
    )] |
    (first(.[] | select(.status == "active")) // first(.[]) // empty)' \
    <<<"$packs"
)"

if [[ -z "$pack" && -n "$host_pack" ]]; then
  echo "error: the Cordium workspace certificate host set exists with unexpected settings" >&2
  exit 1
fi

if [[ -z "$pack" ]]; then
  if [[ "$action" == "check" ]]; then
    echo "error: no Advanced certificate pack owns the exact Cordium workspace TLS host set" >&2
    exit 1
  fi

  payload="$(
    jq -cn \
      --argjson hosts "$desired_hosts" \
      '{
        type: "advanced",
        hosts: $hosts,
        certificate_authority: "lets_encrypt",
        validation_method: "txt",
        validity_days: 90,
        cloudflare_branding: false
      }'
  )"
  created="$(cf_api POST "/zones/${zone_id}/ssl/certificate_packs/order" "$payload")"
  jq -r '"Ordered Cloudflare Advanced certificate pack \(.result.id) with status \(.result.status). Rerun check after deployment."' <<<"$created"
  exit 0
fi

pack_id="$(jq -r '.id' <<<"$pack")"
pack_status="$(jq -r '.status' <<<"$pack")"

if [[ "$action" == "apply" && "$pack_status" == "validation_timed_out" ]]; then
  restarted="$(cf_api PATCH "/zones/${zone_id}/ssl/certificate_packs/${pack_id}" '{}')"
  jq -r '"Restarted validation for Cloudflare Advanced certificate pack \(.result.id); status is \(.result.status)."' <<<"$restarted"
  exit 0
fi

if [[ "$pack_status" != "active" ]]; then
  echo "error: Cloudflare Advanced certificate pack ${pack_id} is ${pack_status}, not active" >&2
  exit 1
fi

curl -sS -I --connect-timeout 10 --max-time 20 -o /dev/null "https://${probe_hostname}/"
echo "Verified active Cloudflare Advanced certificate pack ${pack_id} and public TLS for ${probe_hostname}"
