#!/bin/bash
set -euo pipefail

node /usr/src/app/cache-drill.js prepare
if [[ ! -f /tmp/renovate-cache-drill-mode ]]; then
  exec renovate
fi

renovate &
runner_pid=$!
trap 'kill -TERM "$runner_pid" 2>/dev/null || true' TERM INT
set +e
wait "$runner_pid"
runner_status=$?
set -e
if (( runner_status != 0 )); then
  exit "$runner_status"
fi
node /usr/src/app/cache-drill.js verify
