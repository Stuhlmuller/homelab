#!/usr/bin/env bash
set -euo pipefail

octelium_default_homedir="${RUNNER_TEMP:-/tmp}/octelium"
if [ -n "${GITHUB_RUN_ID:-}" ]; then
  octelium_default_homedir="${RUNNER_TEMP:-/tmp}/octelium-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
fi
OCTELIUM_HOMEDIR="${OCTELIUM_HOMEDIR:-${octelium_default_homedir}}"
OCTELIUM_CONNECT_PID_FILE="${OCTELIUM_CONNECT_PID_FILE:-${OCTELIUM_HOMEDIR}/connect.pid}"

if [ ! -f "${OCTELIUM_CONNECT_PID_FILE}" ]; then
  echo "No Octelium connect PID file found at ${OCTELIUM_CONNECT_PID_FILE}."
  exit 0
fi

connect_pid="$(cat "${OCTELIUM_CONNECT_PID_FILE}")"
if [ -z "${connect_pid}" ]; then
  echo "Octelium connect PID file is empty: ${OCTELIUM_CONNECT_PID_FILE}."
  exit 0
fi

if kill "${connect_pid}" 2>/dev/null; then
  echo "Stopped Octelium connect process ${connect_pid}."
elif command -v sudo >/dev/null 2>&1 && sudo kill "${connect_pid}" 2>/dev/null; then
  echo "Stopped Octelium connect process ${connect_pid} with sudo."
else
  echo "Octelium connect process ${connect_pid} was already stopped."
fi
