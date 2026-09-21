#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 1 || ( $1 != test && $1 != inspect ) ]]; then
  echo 'Usage: bash scripts/nofx-credential-check.sh test|inspect' >&2
  exit 2
fi
mode=$1
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
check_dir="$(mktemp -d /tmp/nofx-credential-check.XXXXXX)"
trap 'rm -rf -- "$check_dir"' EXIT
python3 -I "$root/builds/nofx/prepare-source.py" "$check_dir/source"
cp -R "$root/scripts/nofx-credential-check" "$check_dir/source/upstream/credentialcheck"
cd "$check_dir/source/upstream"
go test ./credentialcheck -count=1

# The published NOFX images target linux/amd64; compile without a C runtime.
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o "$check_dir/check" ./credentialcheck
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
