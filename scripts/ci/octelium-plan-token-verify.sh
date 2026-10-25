#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ $# -eq 0 && ! -t 0 ]] || {
  echo 'error: pipe the new plan token to this verifier on stdin' >&2
  exit 2
}
for tool in curl jq; do
  command -v "$tool" >/dev/null || {
    echo "error: ${tool} is required" >&2
    exit 127
  }
done

token="$(cat)"
if [[ ! "$token" =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
  echo 'error: invalid plan token format' >&2
  exit 1
fi

work="$(mktemp -d "${TMPDIR:-/tmp}/octelium-plan-token-verify.XXXXXX")"
cleanup() {
  unset token
  rm -rf -- "$work"
}
trap cleanup EXIT
response="$work/response.json"
api='https://kubernetes-api-ci.stinkyboi.com'
printf -v probe_name 'homelab-ci-plan-probe-%04x%04x%04x%04x' \
  "$RANDOM" "$RANDOM" "$RANDOM" "$RANDOM"
configmap_url="${api}/api/v1/namespaces/default/configmaps/${probe_name}"
patch='[{"op":"test","path":"/metadata/uid","value":null}]'

fail() {
  echo "error: plan token ${1} check failed; private response withheld" >&2
  exit 1
}

request() {
  local method="$1" url="$2"
  local args=(-q --config - --silent --show-error --proto '=https'
    --connect-timeout 10 --max-time 25 --request "$method"
    --header 'Accept: application/json' --output "$response"
    --write-out '%{http_code}')
  if [[ "$method" == PATCH ]]; then
    args+=(--header 'Content-Type: application/json-patch+json'
      --data-binary "$patch")
  fi
  args+=("$url")
  http_code="$(printf 'header = "Authorization: Bearer %s"\n' "$token" |
    curl "${args[@]}" 2>/dev/null)" || fail transport
  [[ "$http_code" =~ ^[0-9]{3}$ ]] || fail transport
}

request GET "${api}/api/v1/namespaces/default"
[[ "$http_code" == 200 ]] || fail read
jq -e '.kind == "Namespace" and .apiVersion == "v1" and .metadata.name == "default"' \
  "$response" >/dev/null 2>&1 || fail read

# JSON Patch contains only a failing UID test. It cannot create or change an
# object if the policy unexpectedly permits a real PATCH request.
request PATCH "${configmap_url}?dryRun=All"
[[ "$http_code" == 404 ]] || fail dry-run
jq -e --arg name "$probe_name" '
  .kind == "Status" and .apiVersion == "v1" and .status == "Failure" and
  .reason == "NotFound" and .code == 404 and .details.name == $name and
  .details.kind == "configmaps"
' "$response" >/dev/null 2>&1 || fail dry-run

request PATCH "$configmap_url"
[[ "$http_code" == 403 ]] || fail live-write-denial
request GET "${api}/api/v1/namespaces/default/pods/${probe_name}/log"
[[ "$http_code" == 403 ]] || fail subresource-denial

echo 'Plan Octelium read, dry-run, live-write denial, and subresource denial verified.'
