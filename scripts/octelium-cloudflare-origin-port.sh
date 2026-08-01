#!/usr/bin/env bash
set -euo pipefail

zone_name="stinkyboi.com"
api_hostname="octelium-api.stinkyboi.com"
origin_port=8443
rule_description="Octelium API origin port"
token="${CLOUDFLARE_ZONE_SETTINGS_TOKEN:-}"

if [[ -z "$token" || "$token" == "REPLACE_ME" ]]; then
  echo "error: CLOUDFLARE_ZONE_SETTINGS_TOKEN is required" >&2
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
        -X "$method" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        --data "$data" \
        "https://api.cloudflare.com/client/v4${path}"
    )"
  else
    response="$(
      curl -sS \
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

zone_id="$(
  cf_api GET "/zones?name=${zone_name}" |
    jq -er '.result[0].id'
)"

rulesets="$(cf_api GET "/zones/${zone_id}/rulesets")"
ruleset_id="$(
  jq -r \
    'first(.result[] | select(.kind == "zone" and .phase == "http_request_origin") | .id) // ""' \
    <<<"$rulesets"
)"

rule_payload="$(
  jq -cn \
    --arg description "$rule_description" \
    --arg host "$api_hostname" \
    --argjson port "$origin_port" \
    '{
      action: "route",
      action_parameters: {origin: {port: $port}},
      expression: ("(http.host eq \"" + $host + "\")"),
      description: $description,
      enabled: true
    }'
)"

if [[ -z "$ruleset_id" ]]; then
  create_payload="$(
    jq -cn \
      --argjson rule "$rule_payload" \
      '{
        name: "Homelab origin overrides",
        kind: "zone",
        phase: "http_request_origin",
        rules: [$rule]
      }'
  )"
  created="$(cf_api POST "/zones/${zone_id}/rulesets" "$create_payload")"
  ruleset_id="$(jq -er '.result.id' <<<"$created")"
  echo "Created Cloudflare Origin Rule for ${api_hostname} -> TCP/${origin_port}"
else
  ruleset="$(cf_api GET "/zones/${zone_id}/rulesets/${ruleset_id}")"
  rule_id="$(
    jq -r \
      --arg description "$rule_description" \
      'first(.result.rules[]? | select(.description == $description) | .id) // ""' \
      <<<"$ruleset"
  )"

  if [[ -z "$rule_id" ]]; then
    cf_api POST "/zones/${zone_id}/rulesets/${ruleset_id}/rules" "$rule_payload" >/dev/null
    echo "Added Cloudflare Origin Rule for ${api_hostname} -> TCP/${origin_port}"
  else
    cf_api PATCH "/zones/${zone_id}/rulesets/${ruleset_id}/rules/${rule_id}" "$rule_payload" >/dev/null
    echo "Updated Cloudflare Origin Rule for ${api_hostname} -> TCP/${origin_port}"
  fi
fi

verified="$(cf_api GET "/zones/${zone_id}/rulesets/${ruleset_id}")"
jq -e \
  --arg description "$rule_description" \
  --arg host "$api_hostname" \
  --argjson port "$origin_port" \
  'any(
    .result.rules[]?;
    .description == $description and
    .enabled == true and
    .action == "route" and
    .action_parameters.origin.port == $port and
    .expression == ("(http.host eq \"" + $host + "\")")
  )' >/dev/null <<<"$verified"

echo "Verified Cloudflare Origin Rule for ${api_hostname} -> TCP/${origin_port}"
