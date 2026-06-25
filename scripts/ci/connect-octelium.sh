#!/usr/bin/env bash
set -euo pipefail

: "${OCTELIUM_AUTH_TOKEN:?OCTELIUM_AUTH_TOKEN must contain the homelab-ci Octelium credential}"

OCTELIUM_DOMAIN="${OCTELIUM_DOMAIN:-stinkyboi.com}"
OCTELIUM_API_HOSTNAME="${OCTELIUM_API_HOSTNAME:-octelium-api.${OCTELIUM_DOMAIN}}"
OCTELIUM_API_HOST_ALIAS="${OCTELIUM_API_HOST_ALIAS:-}"
octelium_default_homedir="${RUNNER_TEMP:-/tmp}/octelium"
if [ -n "${GITHUB_RUN_ID:-}" ]; then
  octelium_default_homedir="${RUNNER_TEMP:-/tmp}/octelium-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
fi
OCTELIUM_HOMEDIR="${OCTELIUM_HOMEDIR:-${octelium_default_homedir}}"
OCTELIUM_KUBE_SERVICE="${OCTELIUM_KUBE_SERVICE:-kubernetes-api.ci}"
OCTELIUM_KUBE_SERVICE_ADDRESS="${OCTELIUM_KUBE_SERVICE_ADDRESS:-}"
OCTELIUM_KUBE_LOCAL_HOST="${OCTELIUM_KUBE_LOCAL_HOST:-127.0.0.1}"
OCTELIUM_KUBE_LOCAL_PORT="${OCTELIUM_KUBE_LOCAL_PORT:-16443}"
OCTELIUM_READY_TIMEOUT_SECONDS="${OCTELIUM_READY_TIMEOUT_SECONDS:-180}"
OCTELIUM_IMPLEMENTATION="${OCTELIUM_IMPLEMENTATION:-gvisor}"
OCTELIUM_NO_DNS="${OCTELIUM_NO_DNS:-false}"
OCTELIUM_TUNNEL_MODE="${OCTELIUM_TUNNEL_MODE:-}"
OCTELIUM_USE_SUDO="${OCTELIUM_USE_SUDO:-false}"
OCTELIUM_LOGOUT_ON_EXIT="${OCTELIUM_LOGOUT_ON_EXIT:-true}"
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

configure_octelium_api_host_alias() {
  local alias_ip=""

  if [ -z "${OCTELIUM_API_HOST_ALIAS}" ]; then
    return 0
  fi

  if [[ "${OCTELIUM_API_HOST_ALIAS}" =~ ^[0-9]+(\.[0-9]+){3}$ || "${OCTELIUM_API_HOST_ALIAS}" == *:* ]]; then
    alias_ip="${OCTELIUM_API_HOST_ALIAS}"
  else
    command -v getent >/dev/null 2>&1 || {
      echo "getent is required to resolve OCTELIUM_API_HOST_ALIAS=${OCTELIUM_API_HOST_ALIAS}." >&2
      exit 1
    }
    alias_ip="$(
      getent ahosts "${OCTELIUM_API_HOST_ALIAS}" |
        awk '$1 ~ /^[0-9]+(\.[0-9]+){3}$/ { print $1; exit }'
    )"
  fi

  if [ -z "${alias_ip}" ]; then
    echo "Could not resolve OCTELIUM_API_HOST_ALIAS=${OCTELIUM_API_HOST_ALIAS}." >&2
    exit 1
  fi

  if awk -v host="${OCTELIUM_API_HOSTNAME}" '
    $1 !~ /^#/ {
      for (i = 2; i <= NF; i++) {
        if ($i == host) {
          found = 1
        }
      }
    }
    END { exit found ? 0 : 1 }
  ' /etc/hosts; then
    echo "/etc/hosts already has an entry for ${OCTELIUM_API_HOSTNAME}."
    return 0
  fi

  if [ -w /etc/hosts ]; then
    printf '%s\t%s\n' "${alias_ip}" "${OCTELIUM_API_HOSTNAME}" >>/etc/hosts
  elif command -v sudo >/dev/null 2>&1; then
    printf '%s\t%s\n' "${alias_ip}" "${OCTELIUM_API_HOSTNAME}" | sudo tee -a /etc/hosts >/dev/null
  else
    echo "Cannot write /etc/hosts and sudo is not available." >&2
    exit 1
  fi
  echo "Mapped ${OCTELIUM_API_HOSTNAME} to ${alias_ip} for Octelium CLI control-plane calls."
}

configure_octelium_api_host_alias

install -m 0700 -d "${OCTELIUM_HOMEDIR}"

connect_cmd=(
  "${OCTELIUM_BIN}"
  --homedir "${OCTELIUM_HOMEDIR}"
)
if [ "${OCTELIUM_LOGOUT_ON_EXIT}" = "true" ]; then
  connect_cmd+=(--logout)
fi
connect_cmd+=(
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
    sed -E 's/[A-Za-z0-9_-]{20,}/[redacted]/g' "${OCTELIUM_CONNECT_LOG}" >&2 || true
    echo "Octelium exited before publishing ${OCTELIUM_KUBE_SERVICE}." >&2
    exit 1
  fi
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    run_status
    sed -E 's/[A-Za-z0-9_-]{20,}/[redacted]/g' "${OCTELIUM_CONNECT_LOG}" >&2 || true
    echo "Timed out waiting for ${readiness_target}." >&2
    exit 1
  fi
  sleep 2
done

echo "Octelium reached ${readiness_target}."
