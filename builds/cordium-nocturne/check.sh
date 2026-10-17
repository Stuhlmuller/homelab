#!/usr/bin/env bash
set -euo pipefail
[[ $# == 0 && "$(uname -s)/$(uname -m)" == Linux/x86_64 ]] || { echo 'Run with no arguments on Linux x86_64' >&2; exit 2; }
recipe="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
for asset in archive go; do
  curl --fail --location --silent --show-error --proto '=https' --max-time 120 \
    "$(jq -r ".${asset}_url" "$recipe/source.json")" -o "$scratch/$asset.tar.gz"
  printf '%s  %s\n' "$(jq -r ".${asset}_sha256" "$recipe/source.json")" "$scratch/$asset.tar.gz" | sha256sum --check --status
done
mkdir "$scratch/source"
tar -xzf "$scratch/archive.tar.gz" --strip-components=1 -C "$scratch/source"
tar -xzf "$scratch/go.tar.gz" -C "$scratch"
cp "$recipe/workspace_requests_test.go" "$scratch/source/cluster/nocturne/nocturne/controllers/workspaces/homelab_requests_test.go"
if "$scratch/go/bin/go" -C "$scratch/source" test ./cluster/nocturne/nocturne/controllers/workspaces \
  -run '^TestHomelabWorkspaceReservesItsLimits$' -count=1 >"$scratch/before.log" 2>&1; then
  echo 'Expected upstream resource-request defect was not reproduced' >&2
  exit 1
fi
grep -q -- '--- FAIL: TestHomelabWorkspaceReservesItsLimits' "$scratch/before.log"
grep -q 'memory request=5Mi limit=2Gi' "$scratch/before.log"
cat "$scratch/before.log"
echo 'Reproduced the actual upstream workspace reservation defect'
