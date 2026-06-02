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

echo "::group::AWS SSM parameter declaration apply"
(
  cd IaC/live/aws-ssm-parameters
  terragrunt run --all --filter-affected --non-interactive --parallelism 1 -- apply -no-color -auto-approve
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

echo "::group::Kubernetes secret materialization apply"
(
  cd IaC/live/kubernetes-secrets
  terragrunt run --all --filter-affected --non-interactive --parallelism 1 --source-update -- apply -no-color -auto-approve
)
echo "::endgroup::"
