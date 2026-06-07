#!/usr/bin/env bash
set -euo pipefail

: "${OCTELIUM_AUTH_TOKEN:?OCTELIUM_AUTH_TOKEN must contain the homelab-ci Octelium credential}"

OCTELIUM_DOMAIN="${OCTELIUM_DOMAIN:-stinkyboi.com}"
OCTELIUM_HOMEDIR="${OCTELIUM_HOMEDIR:-${RUNNER_TEMP:-/tmp}/octelium}"
OCTELIUM_KUBE_SERVICE="${OCTELIUM_KUBE_SERVICE:-kubernetes-api.homelab}"
OCTELIUM_KUBE_LOCAL_HOST="${OCTELIUM_KUBE_LOCAL_HOST:-127.0.0.1}"
OCTELIUM_KUBE_LOCAL_PORT="${OCTELIUM_KUBE_LOCAL_PORT:-16443}"
OCTELIUM_READY_TIMEOUT_SECONDS="${OCTELIUM_READY_TIMEOUT_SECONDS:-60}"

command -v octelium >/dev/null 2>&1 || {
  echo "octelium is not installed or not on PATH." >&2
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "curl is required to verify the Octelium-published Kubernetes API." >&2
  exit 1
}

install -m 0700 -d "${OCTELIUM_HOMEDIR}"

octelium --homedir "${OCTELIUM_HOMEDIR}" connect \
  --domain "${OCTELIUM_DOMAIN}" \
  --auth-token "${OCTELIUM_AUTH_TOKEN}" \
  --detach \
  --implementation gvisor \
  --ip-mode v4 \
  --no-dns \
  --publish "${OCTELIUM_KUBE_SERVICE}:${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}"

deadline=$((SECONDS + OCTELIUM_READY_TIMEOUT_SECONDS))
until curl -kfsS --max-time 5 "https://${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}/version" >/dev/null; do
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    octelium --homedir "${OCTELIUM_HOMEDIR}" status || true
    echo "Timed out waiting for ${OCTELIUM_KUBE_SERVICE} on ${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}." >&2
    exit 1
  fi
  sleep 2
done

echo "Octelium published ${OCTELIUM_KUBE_SERVICE} on ${OCTELIUM_KUBE_LOCAL_HOST}:${OCTELIUM_KUBE_LOCAL_PORT}."
