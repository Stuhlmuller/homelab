#!/usr/bin/env bash
set -euo pipefail

echo "::group::Argo CD bootstrap apply"
(
  cd IaC/bootstrap/argocd
  terragrunt --log-disable apply -no-color -auto-approve
)
echo "::endgroup::"

echo "::group::AWS SSM parameter declaration apply"
(
  cd IaC/live/aws-ssm-parameters
  terragrunt --log-disable apply -no-color -auto-approve
)
echo "::endgroup::"

azuread_credentials_available() {
  [[ -n "${ARM_CLIENT_ID:-}" && -n "${ARM_CLIENT_SECRET:-}" && -n "${ARM_TENANT_ID:-}" ]]
}

azuread_stack_changed() {
  local base_sha="${APPLY_BASE_SHA:-}"
  local head_sha="${APPLY_HEAD_SHA:-${GITHUB_SHA:-HEAD}}"

  if [[ -z "$base_sha" || "$base_sha" =~ ^0+$ ]]; then
    return 0
  fi

  if ! git cat-file -e "${base_sha}^{commit}" 2>/dev/null; then
    return 0
  fi

  ! git diff --quiet "$base_sha" "$head_sha" -- IaC/live/azuread-applications
}

echo "::group::AzureAD application registration apply"
if azuread_credentials_available; then
  (
    cd IaC/live/azuread-applications
    terragrunt run --all --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
  )
elif azuread_stack_changed; then
  echo "AzureAD credentials are required because IaC/live/azuread-applications changed or the apply diff could not be determined." >&2
  echo "Set AZUREAD_CLIENT_ID, AZUREAD_CLIENT_SECRET, and AZUREAD_TENANT_ID on homelab-production." >&2
  exit 1
else
  echo "::warning::Skipping AzureAD application registration because AzureAD credentials are not configured and IaC/live/azuread-applications did not change in this push."
fi
echo "::endgroup::"

echo "::group::Argo CD Application registration apply"
(
  cd IaC/live/argocd-apps
  terragrunt run --all --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
)
echo "::endgroup::"

echo "::group::Kubernetes secret materialization apply"
(
  cd IaC/live/kubernetes-secrets
  terragrunt run --all --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
)
echo "::endgroup::"
