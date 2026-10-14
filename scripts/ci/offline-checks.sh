#!/usr/bin/env bash
set -euo pipefail

# Generated units are fixtures here; no provider init or live API access.
source scripts/ci/terragrunt-filter-base.sh
terragrunt_generate_stack

python3 -I scripts/ci/speckit-check.py
python3 -I scripts/ci/openwiki-check.py
python3 -I scripts/ci/multica-runtime-check.py
python3 -I scripts/ci/traefik-routes-test.py
python3 -I scripts/ci/install-kubeconfig-test.py
python3 -I scripts/ci/tailscale-ci-configure-test.py
python3 -I scripts/ci/tailscale-ingress-sign-test.py
python3 -I scripts/ci/tailscale-access-check-test.py
python3 -I scripts/ci/tailscale-identity-check-test.py
python3 -I scripts/ci/octelium-api-response-test.py
python3 -I scripts/ci/tailscale-private-dns-test.py
python3 -I scripts/ci/multica-desktop-connect-test.py
python3 -I scripts/ci/policy-bot-webhook-test.py
python3 -I scripts/ci/n8n-github-webhooks-test.py
python3 -I scripts/ci/cordium-check-test.py
python3 -I scripts/ci/cordium-ci-acceptance-test.py
python3 -I scripts/ci/cordium-ci-transport-test.py
python3 -I scripts/ci/cordium-ci-retire-test.py
python3 -I scripts/ci/octelium-service-retire-test.py
python3 -I scripts/ci/cordium-ci-reconcile-test.py
python3 -I scripts/ci/cordium-isolation-check-test.py
python3 -I scripts/ci/nofx-registry-credential-test.py
python3 -I scripts/ci/litellm-provider-credential-test.py
python3 -I scripts/ci/litellm-postgres-check.py
python3 -I scripts/ci/langfuse-valkey-recovery-test.py
python3 -I scripts/ci/entra-ci-configure-test.py
python3 -I scripts/ci/entra-oidc-verify-test.py
python3 -I scripts/ci/octelium-entra-oidc-test.py
python3 scripts/ci/octelium-nofx-reconcile-test.py
python3 -I scripts/ci/octelium-harbor-reconcile-test.py
python3 -I scripts/ci/octelium-langfuse-reconcile-test.py
python3 -I scripts/ci/octelium-bazarr-reconcile-test.py
python3 -I scripts/ci/bazarr-bootstrap-test.py
python3 -I scripts/ci/nas-media-permissions-test.py
python3 -I scripts/ci/harbor-bootstrap-test.py
python3 -I scripts/ci/harbor-vulnerability-exporter-test.py
python3 -I scripts/ci/fleet-bootstrap-test.py
python3 -I scripts/ci/fleet-backup-test.py
python3 -I scripts/ci/fleet-apple-csr-test.py
python3 -I scripts/ci/fleet-free-setup-test.py
python3 -I scripts/ci/fleet-airvpn-setup-test.py
python3 -I scripts/ci/harbor-publish-test.py
python3 -I scripts/ci/harbor-core-source-test.py
python3 -I scripts/ci/harbor-core-scan-check-test.py
python3 -I scripts/ci/harbor-render-check-test.py
python3 -I scripts/ci/harbor-images-check-test.py
python3 -I scripts/ci/image-automation-test.py
python3 -I scripts/ci/image-automation-promote-test.py
python3 -I scripts/ci/image-automation-alert-test.py
python3 -I scripts/ci/image-automation.py check
python3 -I scripts/ci/image-automation.py render-check
python3 -I scripts/ci/harbor-images-check.py
python3 -I scripts/ci/network-policy-inventory-test.py
python3 -I scripts/ci/talos-harbor-mirror-credential-test.py
python3 -I scripts/ci/talos-harbor-mirrors-test.py
python3 -I scripts/ci/talos-nix-builder-seccomp-test.py
python3 scripts/ci/octelium-tunnel-check-test.py
python3 -I scripts/ci/octelium-macos-api-carrier-test.py
python3 scripts/ci/octelium-restore-drill-test.py
python3 scripts/ci/terragrunt-apply-stage-test.py
python3 scripts/ci/terragrunt-plan-stage-test.py
python3 scripts/ci/istio-ambient-log-check-test.py
python3 scripts/ci/istio-ambient-probe-check.py
python3 -I scripts/ci/affine-suspension-probe-check.py
python3 scripts/ci/talos-etcd-backup-check.py
python3 scripts/ci/talos-etcd-schedule-check.py
python3 scripts/ci/etcd-offline-restore-check-test.py
python3 -I scripts/ci/application-backup-test.py
python3 -I scripts/ci/application-backup-restore-test.py
python3 -I scripts/ci/application-backup-rules-test.py
python3 scripts/ci/job-alert-recovery-check.py
python3 -I scripts/ci/memory-overcommit-check.py
python3 -I scripts/ci/terragrunt-stack-test.py
python3 scripts/ci/terragrunt-apply-test.py
python3 scripts/ci/etcd-offsite-backup-check.py
python3 scripts/ci/etcd-offsite-schedule-check.py
python3 -I scripts/ci/n8n-ai-migration-check.py
python3 -I scripts/ci/clickhouse-log-quarantine-test.py
python3 scripts/ci/gluetun-cpu-profile-check.py
python3 scripts/ci/deluge-daemon-status-test.py
python3 -I scripts/ci/deluge-catalog-recovery-test.py
python3 scripts/ci/langfuse-staging-check.py
python3 scripts/ci/openclaw-config-check.py
python3 scripts/ci/openclaw-assistant-check.py
python3 scripts/ci/openclaw-runtime-storage-check.py
python3 -I scripts/ci/nix-cache-test.py
bash scripts/ci/offline-static-checks.sh
