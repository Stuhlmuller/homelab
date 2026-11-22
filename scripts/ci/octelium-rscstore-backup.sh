#!/usr/bin/env bash
# Protected entry point for the Octelium resource-store preflight and backup.
set -euo pipefail
umask 077

phase="${1:-}"
case "$phase" in init|cluster|publish|cleanup) ;; *) exit 2 ;; esac
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_EVENT_NAME:-}" == workflow_dispatch &&
   "${GITHUB_REPOSITORY:-}" == Stuhlmuller/homelab && "${GITHUB_REF:-}" == refs/heads/main &&
   "${GITHUB_WORKFLOW_REF:-}" == Stuhlmuller/homelab/.github/workflows/octelium-rscstore-backup.yml@refs/heads/main &&
   "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ && "${GITHUB_RUN_ATTEMPT:-}" == 1 &&
   "${GITHUB_ACTOR_ID:-}" == 57728706 ]] || exit 2

workspace="$HOME/.octelium-rscstore-$GITHUB_RUN_ID"
if [[ "$phase" == cleanup ]]; then
  [[ ! -L "$workspace" ]] || exit 1
  if [[ -d "$workspace" ]]; then rm -rf -- "$workspace"; fi
  exit 0
fi
[[ "${BACKUP_STAGE:-}" == preflight || "${BACKUP_STAGE:-}" == backup ]]
[[ "${EXPECTED_SHA:-}" =~ ^[0-9a-f]{40}$ && "$EXPECTED_SHA" == "${GITHUB_SHA:-}" &&
   "$EXPECTED_SHA" == "${GITHUB_WORKFLOW_SHA:-}" && "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]]
bash scripts/ci/terragrunt-current-main.sh

if [[ "$phase" == init ]]; then
  mkdir -m 0700 -- "$workspace"
  exit 0
fi
[[ -d "$workspace" && ! -L "$workspace" && "$(stat -c %a "$workspace")" == 700 ]]
EXPECTED_PVC_UID="$(jq -er '.inputs.pvc_uid' "$GITHUB_EVENT_PATH")"
EXPECTED_PV_UID="$(jq -er '.inputs.pv_uid' "$GITHUB_EVENT_PATH")"
export EXPECTED_PVC_UID EXPECTED_PV_UID

if [[ "$phase" == cluster ]]; then
  if [[ "$BACKUP_STAGE" == backup ]]; then
    [[ "${PREFLIGHT_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]]
    reviewed="$(gh api "repos/Stuhlmuller/homelab/actions/runs/$PREFLIGHT_RUN_ID" | jq -er '
      select(.head_branch == "main" and .event == "workflow_dispatch" and .conclusion == "success"
        and .path == ".github/workflows/octelium-rscstore-backup.yml"
        and .display_title == ("Octelium rscstore preflight @ " + .head_sha)) | .head_sha')"
    [[ "$reviewed" =~ ^[0-9a-f]{40}$ ]]
    git merge-base --is-ancestor "$reviewed" "$EXPECTED_SHA"
    git diff --quiet "$reviewed" "$EXPECTED_SHA" -- \
      .github/workflows/octelium-rscstore-backup.yml flake.nix flake.lock \
      scripts/octelium-rscstore-capture.py scripts/application-backup.py \
      scripts/ci/octelium-rscstore-backup.sh scripts/ci/octelium-rscstore-backup-receipt.py \
      scripts/ci/install-kubeconfig.sh scripts/ci/install-octelium-client.sh \
      IaC/terragrunt-catalog/modules/aws-octelium-rscstore-backup
  else
    [[ -z "${PREFLIGHT_RUN_ID:-}" ]]
  fi
  : "${OCTELIUM_AUTH_TOKEN:?missing dedicated Kubernetes transport credential}"
  : "${RSCSTORE_TALOS_TOKEN:?missing dedicated Talos relay credential}"
  : "${RSCSTORE_TALOSCONFIG_B64:?missing dedicated Talos client configuration}"
  install -m 0700 -d "$workspace/cluster-home" "$workspace/bin" "$workspace/octelium"
  export KUBE_API_SERVER_URL=https://kubernetes-api-ci.stinkyboi.com
  env -u KUBECONFIG HOME="$workspace/cluster-home" bash scripts/ci/install-kubeconfig.sh
  export KUBECONFIG="$workspace/cluster-home/.kube/config"
  printf %s "$RSCSTORE_TALOSCONFIG_B64" | base64 --decode >"$workspace/talosconfig"
  OCTELIUM_INSTALL_DIR="$workspace/bin" bash scripts/ci/install-octelium-client.sh
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --max-time 180 \
    'https://github.com/siderolabs/talos/releases/download/v1.11.3/talosctl-linux-amd64' \
    --output "$workspace/bin/talosctl"
  printf '%s  %s\n' 7cd3a0d25a8f2dea343c2815431cc07d3e80bab124e7c3e22738819dc09c1b3f \
    "$workspace/bin/talosctl" | sha256sum --check --status
  chmod 0700 "$workspace/bin/talosctl"
  export PATH="$workspace/bin:$PATH"
  # Use the same certificate hostname as protected Platform Maintenance.
  printf '127.0.0.1 talos-api.homelab.local.stinkyboi.com\n' | sudo tee -a /etc/hosts >/dev/null
  OCTELIUM_AUTH_TOKEN="$RSCSTORE_TALOS_TOKEN" "$workspace/bin/octelium" \
    --homedir "$workspace/octelium" connect --domain stinkyboi.com \
    --implementation gvisor --ip-mode v4 --no-dns \
    --publish talos-api-ci.homelab:127.0.0.1:15000 >"$workspace/tunnel.log" 2>&1 &
  tunnel_pid=$!
  trap '
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
    rm -f -- "$workspace/talosconfig" "$KUBECONFIG"' EXIT
  python3 -I - <<'PY'
import socket
import time
for _ in range(30):
    try:
        with socket.create_connection(("127.0.0.1", 15000), timeout=2):
            break
    except OSError:
        time.sleep(2)
else:
    raise SystemExit("Talos relay did not become ready")
PY
  capture_mode=preflight-actions
  if [[ "$BACKUP_STAGE" == backup ]]; then capture_mode=capture-actions; fi
  python3 -I scripts/octelium-rscstore-capture.py "$capture_mode" \
    --workspace "$workspace" --expected-sha "$EXPECTED_SHA" \
    --talosconfig "$workspace/talosconfig" --expected-pvc-uid "$EXPECTED_PVC_UID" \
    --expected-pv-uid "$EXPECTED_PV_UID" >"$workspace/cluster-result"
  exit 0
fi

aws_cli="$(command -v aws)"
: "${AWS_ACCESS_KEY_ID:?missing OIDC session}"
: "${AWS_SECRET_ACCESS_KEY:?missing OIDC session}"
: "${AWS_SESSION_TOKEN:?missing short-lived OIDC session}"
profile_home="$workspace/aws-home"
install -m 0700 -d "$profile_home/.aws"
# The existing publisher drops AWS_* variables. Supply only this invocation's
# credentials through its explicit file-backed profile.
printf '[octelium-rscstore]\naws_access_key_id=%s\naws_secret_access_key=%s\naws_session_token=%s\n' \
  "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" "$AWS_SESSION_TOKEN" \
  >"$profile_home/.aws/credentials"
trap 'rm -f -- "$profile_home/.aws/credentials"' EXIT
chmod 0600 "$profile_home/.aws/credentials"
if [[ "$BACKUP_STAGE" == preflight ]]; then
  test -s "$workspace/cluster-result"
  HOME="$profile_home" python3 -I scripts/ci/octelium-rscstore-backup-receipt.py \
    "$aws_cli" "$workspace" "$GITHUB_RUN_ID" preflight
  exit 0
fi
stamp="$(cat "$workspace/cluster-result")"
[[ "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]
identifier="$(python3 -I scripts/application-backup.py prepare --app octelium-rscstore \
  --workspace "$workspace" --source "$workspace/$stamp")"
[[ "$identifier" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{64}$ ]]
bash scripts/ci/terragrunt-current-main.sh
HOME="$profile_home" python3 -I scripts/application-backup.py publish --app octelium-rscstore \
  --workspace "$workspace" --id "$identifier" --create-only \
  --profile octelium-rscstore --aws-cli "$aws_cli" >/dev/null
HOME="$profile_home" python3 -I scripts/octelium-rscstore-capture.py prove-retrieval \
  --workspace "$workspace" --id "$identifier" --proof "$workspace/proof" \
  --profile octelium-rscstore --aws-cli "$aws_cli"
HOME="$profile_home" python3 -I scripts/ci/octelium-rscstore-backup-receipt.py \
  "$aws_cli" "$workspace" "$GITHUB_RUN_ID" backup
