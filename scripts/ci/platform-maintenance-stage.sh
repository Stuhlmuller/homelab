#!/usr/bin/env bash
# Protected, source-pinned entry point. Activation remains false until the
# private recovery, publication, and isolated-canary gates are fulfilled.
set -euo pipefail
umask 077

stage="${RUN_STAGE:-}"
case "$stage" in
  inspect|qualify|owned-cleanup|talos-1.11.6|talos-1.12.12|talos-1.13.11|talos-1.14.4|kubernetes-1.35.9) ;;
  *) exit 2 ;;
esac
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REF:-}" == refs/heads/main &&
   "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ && "${EXPECTED_SHA:-}" == "$GITHUB_SHA" &&
   "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ ]] || exit 2
[[ "$GITHUB_SHA" == "$(gh api repos/Stuhlmuller/homelab/branches/main --jq .commit.sha)" ]] || exit 1

config=scripts/config/platform-maintenance.json
jq -e '.schemaVersion == 1 and .sourceRevisionPolicy == "exact-current-main-sha-from-protected-workflow"' "$config" >/dev/null
if [[ "$stage" != inspect ]]; then
  jq -e '.activationEnabled == true and (.canary.node | type == "string")' "$config" >/dev/null
fi

work="$(mktemp -d)"
chmod 700 "$work"
private_log="$work/tunnel.log"
tunnel_pid=
cleanup() {
  if [[ -n "$tunnel_pid" ]]; then
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
  fi
  if [[ -d "$work" ]]; then rm -rf -- "$work"; fi
}
trap cleanup EXIT

bucket="$(terragrunt render --config IaC/application-backup-storage.hcl --json --write=false --log-disable | jq -er .inputs.bucket)"
[[ "$(aws s3api get-bucket-versioning --bucket "$bucket" --query Status --output text)" == Enabled ]]
[[ "$(aws s3api get-bucket-encryption --bucket "$bucket" \
  --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' \
  --output text)" == 'aws:kms' ]]

retain_result() {
  local result="$1" name="$2" key response checksum version readback
  [[ -f "$result" && ! -L "$result" && "$(stat -c %a "$result")" == 600 &&
     "$(stat -c %s "$result")" -le 1048576 ]] || exit 1
  key="openclaw-enterprise/platform/${GITHUB_SHA}/${GITHUB_RUN_ID}/${name}.json"
  checksum="$(openssl dgst -sha256 -binary "$result" | base64 -w0)"
  response="$(aws s3api put-object --bucket "$bucket" --key "$key" --body "$result" \
    --server-side-encryption aws:kms --if-none-match '*' \
    --checksum-algorithm SHA256 --checksum-sha256 "$checksum")"
  version="$(jq -er .VersionId <<<"$response")"
  [[ "$version" != null && "$version" != "" ]] || exit 1
  readback="$(aws s3api head-object --bucket "$bucket" --key "$key" \
    --version-id "$version" --checksum-mode ENABLED)"
  jq -e --arg version "$version" --arg checksum "$checksum" \
    '.VersionId == $version and .ChecksumSHA256 == $checksum and .ServerSideEncryption == "aws:kms"' \
    <<<"$readback" >/dev/null
}

load_receipt() {
  local key="$1" target="$2" versions version metadata checksum actual
  versions="$(aws s3api list-object-versions --bucket "$bucket" --prefix "$key")"
  version="$(jq -er --arg key "$key" '
    if .IsTruncated != true and (.DeleteMarkers // []) == [] and
       (.Versions | length) == 1 and .Versions[0].Key == $key and
       (.Versions[0].IsLatest == true) and
       (.Versions[0].VersionId | type == "string" and . != "" and . != "null")
    then .Versions[0].VersionId else empty end' <<<"$versions")"
  metadata="$(aws s3api head-object --bucket "$bucket" --key "$key" \
    --version-id "$version" --checksum-mode ENABLED)"
  checksum="$(jq -er --arg version "$version" '
    select(.VersionId == $version and .ServerSideEncryption == "aws:kms" and
      (.ContentLength | type == "number" and . >= 1 and . <= 1048576)) |
    .ChecksumSHA256 | select(type == "string" and . != "")' <<<"$metadata")"
  aws s3api get-object --bucket "$bucket" --key "$key" --version-id "$version" "$target" >/dev/null
  chmod 600 "$target"
  actual="$(openssl dgst -sha256 -binary "$target" | base64 -w0)"
  [[ "$actual" == "$checksum" ]]
}

connect_talos() {
    # Octelium clientless credentials cannot reach TCP Services. This separate
    # CLIENT credential is limited by homelab-platform-talos-ci-access.
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" && -n "${OCE_OCTELIUM_CLIENT_AUTH_TOKEN:-}" &&
       -n "${OCE_TALOSCONFIG_B64:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    printf %s "$OCE_TALOSCONFIG_B64" | base64 --decode >"$work/talosconfig"
    chmod 600 "$work/talosconfig"
    bash scripts/ci/install-octelium-client.sh >/dev/null
    install -m 0700 -d "$work/octelium"
    OCTELIUM_AUTH_TOKEN="$OCE_OCTELIUM_CLIENT_AUTH_TOKEN" \
      "${HOME}/.local/bin/octelium" --homedir "$work/octelium" connect \
      --domain stinkyboi.com --implementation gvisor --ip-mode v4 --no-dns \
      --publish talos-api-ci.homelab:127.0.0.1:15000 >"$private_log" 2>&1 &
    tunnel_pid=$!
    # Preserve the reviewed certificate hostname while connecting to the
    # runner-local Octelium TCP listener; Talos mTLS remains mandatory.
    printf '127.0.0.1 talos-api.homelab.local.stinkyboi.com\n' | sudo tee -a /etc/hosts >/dev/null
    python3 - <<'PY'
import socket
import time
for attempt in range(60):
    try:
        with socket.create_connection(("127.0.0.1", 15000), timeout=2):
            break
    except OSError:
        time.sleep(2)
else:
    raise SystemExit("Talos TCP tunnel did not become ready")
PY
}

case "$stage" in
  inspect)
    connect_talos
    python3 -I scripts/platform-maintenance.py inspect --config "$config" \
      --talosconfig "$work/talosconfig" --output "$work/inspect.json"
    retain_result "$work/inspect.json" inspect
    ;;
  qualify)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    python3 scripts/network-policy-qualification.py --config "$config" --output "$work/qualification.json"
    retain_result "$work/qualification.json" qualification
    ;;
  owned-cleanup)
    [[ -n "${OCTELIUM_AUTH_TOKEN:-}" ]] || exit 1
    bash scripts/ci/install-kubeconfig.sh
    install -m 0700 -d "$work/receipts"
    load_receipt "openclaw-enterprise/platform/receipts/${GITHUB_SHA}/placement.json" \
      "$work/receipts/placement.json"
    load_receipt "openclaw-enterprise/platform/receipts/${GITHUB_SHA}/firewall-ownership.json" \
      "$work/receipts/firewall-ownership.json"
    # A versioned private attempt must exist before any firewall operation.
    # If the final upload fails, this marker still requires direct review.
    jq -n --arg sourceSha "$GITHUB_SHA" --arg runId "$GITHUB_RUN_ID" \
      '{format: 1, stage: "owned-firewall-cleanup", status: "attempted", verified: false,
        sourceSha: $sourceSha, runId: $runId}' >"$work/cleanup-attempt.json"
    chmod 600 "$work/cleanup-attempt.json"
    retain_result "$work/cleanup-attempt.json" cleanup-attempt
    if ! python3 scripts/network-policy-cleanup.py --config "$config" \
      --expected-sha "$GITHUB_SHA" --receipt-dir "$work/receipts" \
      --output "$work/cleanup.json"; then
      if [[ -f "$work/cleanup.json" && ! -L "$work/cleanup.json" ]]; then
        retain_result "$work/cleanup.json" cleanup-interrupted
      fi
      exit 1
    fi
    retain_result "$work/cleanup.json" cleanup
    ;;
  talos-*|kubernetes-*)
    [[ -n "${OCE_CONTROLPLANE_CONFIG_B64:-}" && -n "${OCE_WORKER_CONFIG_B64:-}" ]] || exit 1
    connect_talos
    printf %s "$OCE_CONTROLPLANE_CONFIG_B64" | base64 --decode >"$work/controlplane.yaml"
    printf %s "$OCE_WORKER_CONFIG_B64" | base64 --decode >"$work/worker.yaml"
    chmod 600 "$work/controlplane.yaml" "$work/worker.yaml"
    install -m 0700 -d "$work/receipts"
    if ! python3 -I scripts/platform-maintenance.py execute --config "$config" \
      --stage "$stage" --expected-sha "$GITHUB_SHA" \
      --talosconfig "$work/talosconfig" \
      --control-plane-config "$work/controlplane.yaml" \
      --worker-config "$work/worker.yaml" \
      --receipt-dir "$work/receipts" --output "$work/upgrade-error.json"; then
      if [[ -f "$work/upgrade-error.json" && ! -L "$work/upgrade-error.json" ]]; then
        retain_result "$work/upgrade-error.json" upgrade-error
      fi
      exit 1
    fi
    retain_result "$work/receipts/$stage.json" "$stage"
    ;;
esac
