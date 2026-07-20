#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

cleanup_dirs=()

cleanup_temp_dirs() {
  local temp_dir

  for temp_dir in "${cleanup_dirs[@]}"; do
    if [[ -d "$temp_dir" ]]; then
      rm -rf "$temp_dir"
    fi
  done
}

trap cleanup_temp_dirs EXIT

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

destroy_deleted_terragrunt_units() {
  local deleted_units=()
  local snapshot_dir
  local unit_dir
  local snapshot_unit_dir
  local state_list_file

  while IFS= read -r unit_dir; do
    deleted_units+=("$unit_dir")
  done < <(terragrunt_deleted_unit_paths)

  if ((${#deleted_units[@]} == 0)); then
    echo "No deleted Terragrunt units require destroy handling."
    return 0
  fi

  for unit_dir in "${deleted_units[@]}"; do
    snapshot_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/terragrunt-deleted-apply.XXXXXX")"
    cleanup_dirs+=("$snapshot_dir")
    terragrunt_create_deleted_unit_destroy_stack "$snapshot_dir" "$unit_dir"
    snapshot_unit_dir="${snapshot_dir}/${unit_dir}"
    state_list_file="${snapshot_unit_dir}/state-resources.txt"

    if [[ ! -f "${snapshot_unit_dir}/terragrunt.hcl" ]]; then
      echo "Deleted Terragrunt unit ${unit_dir} fake stack was not generated." >&2
      exit 1
    fi

    echo "::group::Deleted Terragrunt unit state destroy: ${unit_dir}"
    (
      cd "$snapshot_unit_dir"
      terragrunt --log-disable init -no-color
      if ! terragrunt --log-disable state list >"$state_list_file"; then
        echo "Unable to list state for deleted Terragrunt unit ${unit_dir}; inspect the backend or credentials before applying." >&2
        exit 1
      fi
      if [[ -s "$state_list_file" ]]; then
        echo "Resources in deleted Terragrunt unit state:"
        cat "$state_list_file"
        terragrunt plan -destroy -refresh=false -out plan.out -no-color >/dev/null
        terragrunt apply -no-color plan.out
      else
        echo "Deleted Terragrunt unit ${unit_dir} has no resources in remote state."
      fi
    )
    echo "::endgroup::"
  done
}

adopt_existing_ssm_parameters() {
  local parameter_region="us-west-2"
  local state_resources
  local parameter_name
  local resource_address
  local existing_name

  terragrunt init -no-color
  state_resources="$(terragrunt state list -no-color 2>/dev/null || true)"

  for parameter_name in "/homelab/github-actions-runner/registration-token"; do
    resource_address="aws_ssm_parameter.this[\"${parameter_name}\"]"

    if grep -Fxq "$resource_address" <<<"$state_resources"; then
      echo "SSM parameter ${parameter_name} is already managed in OpenTofu state."
      continue
    fi

    existing_name="$(
      aws ssm describe-parameters \
        --region "$parameter_region" \
        --parameter-filters "Key=Name,Option=Equals,Values=${parameter_name}" \
        --query "Parameters[0].Name" \
        --output text 2>/dev/null || true
    )"

    if [[ "$existing_name" == "$parameter_name" ]]; then
      echo "Adopting existing SSM parameter ${parameter_name} into OpenTofu state."
      terragrunt import -no-color "$resource_address" "$parameter_name"
      state_resources="${state_resources}"$'\n'"${resource_address}"
    else
      echo "SSM parameter ${parameter_name} is absent; OpenTofu will create the placeholder."
    fi
  done
}

prepare_terragrunt_filter_base

if ! azuread_credentials_available && azuread_stack_changed; then
  echo "AzureAD credentials are required because IaC/live/azuread-applications changed or the apply diff could not be determined." >&2
  echo "Set AZUREAD_CLIENT_ID, AZUREAD_CLIENT_SECRET, and AZUREAD_TENANT_ID on homelab-production." >&2
  exit 1
fi

destroy_deleted_terragrunt_units

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
  adopt_existing_ssm_parameters
  terragrunt plan -out plan.out -no-color
  terragrunt --log-disable show -json plan.out >plan.json
  conftest test --policy ../../../policy --output github plan.json
  terragrunt apply -no-color plan.out
)
echo "::endgroup::"

echo "::group::Kubernetes node label apply"
(
  cd IaC/live/kubernetes-node-labels
  rm -f plan.out plan.json
  terragrunt plan -out plan.out -no-color
  terragrunt --log-disable show -json plan.out >plan.json
  conftest test --policy ../../../policy --output github plan.json
  terragrunt apply -no-color plan.out
)
echo "::endgroup::"

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

echo "::group::External Secrets AWS auth Secret state adoption"
kubectl apply -f clusters/homelab/apps/external-secrets/namespace.yaml
if kubectl -n external-secrets get secret aws-ssm-auth >/dev/null 2>&1; then
  (
    cd IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth
    terragrunt init -no-color
    if ! terragrunt state list -no-color 2>/dev/null | grep -Fxq 'kubernetes_secret_v1.this'; then
      terragrunt import -no-color kubernetes_secret_v1.this external-secrets/aws-ssm-auth
    fi
  )
else
  echo "external-secrets/aws-ssm-auth is absent; Kubernetes secret materialization will create it from SSM."
fi
echo "::endgroup::"

echo "::group::Kubernetes secret materialization apply"
(
  cd IaC/live/kubernetes-secrets
  terragrunt run --all --filter-affected --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
)
echo "::endgroup::"
