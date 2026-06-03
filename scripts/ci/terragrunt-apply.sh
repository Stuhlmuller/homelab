#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

prepare_terragrunt_filter_base

echo "::group::Argo CD bootstrap apply"
(
  cd IaC/bootstrap
  terragrunt run --all --filter-affected --non-interactive --parallelism 1 -- apply -no-color -auto-approve
)
echo "::endgroup::"

echo "::group::AWS SSM parameter declaration plan and apply"
(
  cd IaC/live/aws-ssm-parameters
  rm -f plan.out plan.json
  terragrunt plan -out plan.out -no-color
  terragrunt --log-disable show -json plan.out >plan.json
  conftest test --policy ../../../policy --output github plan.json
  terragrunt apply -no-color plan.out
)
echo "::endgroup::"

echo "::group::External Secrets AWS auth legacy state cleanup"
bash scripts/ci/remove-external-secrets-aws-auth-state.sh
echo "::endgroup::"

echo "::group::External Secrets AWS auth Secret install"
bash scripts/ci/install-external-secrets-aws-auth.sh
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
    terragrunt run --all --filter-affected --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
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
  terragrunt run --all --filter-affected --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
)
echo "::endgroup::"
