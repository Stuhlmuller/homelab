#!/usr/bin/env bash
# Protected, source-pinned entry point. Upgrade execution remains disabled until
# each node receipt can be retained outside the ephemeral Actions runner.
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
  local result="$1" name="$2" key version
  [[ -f "$result" && ! -L "$result" && "$(stat -c %a "$result")" == 600 ]] || exit 1
  key="openclaw-enterprise/platform/${GITHUB_SHA}/${GITHUB_RUN_ID}/${name}.json"
  aws s3api put-object --bucket "$bucket" --key "$key" --body "$result" \
    --server-side-encryption aws:kms >/dev/null
  version="$(aws s3api head-object --bucket "$bucket" --key "$key" --query VersionId --output text)"
  [[ -n "$version" && "$version" != None && "$version" != null ]] || exit 1
}

case "$stage" in
  inspect)
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
    python3 scripts/platform-maintenance.py inspect --config "$config" \
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
    aws s3api get-object --bucket "$bucket" \
      --key "openclaw-enterprise/platform/receipts/${GITHUB_SHA}/placement.json" \
      "$work/receipts/placement.json" >/dev/null
    chmod 600 "$work/receipts/placement.json"
    aws s3api get-object --bucket "$bucket" \
      --key "openclaw-enterprise/platform/receipts/${GITHUB_SHA}/firewall-ownership.json" \
      "$work/receipts/firewall-ownership.json" >/dev/null
    chmod 600 "$work/receipts/firewall-ownership.json"
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
    # The executor writes per-node receipts on the runner. A reviewed durable
    # per-node write-through path and fresh private recovery evidence are still
    # required before it may ever invoke a Talos/Kubernetes upgrade.
    [[ -n "${OCE_OCTELIUM_CLIENT_AUTH_TOKEN:-}" && -n "${OCE_TALOSCONFIG_B64:-}" &&
       -n "${OCE_CONTROLPLANE_CONFIG_B64:-}" && -n "${OCE_WORKER_CONFIG_B64:-}" ]] || exit 1
    echo 'Platform upgrade blocked: durable per-node receipts and recovery verification are not wired.' >&2
    exit 1
    ;;
esac
