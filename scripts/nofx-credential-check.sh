#!/usr/bin/env bash
set -euo pipefail

mode=${1:-}
if ! [[ $mode == test && $# == 1 ]] &&
  ! [[ $mode == inspect && $# == 2 && ${2:-} =~ ^[a-f0-9]{40}$ ]]; then
  echo 'Usage: bash scripts/nofx-credential-check.sh test | inspect REVIEWED_MAIN_SHA' >&2
  exit 2
fi
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
check_dir="$(mktemp -d /tmp/nofx-credential-check.XXXXXX)"
trap 'chmod -R u+w "$check_dir"; rm -rf -- "$check_dir"' EXIT
if [[ $mode == inspect ]]; then
  reviewed_sha=$2
  checkout_status="$(git --no-replace-objects -C "$root" status --porcelain --untracked-files=all)"
  if [[ -n "$checkout_status" ]]; then
    echo 'Inspection requires a clean reviewed checkout, including untracked files' >&2
    exit 1
  fi
  remote_main="$(gh api --hostname github.com repos/Stuhlmuller/homelab/git/ref/heads/main --jq .object.sha)"
  if [[ "$(git --no-replace-objects -C "$root" rev-parse HEAD)" != "$reviewed_sha" ||
    "$remote_main" != "$reviewed_sha" ]]; then
    echo 'Inspection requires HEAD and remote main to match REVIEWED_MAIN_SHA' >&2
    exit 1
  fi
  # Build immutable committed inputs; ignored files and concurrent edits cannot
  # add executable code to the helper that receives the backend's environment.
  mkdir "$check_dir/reviewed"
  git --no-replace-objects -C "$root" archive "$reviewed_sha" -- builds/nofx scripts/nofx-credential-check \
    clusters/homelab/apps/nofx/deployment.yaml | tar -x -C "$check_dir/reviewed"
  root="$check_dir/reviewed"
  printf '%s\n' "$reviewed_sha" > "$root/builds/nofx/revision.txt"
fi
python3 -I "$root/builds/nofx/prepare-source.py" "$check_dir/source"
cp -R "$root/scripts/nofx-credential-check" "$check_dir/source/upstream/credentialcheck"
cd "$check_dir/source/upstream"
# Use the locked Nix toolchain without ambient overlays/workspaces, alternate
# roots, or mutable dependency caches substituting unreviewed source.
go_environment=(env -i "PATH=$PATH" "SSL_CERT_FILE=${SSL_CERT_FILE:-}"
  GOENV=off GOWORK=off GOFLAGS= GOTOOLCHAIN=local GO111MODULE=on CGO_ENABLED=0
  "GOPATH=$check_dir/go" "GOMODCACHE=$check_dir/modules" "GOCACHE=$check_dir/go-build")
"${go_environment[@]}" go test ./credentialcheck -count=1

# The published NOFX images target linux/amd64; compile without a C runtime.
"${go_environment[@]}" GOOS=linux GOARCH=amd64 go build -trimpath -o "$check_dir/check" ./credentialcheck
[[ $mode == inspect ]] || exit 0
kube=(kubectl --context admin@homelab --request-timeout=30s -n nofx)
backend_image="$(yq ea 'select(.kind == "Deployment" and .metadata.name == "nofx-backend") | .spec.template.spec.containers[] | select(.name == "backend") | .image' "$root/clusters/homelab/apps/nofx/deployment.yaml")"
frontend_image="$(yq ea 'select(.kind == "Deployment" and .metadata.name == "nofx-frontend") | .spec.template.spec.containers[] | select(.name == "frontend") | .image' "$root/clusters/homelab/apps/nofx/deployment.yaml")"
ready_pod() {
  "${kube[@]}" get pods -l "app.kubernetes.io/name=nofx,app.kubernetes.io/component=$1" -o json |
    python3 -I -c '
import json, sys
pods = [p["metadata"]["name"] for p in json.load(sys.stdin)["items"]
        if not p["metadata"].get("deletionTimestamp")
        and any(c.get("name") == sys.argv[2] and c.get("image") == sys.argv[1]
                for c in p["spec"]["containers"])
        and p.get("status", {}).get("phase") == "Running"
        and any(c.get("name") == sys.argv[2] and c.get("ready")
                for c in p.get("status", {}).get("containerStatuses", []))]
if len(pods) != 1:
    sys.exit("Expected exactly one ready NOFX pod at its declared image")
print(pods[0])' "$2" "$1"
}
backend_pod="$(ready_pod backend "$backend_image")"
frontend_pod="$(ready_pod frontend "$frontend_image")"
"${kube[@]}" exec "$frontend_pod" -c frontend -- wget -qO- http://127.0.0.1/nofx-source.tar.gz > "$check_dir/live-source.tar.gz"
python3 -I - "$check_dir/live-source.tar.gz" <<'PY'
import pathlib, sys, tarfile
with tarfile.open(sys.argv[1]) as archive:
    for name in ("crypto/crypto.go", "go.mod", "go.sum"):
        member = archive.extractfile("nofx/" + name)
        if member is None or member.read() != pathlib.Path(name).read_bytes():
            sys.exit("Deployed NOFX encryption source/dependencies differ; inspection refused")
PY

# Only the temporary executable is written. The helper opens SQLite mode=ro,
# uses the pod's existing encryption service inputs, and makes no API requests.
# Variables in the remote shell and its cleanup trap must expand inside the pod.
# shellcheck disable=SC2016
"${kube[@]}" exec -i "$backend_pod" -c backend -- sh -c '
set -eu
umask 077
diagnostic_dir="$(mktemp -d /tmp/nofx-credential-check.XXXXXX)"
trap '\''rm -f -- "$diagnostic_dir/check"; rmdir -- "$diagnostic_dir"'\'' EXIT
cat > "$diagnostic_dir/check"
chmod 700 "$diagnostic_dir/check"
"$diagnostic_dir/check"
' < "$check_dir/check"
