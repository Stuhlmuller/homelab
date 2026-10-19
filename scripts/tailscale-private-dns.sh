#!/usr/bin/env bash
# Retire only approved public app subdomains after private client acceptance.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
zone_name="stinkyboi.com"
aws_region="us-west-2"
token_parameter="/homelab/cert-manager/cloudflare-api-token"
dry_run="true"
retire_private="false"
expected_sha=""
evidence=""
baseline_out=""

usage() {
  cat <<'USAGE'
Usage: scripts/tailscale-private-dns.sh --retire-private [--dry-run] [--baseline-out FILE]
       scripts/tailscale-private-dns.sh --retire-private --execute --expected-sha SHA --evidence FILE

Dry-run reads the 26 non-apex app names and previews only A/AAAA/CNAME deletions.
--baseline-out writes a private evidence template with the old maximum public TTL;
complete its cutover checks before execution. Execution requires reviewed main,
healthy private DNS and clients, and the saved baseline. Retired CI/callback/
carrier names and other public DNS record types are preserved. This helper has
no public application record publication or restoration mode.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --retire-private) retire_private="true"; shift ;;
    --dry-run) dry_run="true"; shift ;;
    --execute) dry_run="false"; shift ;;
    --expected-sha) expected_sha="${2:?Missing expected SHA}"; shift 2 ;;
    --evidence) evidence="${2:?Missing evidence file}"; shift 2 ;;
    --baseline-out) baseline_out="${2:?Missing baseline file}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "$retire_private" == "true" ]] || { echo 'error: --retire-private is required; public publication is disabled' >&2; exit 2; }
if [[ "$dry_run" == "false" ]]; then
  [[ -n "$expected_sha" && -n "$evidence" && -z "$baseline_out" ]] || {
    echo 'error: execution requires --expected-sha and --evidence, without --baseline-out' >&2; exit 2;
  }
else
  [[ -z "$expected_sha" && -z "$evidence" ]] || {
    echo 'error: --expected-sha and --evidence require --execute' >&2; exit 2;
  }
  if [[ -n "$baseline_out" ]]; then
    baseline_target="$(cd -- "$(dirname -- "$baseline_out")" && pwd -P)/$(basename -- "$baseline_out")"
    [[ "$baseline_target" != "$root/"* ]] || {
      echo 'error: keep the private baseline outside the public repository' >&2; exit 2;
    }
  fi
fi

for command in aws curl jq python3; do
  command -v "$command" >/dev/null || { echo "error: $command is required" >&2; exit 127; }
done

preflight=(python3 -I "$root/scripts/tailscale-private-dns-check.py" --retire-private)
if [[ "$dry_run" == "false" ]]; then
  "${preflight[@]}" --execute --expected-sha "$expected_sha" --evidence "$evidence"
else
  "${preflight[@]}" >/dev/null
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
zone_nameservers="$(jq -c --arg name "$zone_name" '.result | select(length == 1) | .[0] | select(.name == $name) | .name_servers' <<<"$zone_response")"
"${preflight[@]}" --zone-name-servers "$zone_nameservers"
inventory="$root/scripts/config/tailscale-private-dns.json"
checked_names="$(jq -ce '[.hostnames[:27][] | select(. != "stinkyboi.com")]' "$inventory")"
names="$(jq -r '.[]' <<<"$checked_names")"

records_for() {
  local hostname="$1" encoded response
  encoded="$(jq -rn --arg name "$hostname" '$name | @uri')"
  response="$(cf_api GET "/zones/${zone_id}/dns_records?name=${encoded}&per_page=100")"
  # Validate every returned owner before filtering record types.
  jq -ce --arg name "$hostname" '
    select(.result | type == "array") |
    select(.result_info.total_count == (.result | length)) |
    select(all(.result[]; .name == $name and (.id | type == "string") and (.id | length > 0))) |
    [.result[] | select(.type == "A" or .type == "AAAA" or .type == "CNAME")]' <<<"$response"
}

scan_zone() {
  local page=1 expected_total=-1 expected_pages=-1 response total pages count wanted
  : >"$private_dir/zone-ids.jsonl"
  : >"$private_dir/zone-metadata.jsonl"
  while :; do
    response="$(cf_api GET "/zones/${zone_id}/dns_records?per_page=100&page=${page}")"
    jq -e --argjson page "$page" '
      (.result | type == "array") and
      (.result_info.page == $page) and (.result_info.per_page == 100) and
      (.result_info.count == (.result | length)) and
      (.result_info.total_count | type == "number") and (.result_info.total_count > 0) and
      (.result_info.total_pages | type == "number") and
      (.result_info.total_pages == ((.result_info.total_count + 99) / 100 | floor)) and
      all(.result[]; type == "object" and (.id | type == "string") and (.id | length > 0) and
        (.name | type == "string") and (.type | type == "string"))
    ' >/dev/null <<<"$response" || { echo 'error: incomplete public-zone page' >&2; return 1; }
    total="$(jq -er '.result_info.total_count' <<<"$response")"
    pages="$(jq -er '.result_info.total_pages' <<<"$response")"
    count="$(jq -er '.result_info.count' <<<"$response")"
    if [[ "$expected_total" == -1 ]]; then
      expected_total="$total"
      expected_pages="$pages"
    elif [[ "$total" != "$expected_total" || "$pages" != "$expected_pages" ]]; then
      echo 'error: public-zone page totals changed during inspection' >&2
      return 1
    fi
    wanted=100
    if (( page == pages )); then wanted=$((total - 100 * (pages - 1))); fi
    if (( count != wanted )); then
      echo 'error: incomplete public-zone page' >&2
      return 1
    fi
    jq -c '.result[].id' <<<"$response" >>"$private_dir/zone-ids.jsonl"
    jq -c '.result[] | select(.type == "A" or .type == "AAAA" or .type == "CNAME" or .type == "NS") | {id,name,type}' \
      <<<"$response" >>"$private_dir/zone-metadata.jsonl"
    if (( page == pages )); then break; fi
    page=$((page + 1))
  done
  jq -se --argjson total "$expected_total" 'length == $total and length == (unique | length)' \
    "$private_dir/zone-ids.jsonl" >/dev/null || {
      echo 'error: duplicate or incomplete public-zone record IDs' >&2; return 1;
    }
  jq -sc '.' "$private_dir/zone-metadata.jsonl" >"$private_dir/zone.json"
  # A delegated child can serve records outside this zone, so inspection blocks instead of changing its NS.
  "${preflight[@]}" --inspect-zone "$private_dir/zone.json" --current "$private_dir/current.json"
}

private_dir="$(mktemp -d)"
chmod 700 "$private_dir"
trap 'rm -rf -- "$private_dir"' EXIT
while IFS= read -r hostname; do
  records_for "$hostname" >"$private_dir/$hostname.json"
done <<<"$names"

current="$(jq -cs 'add | map({id,name,type,content,ttl,proxied}) | sort_by(.name,.type,.id)' "$private_dir"/*.json)"
printf '%s\n' "$current" >"$private_dir/current.json"
scan_zone

if [[ "$dry_run" == "true" ]]; then
  previous_ttl="$("${preflight[@]}" --baseline-ttl)"
  echo "Old maximum authoritative TTL: ${previous_ttl} seconds"
  jq -r '.[] | "DRY-RUN delete \(.id) \(.type) \(.name)"' <<<"$current"
  if [[ -n "$baseline_out" ]]; then
    reviewed_sha="$(git -C "$root" rev-parse HEAD)"
    template="$(jq -cn --arg sha "$reviewed_sha" --argjson ttl "$previous_ttl" --argjson names "$checked_names" --argjson records "$current" '{
      reviewed_main_sha:$sha, resolver_ip:"", owner_tailnet_dns_confirmed:false,
      normal_client_dns_confirmed:false,
      critical_paths_confirmed:{fleet_setup_denied:false,harbor_node_pulls:false,native_api:false,
        cordium_reconnect:false,public_callbacks:false},
      off_tailnet:($names | map({key:.,value:""}) | from_entries),
      previous_ttl_seconds:$ttl, checked_names:$names, baseline_records:$records
    }')"
    (umask 077; set -C; printf '%s\n' "$template" >"$baseline_out")
    echo "Wrote private cutover evidence template: ${baseline_out}"
  fi
  exit 0
fi

baseline="$(jq -ce '.baseline_records | sort_by(.name,.type,.id)' "$evidence")"
jq -e --argjson baseline "$baseline" 'all(.[]; . as $record | any($baseline[]; . == $record))' <<<"$current" >/dev/null || {
  echo 'error: live public records differ from the saved baseline; no records deleted' >&2; exit 1;
}
fresh="$(
  while IFS= read -r hostname; do records_for "$hostname" || exit 1; done <<<"$names" |
    jq -cs 'add | map({id,name,type,content,ttl,proxied}) | sort_by(.name,.type,.id)'
)"
[[ "$fresh" == "$current" ]] || {
  echo 'error: public target records changed during inspection; no records deleted' >&2; exit 1;
}

while IFS= read -r hostname; do
  while IFS= read -r record; do
    [[ -n "$record" ]] || continue
    id="$(jq -er '.id | @uri' <<<"$record")"
    cf_api DELETE "/zones/${zone_id}/dns_records/${id}" >/dev/null
  done < <(jq -c '.[]' "$private_dir/$hostname.json")
  [[ "$(records_for "$hostname" | jq 'length')" == 0 ]] || {
    echo "error: public address record remains for ${hostname}; rerun with the same evidence" >&2; exit 1;
  }
  echo "Verified public address retirement: ${hostname}"
done <<<"$names"

previous_ttl="$(jq -r '.previous_ttl_seconds' "$evidence")"
echo "All 26 app subdomains read back without A/AAAA/CNAME; wait ${previous_ttl} seconds from the last deletion before public resolver checks."
echo 'Legacy CI, callback, carrier, unrelated names, and non-address records were preserved.'
