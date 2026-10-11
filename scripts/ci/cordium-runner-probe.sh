#!/usr/bin/env bash
set -euo pipefail

# Fixed reviewed-main probe; no GitHub App credentials or runner registration.
[[ "$(uname -s)/$(uname -m)" == Linux/x86_64 ]]
[[ "$(id -u)" == 0 ]]
image="$(jq -er '.spec.image.registry.url' .cordium/runner-workspace.json)"
scratch="$(mktemp -d)"
daemon_pid=""
cleanup() {
  result=$?
  trap - EXIT INT TERM
  if [[ -n "$daemon_pid" ]]; then
    kill "$daemon_pid" 2>/dev/null || true
    wait "$daemon_pid" 2>/dev/null || true
  fi
  rm -rf -- "$scratch"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
dockerd --host "unix://$scratch/docker.sock" --data-root "$scratch/data" \
  --exec-root "$scratch/exec" --pidfile "$scratch/docker.pid" \
  --storage-driver vfs >"$scratch/daemon.log" 2>&1 &
daemon_pid=$!
docker_command() { docker --host "unix://$scratch/docker.sock" "$@"; }
ready=false
for _ in {1..30}; do
  kill -0 "$daemon_pid" || break
  if docker_command info >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
"$ready" || {
  echo 'Nested Docker daemon did not become ready.' >&2
  exit 1
}

mkdir "$scratch/context"
printf 'cordium-runner-probe\n' >"$scratch/context/sentinel"
# shellcheck disable=SC2016 # The nested builder expands the sentinel read.
printf 'FROM %s\nCOPY sentinel /sentinel\nRUN test "$(cat /sentinel)" = cordium-runner-probe\n' \
  "$image" >"$scratch/context/Dockerfile"
docker_command build --tag cordium-runner-probe "$scratch/context"
# shellcheck disable=SC2016 # The container expands its own bind-mount read.
docker_command run --rm --network bridge \
  --volume "$scratch/context:/probe:ro" cordium-runner-probe \
  bash -ceu 'test "$(cat /probe/sentinel)" = cordium-runner-probe; curl --fail --silent --show-error --max-time 20 https://api.github.com/meta >/dev/null'
/home/runner/externals/node24/bin/node --version
echo 'Cordium runner image: nested Docker build, bind mount, bridged HTTPS and Node action runtime verified.'
