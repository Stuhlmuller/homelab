#!/usr/bin/env bash
set -euo pipefail

zone_name="stinkyboi.com"
api_hostname="octelium-api.stinkyboi.com"
origin_port=8443
rule_description="Octelium API origin port"
tls_rule_description="Octelium API origin TLS"
token="${CLOUDFLARE_ZONE_SETTINGS_TOKEN:-}"
action="${1:-apply}"

if [[ -z "$token" || "$token" == "REPLACE_ME" ]]; then
  echo "error: CLOUDFLARE_ZONE_SETTINGS_TOKEN is required" >&2
  exit 1
fi

if [[ "$action" != "apply" && "$action" != "remove" ]]; then
  echo "error: action must be apply or remove" >&2
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
tls_ruleset_id="$(
  jq -r \
    'first(.result[] | select(.kind == "zone" and .phase == "http_config_settings") | .id) // ""' \
    <<<"$rulesets"
)"

if [[ -n "$ruleset_id" ]]; then
  ruleset="$(cf_api GET "/zones/${zone_id}/rulesets/${ruleset_id}")"
  rule_id="$(
    jq -r \
      --arg description "$rule_description" \
      'first(.result.rules[]? | select(.description == $description) | .id) // ""' \
      <<<"$ruleset"
  )"
else
  rule_id=""
fi

if [[ -n "$tls_ruleset_id" ]]; then
  tls_ruleset="$(cf_api GET "/zones/${zone_id}/rulesets/${tls_ruleset_id}")"
  tls_rule_id="$(
    jq -r \
      --arg description "$tls_rule_description" \
      'first(.result.rules[]? | select(.description == $description) | .id) // ""' \
      <<<"$tls_ruleset"
  )"
else
  tls_rule_id=""
fi

if [[ "$action" == "remove" ]]; then
  if [[ -n "$rule_id" ]]; then
    cf_api DELETE "/zones/${zone_id}/rulesets/${ruleset_id}/rules/${rule_id}" >/dev/null
    verified="$(cf_api GET "/zones/${zone_id}/rulesets/${ruleset_id}")"
    jq -e \
      --arg description "$rule_description" \
      'all(.result.rules[]?; .description != $description)' >/dev/null <<<"$verified"
    echo "Removed Cloudflare Origin Rule for ${api_hostname}"
  else
    echo "Cloudflare Origin Rule is already absent for ${api_hostname}"
  fi

  if [[ -n "$tls_rule_id" ]]; then
    cf_api DELETE "/zones/${zone_id}/rulesets/${tls_ruleset_id}/rules/${tls_rule_id}" >/dev/null
    tls_verified="$(cf_api GET "/zones/${zone_id}/rulesets/${tls_ruleset_id}")"
    jq -e \
      --arg description "$tls_rule_description" \
      'all(.result.rules[]?; .description != $description)' >/dev/null <<<"$tls_verified"
    echo "Removed Cloudflare TLS Configuration Rule for ${api_hostname}"
  else
    echo "Cloudflare TLS Configuration Rule is already absent for ${api_hostname}"
  fi
  exit 0
fi

ssl_mode="$(cf_api GET "/zones/${zone_id}/settings/ssl" | jq -er '.result.value')"
origin_max_http_version="$(
  cf_api GET "/zones/${zone_id}/settings/origin_max_http_version" |
    jq -er '.result.value'
)"

echo "Cloudflare origin transport: SSL=${ssl_mode}, HTTP/${origin_max_http_version} max"

if [[ "$origin_max_http_version" != "2" ]]; then
  echo "error: Cloudflare HTTP/2 to Origin must be enabled for Octelium gRPC" >&2
  exit 1
fi

tls_rule_payload="$(
  jq -cn \
    --arg description "$tls_rule_description" \
    --arg host "$api_hostname" \
    '{
      action: "set_config",
      action_parameters: {ssl: "strict"},
      expression: ("(http.host eq \"" + $host + "\")"),
      description: $description,
      enabled: true
    }'
)"

if [[ -z "$tls_ruleset_id" ]]; then
  create_payload="$(
    jq -cn \
      --argjson rule "$tls_rule_payload" \
      '{
        name: "Homelab configuration overrides",
        kind: "zone",
        phase: "http_config_settings",
        rules: [$rule]
      }'
  )"
  created="$(cf_api POST "/zones/${zone_id}/rulesets" "$create_payload")"
  tls_ruleset_id="$(jq -er '.result.id' <<<"$created")"
  echo "Created Cloudflare TLS Configuration Rule for ${api_hostname}"
elif [[ -z "$tls_rule_id" ]]; then
  cf_api POST "/zones/${zone_id}/rulesets/${tls_ruleset_id}/rules" "$tls_rule_payload" >/dev/null
  echo "Added Cloudflare TLS Configuration Rule for ${api_hostname}"
else
  cf_api PATCH "/zones/${zone_id}/rulesets/${tls_ruleset_id}/rules/${tls_rule_id}" "$tls_rule_payload" >/dev/null
  echo "Updated Cloudflare TLS Configuration Rule for ${api_hostname}"
fi

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

tls_verified="$(cf_api GET "/zones/${zone_id}/rulesets/${tls_ruleset_id}")"
jq -e \
  --arg description "$tls_rule_description" \
  --arg host "$api_hostname" \
  'any(
    .result.rules[]?;
    .description == $description and
    .enabled == true and
    .action == "set_config" and
    .action_parameters.ssl == "strict" and
    .expression == ("(http.host eq \"" + $host + "\")")
  )' >/dev/null <<<"$tls_verified"

echo "Verified Cloudflare TLS Configuration Rule for ${api_hostname}: Full (strict)"
