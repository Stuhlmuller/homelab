#!/usr/bin/env bash
set -euo pipefail

OCTELIUM_DOMAIN="${OCTELIUM_DOMAIN:-stinkyboi.com}"
octelium_default_homedir="${RUNNER_TEMP:-/tmp}/octelium"
if [ -n "${GITHUB_RUN_ID:-}" ]; then
  octelium_default_homedir="${RUNNER_TEMP:-/tmp}/octelium-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
fi
OCTELIUM_HOMEDIR="${OCTELIUM_HOMEDIR:-${octelium_default_homedir}}"
OCTELIUM_USE_SUDO="${OCTELIUM_USE_SUDO:-false}"
OCTELIUM_LOGOUT_ON_DISCONNECT="${OCTELIUM_LOGOUT_ON_DISCONNECT:-true}"
OCTELIUM_CONNECT_PID_FILE="${OCTELIUM_CONNECT_PID_FILE:-${OCTELIUM_HOMEDIR}/connect.pid}"

run_octelium_client() {
  local verb="$1"
  local cmd

  if ! command -v octelium >/dev/null 2>&1; then
    echo "octelium is not installed; skipping ${verb} cleanup."
    return 0
  fi
  if [ ! -d "${OCTELIUM_HOMEDIR}" ]; then
    echo "Octelium homedir does not exist; skipping ${verb} cleanup: ${OCTELIUM_HOMEDIR}"
    return 0
  fi

  cmd=(octelium --homedir "${OCTELIUM_HOMEDIR}" "${verb}" --domain "${OCTELIUM_DOMAIN}")
  if [ "${OCTELIUM_USE_SUDO}" = "true" ]; then
    if ! command -v sudo >/dev/null 2>&1; then
      echo "sudo is not installed; skipping ${verb} cleanup."
      return 0
    fi
    if sudo -E "${cmd[@]}"; then
      echo "Ran octelium ${verb} for ${OCTELIUM_DOMAIN}."
    else
      echo "Octelium ${verb} cleanup did not complete; continuing teardown."
    fi
  elif "${cmd[@]}"; then
    echo "Ran octelium ${verb} for ${OCTELIUM_DOMAIN}."
  else
    echo "Octelium ${verb} cleanup did not complete; continuing teardown."
  fi
}

run_octelium_client disconnect

if [ -f "${OCTELIUM_CONNECT_PID_FILE}" ]; then
  connect_pid="$(cat "${OCTELIUM_CONNECT_PID_FILE}")"
  if [ -z "${connect_pid}" ]; then
    echo "Octelium connect PID file is empty: ${OCTELIUM_CONNECT_PID_FILE}."
  elif kill "${connect_pid}" 2>/dev/null; then
    echo "Stopped Octelium connect process ${connect_pid}."
  elif command -v sudo >/dev/null 2>&1 && sudo kill "${connect_pid}" 2>/dev/null; then
    echo "Stopped Octelium connect process ${connect_pid} with sudo."
  else
    echo "Octelium connect process ${connect_pid} was already stopped."
  fi
  rm -f "${OCTELIUM_CONNECT_PID_FILE}"
else
  echo "No Octelium connect PID file found at ${OCTELIUM_CONNECT_PID_FILE}."
fi

if [ "${OCTELIUM_LOGOUT_ON_DISCONNECT}" = "true" ]; then
  run_octelium_client logout
fi
