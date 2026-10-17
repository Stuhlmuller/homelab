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
mapfile -d '' production < <(find "$scratch/source/cluster/nocturne/nocturne/controllers/workspaces" -maxdepth 1 -type f -name '*.go' ! -name '*_test.go' -print0 | sort -z)
check_requests() {
  "$scratch/go/bin/go" -C "$scratch/source" test "${production[@]}" \
    "$scratch/source/cluster/nocturne/nocturne/controllers/workspaces/homelab_requests_test.go" \
    -run '^TestHomelabWorkspaceReservesItsLimits$' -count=1
}
if check_requests >"$scratch/before.log" 2>&1; then
  echo 'Expected upstream resource-request defect was not reproduced' >&2
  exit 1
fi
grep -q -- '--- FAIL: TestHomelabWorkspaceReservesItsLimits' "$scratch/before.log"
grep -q 'memory request=5Mi limit=2Gi' "$scratch/before.log"
cat "$scratch/before.log"
patch --batch --fuzz=0 --directory="$scratch/source" --strip=1 < "$recipe/workspace-reservations.patch"
check_requests
echo 'Pinned generator reserves limits and isolates the Pod user namespace'
mkdir "$scratch/context"
# Preserve component image versions; only Nocturne's generator is patched.
linker='github.com/octelium/octelium/pkg/utils/ldflags'
CGO_ENABLED=0 "$scratch/go/bin/go" -C "$scratch/source" build -trimpath \
  -ldflags "-X $linker.GitTag=v0.12.7 -X $linker.GitCommit=e12b0b16d5fe94716e414fca7cfdc10b21014f2c -X $linker.GitBranch=homelab-reservations -X $linker.ImageRegistry=ghcr.io -X $linker.ImageRegistryPrefix=octelium" \
  -o "$scratch/context/cordium-nocturne" ./cluster/nocturne
docker build --platform=linux/amd64 --file "$recipe/Dockerfile" \
  --tag homelab-cordium-nocturne:build "$scratch/context"
# The controller has no help command; reaching its missing-cluster guard proves it loads.
status=0
timeout 30s docker run --rm --network=none --read-only --cap-drop=ALL --user 3454:3454 \
  homelab-cordium-nocturne:build >"$scratch/smoke.log" 2>&1 || status=$?
cat "$scratch/smoke.log"
[[ $status == 1 ]]
grep -q 'unable to load in-cluster configuration' "$scratch/smoke.log"
