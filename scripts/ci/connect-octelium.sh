#!/usr/bin/env bash
set -euo pipefail

: "${OCTELIUM_AUTH_TOKEN:?OCTELIUM_AUTH_TOKEN must contain the homelab-ci Octelium credential}"

OCTELIUM_DOMAIN="${OCTELIUM_DOMAIN:-stinkyboi.com}"
OCTELIUM_HOMEDIR="${OCTELIUM_HOMEDIR:-${RUNNER_TEMP:-/tmp}/octelium}"
OCTELIUM_KUBE_SERVICE="${OCTELIUM_KUBE_SERVICE:-kubernetes-api.ci}"
OCTELIUM_KUBE_SERVICE_ADDRESS="${OCTELIUM_KUBE_SERVICE_ADDRESS:-}"
OCTELIUM_KUBE_LOCAL_HOST="${OCTELIUM_KUBE_LOCAL_HOST:-127.0.0.1}"
OCTELIUM_KUBE_LOCAL_PORT="${OCTELIUM_KUBE_LOCAL_PORT:-16443}"
OCTELIUM_READY_TIMEOUT_SECONDS="${OCTELIUM_READY_TIMEOUT_SECONDS:-180}"
OCTELIUM_IMPLEMENTATION="${OCTELIUM_IMPLEMENTATION:-gvisor}"
OCTELIUM_NO_DNS="${OCTELIUM_NO_DNS:-false}"
OCTELIUM_TUNNEL_MODE="${OCTELIUM_TUNNEL_MODE:-}"
OCTELIUM_USE_SUDO="${OCTELIUM_USE_SUDO:-false}"
OCTELIUM_STATUS_TIMEOUT_SECONDS="${OCTELIUM_STATUS_TIMEOUT_SECONDS:-10}"
OCTELIUM_CONNECT_LOG="${OCTELIUM_CONNECT_LOG:-${OCTELIUM_HOMEDIR}/connect.log}"
OCTELIUM_CONNECT_PID_FILE="${OCTELIUM_CONNECT_PID_FILE:-${OCTELIUM_HOMEDIR}/connect.pid}"

command -v octelium >/dev/null 2>&1 || {
  echo "octelium is not installed or not on PATH." >&2
  exit 1
}
OCTELIUM_BIN="$(command -v octelium)"
command -v curl >/dev/null 2>&1 || {
  echo "curl is required to verify the Octelium-published Kubernetes API." >&2
  exit 1
}
if [ "${OCTELIUM_USE_SUDO}" = "true" ]; then
  command -v sudo >/dev/null 2>&1 || {
    echo "sudo is required when OCTELIUM_USE_SUDO=true." >&2
    exit 1
  }
fi

install -m 0700 -d "${OCTELIUM_HOMEDIR}"

redact_connect_log() {
  sed -E 's/[A-Za-z0-9_-]{20,}/[redacted]/g' "${OCTELIUM_CONNECT_LOG}" >&2 || true
}

explain_connect_failure() {
  if grep -q 'PermissionDenied' "${OCTELIUM_CONNECT_LOG}" 2>/dev/null; then
    cat >&2 <<'MSG'
Octelium denied the client session. Verify the committed catalog has been
applied and rotate OCTELIUM_CI_AUTH_TOKEN with scripts/octelium-ci-credential.sh
after authenticating octeliumctl as an Octelium admin.
MSG
  fi
}

connect_cmd=(
  "${OCTELIUM_BIN}"
  --homedir "${OCTELIUM_HOMEDIR}"
  connect
  --domain "${OCTELIUM_DOMAIN}"
  --auth-token "${OCTELIUM_AUTH_TOKEN}"
  --implementation "${OCTELIUM_IMPLEMENTATION}"
  --ip-mode v4
)
if [ "${OCTELIUM_NO_DNS}" = "true" ]; then
  connect_cmd+=(--no-dns)
fi
if [ -n "${OCTELIUM_TUNNEL_MODE}" ]; then
  connect_cmd+=(--tunnel-mode "${OCTELIUM_TUNNEL_MODE}")
fi
if [ -z "${OCTELIUM_KUBE_SERVICE_ADDRESS}" ]; then
  connect_cmd+=(--publish "${OCTELIUM_KUBE_SERVICE}:${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}")
fi
if [ "${OCTELIUM_USE_SUDO}" = "true" ]; then
  nohup sudo -E "${connect_cmd[@]}" >"${OCTELIUM_CONNECT_LOG}" 2>&1 &
else
  nohup "${connect_cmd[@]}" >"${OCTELIUM_CONNECT_LOG}" 2>&1 &
fi
echo "$!" >"${OCTELIUM_CONNECT_PID_FILE}"

if [ -n "${OCTELIUM_KUBE_SERVICE_ADDRESS}" ]; then
  readiness_url="https://${OCTELIUM_KUBE_SERVICE_ADDRESS}:6443/version"
  readiness_target="${OCTELIUM_KUBE_SERVICE} at ${OCTELIUM_KUBE_SERVICE_ADDRESS}:6443"
else
  readiness_url="https://${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}/version"
  readiness_target="${OCTELIUM_KUBE_SERVICE} on ${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}"
fi

deadline=$((SECONDS + OCTELIUM_READY_TIMEOUT_SECONDS))
run_status() {
  local status_cmd

  status_cmd=("${OCTELIUM_BIN}" --homedir "${OCTELIUM_HOMEDIR}" status)
  if [ "${OCTELIUM_USE_SUDO}" = "true" ]; then
    status_cmd=(sudo -E "${status_cmd[@]}")
  fi

  if command -v timeout >/dev/null 2>&1; then
    timeout "${OCTELIUM_STATUS_TIMEOUT_SECONDS}" "${status_cmd[@]}" || true
  else
    "${status_cmd[@]}" || true
  fi
}

until curl -ksS --max-time 5 -o /dev/null "${readiness_url}"; do
  if ! kill -0 "$(cat "${OCTELIUM_CONNECT_PID_FILE}")" 2>/dev/null; then
    redact_connect_log
    explain_connect_failure
    echo "Octelium exited before publishing ${OCTELIUM_KUBE_SERVICE}." >&2
    exit 1
  fi
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    run_status
    redact_connect_log
    explain_connect_failure
    echo "Timed out waiting for ${readiness_target}." >&2
    exit 1
  fi
  sleep 2
done

echo "Octelium reached ${readiness_target}."
