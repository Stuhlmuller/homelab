#!/usr/bin/env bash
set -euo pipefail

# This transport changes only the ephemeral GitHub runner's host resolution.
[[ "${GITHUB_ACTIONS:-}" == true && "$(uname -s)" == Linux ]]
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
scratch="$(mktemp -d "${RUNNER_TEMP}/cordium-ci.XXXXXX")"
chmod 700 "$scratch"
carrier_pid=""
hosts_added=false
logged_in=false
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if "$logged_in"; then
    timeout 30 octelium --homedir "$scratch/login" logout --domain stinkyboi.com \
      >"$scratch/logout.log" 2>&1 || result=1
  fi
  if [[ -n "$carrier_pid" ]]; then
    kill "$carrier_pid" 2>/dev/null || true
    for _ in {1..10}; do
      kill -0 "$carrier_pid" 2>/dev/null || break
      sleep 1
    done
    kill -KILL "$carrier_pid" 2>/dev/null || true
    wait "$carrier_pid" 2>/dev/null || true
  fi
  if "$hosts_added"; then
    sudo sed -i '/# homelab-cordium-ci$/d' /etc/hosts || result=1
  fi
  rm -rf -- "$scratch"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if grep -q '# homelab-cordium-ci$' /etc/hosts; then
  echo 'Refusing to replace an existing Cordium CI transport.' >&2
  exit 1
fi
cp "$(command -v cloudflared)" "$scratch/cloudflared"
chmod 755 "$scratch/cloudflared"
sudo setcap cap_net_bind_service=+ep "$scratch/cloudflared"
"$scratch/cloudflared" access tcp --hostname octelium-transport.stinkyboi.com \
  --url 127.0.0.1:443 >"$scratch/carrier.log" 2>&1 &
carrier_pid=$!
hosts_added=true
printf '%s\n' '127.0.0.1 octelium-api.stinkyboi.com # homelab-cordium-ci' |
  sudo tee -a /etc/hosts >/dev/null

ready=false
for _ in {1..10}; do
  kill -0 "$carrier_pid"
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

timeout 60 octelium --homedir "$scratch/login" login --domain stinkyboi.com \
  --assertion github-actions >"$scratch/login.log" 2>&1
logged_in=true
python3 scripts/cordium-check.py --checkout "$GITHUB_SHA" --homedir "$scratch/login"
