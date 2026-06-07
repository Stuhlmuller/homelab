#!/usr/bin/env bash
set -euo pipefail

: "${OCTELIUM_AUTH_TOKEN:?OCTELIUM_AUTH_TOKEN must contain the homelab-ci Octelium credential}"

OCTELIUM_DOMAIN="${OCTELIUM_DOMAIN:-stinkyboi.com}"
OCTELIUM_HOMEDIR="${OCTELIUM_HOMEDIR:-${RUNNER_TEMP:-/tmp}/octelium}"
OCTELIUM_KUBE_SERVICE="${OCTELIUM_KUBE_SERVICE:-kubernetes-api.ci}"
OCTELIUM_KUBE_LOCAL_HOST="${OCTELIUM_KUBE_LOCAL_HOST:-127.0.0.1}"
OCTELIUM_KUBE_LOCAL_PORT="${OCTELIUM_KUBE_LOCAL_PORT:-16443}"
OCTELIUM_READY_TIMEOUT_SECONDS="${OCTELIUM_READY_TIMEOUT_SECONDS:-180}"
OCTELIUM_IMPLEMENTATION="${OCTELIUM_IMPLEMENTATION:-gvisor}"
OCTELIUM_USE_SUDO="${OCTELIUM_USE_SUDO:-false}"
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

connect_cmd=(
  "${OCTELIUM_BIN}"
  --homedir "${OCTELIUM_HOMEDIR}"
  connect
  --domain "${OCTELIUM_DOMAIN}"
  --auth-token "${OCTELIUM_AUTH_TOKEN}"
  --implementation "${OCTELIUM_IMPLEMENTATION}"
  --ip-mode v4
  --no-dns
  --publish "${OCTELIUM_KUBE_SERVICE}:${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}"
)
if [ "${OCTELIUM_USE_SUDO}" = "true" ]; then
  nohup sudo -E "${connect_cmd[@]}" >"${OCTELIUM_CONNECT_LOG}" 2>&1 &
else
  nohup "${connect_cmd[@]}" >"${OCTELIUM_CONNECT_LOG}" 2>&1 &
fi
echo "$!" >"${OCTELIUM_CONNECT_PID_FILE}"

deadline=$((SECONDS + OCTELIUM_READY_TIMEOUT_SECONDS))
until curl -ksS --max-time 5 -o /dev/null "https://${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}/version"; do
  if ! kill -0 "$(cat "${OCTELIUM_CONNECT_PID_FILE}")" 2>/dev/null; then
    sed -E 's/[A-Za-z0-9_-]{20,}/[redacted]/g' "${OCTELIUM_CONNECT_LOG}" >&2 || true
    echo "Octelium exited before publishing ${OCTELIUM_KUBE_SERVICE}." >&2
    exit 1
  fi
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    if [ "${OCTELIUM_USE_SUDO}" = "true" ]; then
      sudo -E "${OCTELIUM_BIN}" --homedir "${OCTELIUM_HOMEDIR}" status || true
    else
      "${OCTELIUM_BIN}" --homedir "${OCTELIUM_HOMEDIR}" status || true
    fi
    sed -E 's/[A-Za-z0-9_-]{20,}/[redacted]/g' "${OCTELIUM_CONNECT_LOG}" >&2 || true
    echo "Timed out waiting for ${OCTELIUM_KUBE_SERVICE} on ${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}." >&2
    exit 1
  fi
  sleep 2
done

echo "Octelium published ${OCTELIUM_KUBE_SERVICE} on ${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}."
