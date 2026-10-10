#!/usr/bin/env bash
set -euo pipefail

# The workflow joins the tailnet before native TLS calls to the canonical API.
[[ "${GITHUB_ACTIONS:-}" == true && "$(uname -s)" == Linux ]]
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
[[ $# -ge 1 && $# -le 2 && "$1" =~ ^[0-9]+$ ]]
execution_deadline="$1"
mode="${2:-checks}"
(( $(date +%s) < execution_deadline - 180 ))
python3 -I scripts/cordium-ci-acceptance.py --mode "$mode" --verify-context
scratch="$(mktemp -d "${RUNNER_TEMP}/cordium-ci.XXXXXX")"
chmod 700 "$scratch"
logged_in=false
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if "$logged_in"; then
    timeout 30 octelium --homedir "$scratch/login" logout --domain stinkyboi.com \
      >"$scratch/logout.log" 2>&1 || result=1
  fi
  rm -rf -- "$scratch"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

ready=false
for _ in {1..10}; do
  if curl --silent --show-error --http2 --max-time 5 \
    -H 'content-type: application/grpc' -H "$(printf '%s%s: trailers' t e)" \
    --data-binary '' -D "$scratch/headers" -o /dev/null \
    -w '%{http_code} %{http_version}' \
    https://octelium-api.stinkyboi.com/octelium.api.main.user.v1.MainService/GetStatus \
    >"$scratch/status" 2>"$scratch/curl.log" &&
    [[ "$(cat "$scratch/status")" == '200 2' ]] &&
    grep -Eiq '^grpc-status:[[:space:]]*16[[:space:]]*$' "$scratch/headers"; then
    ready=true
    break
  fi
  sleep 1
done
"$ready" || { echo 'Native TLS transport is not ready.' >&2; exit 1; }

case "$mode" in
  deny-ref | deny-workflow)
    # These cases may authenticate only to observe rejection. They never invoke
    # Cordium or create a workspace, even if login unexpectedly succeeds.
    python3 -I scripts/cordium-ci-acceptance.py --mode "$mode" \
      --homedir "$scratch/login" --deadline "$execution_deadline"
    ;;
  checks | force-failure | forbidden-method)
    timeout 60 octelium --homedir "$scratch/login" login --domain stinkyboi.com \
      --assertion github-actions >"$scratch/login.log" 2>&1
    logged_in=true
    if [[ "$mode" == forbidden-method ]]; then
      python3 -I scripts/cordium-ci-acceptance.py --mode "$mode" \
        --homedir "$scratch/login" --deadline "$execution_deadline"
    else
      python3 -I scripts/cordium-check.py --checkout "$GITHUB_SHA" --homedir "$scratch/login" \
        --deadline "$execution_deadline" --mode "$mode"
    fi
    ;;
esac
