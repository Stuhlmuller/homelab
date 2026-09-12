#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 0 ]] || {
  echo "error: this fixed production apply accepts no arguments" >&2
  exit 2
}
[[ -n "${OCTELIUM_CATALOG_AUTH_TOKEN:-}" ]] || {
  echo "error: OCTELIUM_CATALOG_AUTH_TOKEN is required" >&2
  exit 1
}

domain="stinkyboi.com"
catalog="docs/examples/octelium/homelab-services.yaml"
artifact="octeliumctl-linux-amd64.tar.gz"
checksum="d46e57fc5f34c0462a2eb0357fc32329b5f66f15d4edff6dbb694c51c9dd6eac"
tmpdir="$(mktemp -d)"
ctl="${tmpdir}/octeliumctl"
ctl_home="${tmpdir}/home"
target_catalog="${tmpdir}/private-kubernetes.yaml"
logged_in="false"

cleanup() {
  local status=$?
  if [[ "$logged_in" == "true" ]]; then
    "$ctl" --homedir "$ctl_home" logout --domain "$domain" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmpdir"
  return "$status"
}
trap cleanup EXIT

install -m 0700 -d "$ctl_home"
yq ea 'select((.kind == "Policy" and (.metadata.name == "homelab-private-kubernetes-access" or .metadata.name == "homelab-private-talos-access")) or (.kind == "Service" and (.metadata.name == "kubernetes-api.homelab" or .metadata.name == "talos-api.homelab")))' \
  "$catalog" >"$target_catalog"
chmod 0600 "$target_catalog"
yq ea -o=json -I=0 '[.]' "$target_catalog" |
  jq -e '
    length == 4 and
    (map({kind, name: .metadata.name}) | sort_by(.kind, .name)) == [
      {"kind": "Policy", "name": "homelab-private-kubernetes-access"},
      {"kind": "Policy", "name": "homelab-private-talos-access"},
      {"kind": "Service", "name": "kubernetes-api.homelab"},
      {"kind": "Service", "name": "talos-api.homelab"}
    ]
  ' >/dev/null

curl -fsSL \
  "https://github.com/octelium/octelium/releases/download/v0.35.0/${artifact}" \
  -o "${tmpdir}/${artifact}"
printf '%s  %s\n' "$checksum" "${tmpdir}/${artifact}" | sha256sum --check -
tar -xzf "${tmpdir}/${artifact}" -C "$tmpdir"

scopes=(
  --scope api:core.MainService/ListPolicy
  --scope api:core.MainService/CreatePolicy
  --scope api:core.MainService/UpdatePolicy
  --scope api:core.MainService/ListService
  --scope api:core.MainService/CreateService
  --scope api:core.MainService/UpdateService
)
"$ctl" --homedir "$ctl_home" login --domain "$domain" \
  --auth-token "$OCTELIUM_CATALOG_AUTH_TOKEN" "${scopes[@]}"
unset OCTELIUM_CATALOG_AUTH_TOKEN
logged_in="true"

apply_catalog() {
  local output
  if ! output="$("$ctl" --homedir "$ctl_home" apply --domain "$domain" \
    --include Policy --include Service "$target_catalog" 2>&1)"; then
    printf '%s\n' "$output" >&2
    return 1
  fi
  if grep -Eq 'Could not (list|create|update|apply)|gRPC error' <<<"$output"; then
    printf '%s\n' "$output" >&2
    return 1
  fi
  printf '%s\n' "$output"
}

apply_catalog >/dev/null
second_apply="$(apply_catalog)"
grep -Fq 'No applied changes in Cluster Core resources' <<<"$second_apply" || {
  echo "error: second Octelium apply did not prove an empty live diff" >&2
  exit 1
}

echo "Private Kubernetes and Talos Policies and Services match the reviewed catalog."
