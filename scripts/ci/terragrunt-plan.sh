#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

extra_plan_json_files=()
cleanup_dirs=()

azuread_credentials_available() {
  [[ -n "${ARM_CLIENT_ID:-}" && -n "${ARM_CLIENT_SECRET:-}" && -n "${ARM_TENANT_ID:-}" ]]
}

cleanup_temp_dirs() {
  local temp_dir

  for temp_dir in "${cleanup_dirs[@]}"; do
    if [[ -d "$temp_dir" ]]; then
      rm -rf "$temp_dir"
    fi
  done

  clear_plan_artifacts IaC/bootstrap IaC/live/argocd-apps IaC/live/azuread-applications
}

trap cleanup_temp_dirs EXIT

clear_plan_artifacts() {
  find "$@" \( -name plan.out -o -name plan.json \) -type f -delete
}

plan_out_for_unit() {
  local unit_dir

  unit_dir="$(cd "$1" && pwd -P)"
  find "$unit_dir" -name plan.out -type f -print -quit
}

plan_out_present() {
  local unit_dir="$1"
  local plan_file

  if plan_file="$(plan_out_for_unit "$unit_dir")" && [[ -n "$plan_file" ]]; then
    return 0
  fi

  return 1
}

render_plan_json_if_present() {
  local unit_dir="$1"
  local plan_file

  if plan_file="$(plan_out_for_unit "$unit_dir")" && [[ -n "$plan_file" ]]; then
    (
      cd "$unit_dir"
      terragrunt --log-disable show -json "$plan_file" >plan.json
    )
    return 0
  fi

  return 1
}

validate_terraform_plan_policies() {
  local plan_json_files=()

  while IFS= read -r plan_json_file; do
    plan_json_files+=("$plan_json_file")
  done < <(
    find IaC/bootstrap IaC/live/argocd-apps \
      IaC/live/azuread-applications \
      -name plan.json \
      -not -path '*/.terragrunt-cache/*' \
      -print 2>/dev/null | sort
  )

  if ((${#extra_plan_json_files[@]} > 0)); then
    plan_json_files+=("${extra_plan_json_files[@]}")
  fi

  if ((${#plan_json_files[@]} > 0)); then
    echo "::group::Terraform plan Conftest policies"
    conftest test --policy policy --output github "${plan_json_files[@]}"
    echo "::endgroup::"
  fi
}

plan_deleted_terragrunt_units() {
  local unit_dirs=("$@")
  local snapshot_dir
  local unit_dir
  local snapshot_unit_dir
  local state_list_file

  if ((${#unit_dirs[@]} == 0)); then
    return 0
  fi

  for unit_dir in "${unit_dirs[@]}"; do
    snapshot_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/terragrunt-deleted-plan.XXXXXX")"
    cleanup_dirs+=("$snapshot_dir")
    terragrunt_create_deleted_unit_destroy_stack "$snapshot_dir" "$unit_dir"
    snapshot_unit_dir="${snapshot_dir}/${unit_dir}"
    state_list_file="${snapshot_unit_dir}/state-resources.txt"

    if [[ ! -f "${snapshot_unit_dir}/terragrunt.hcl" ]]; then
      echo "Deleted Terragrunt unit ${unit_dir} fake stack was not generated." >&2
      exit 1
    fi

    echo "::group::Deleted Terragrunt unit state comparison: ${unit_dir}"
    (
      cd "$snapshot_unit_dir"
      rm -f plan.out plan.json
      terragrunt --log-disable init -no-color
      if ! terragrunt --log-disable state list >"$state_list_file"; then
        echo "Unable to list state for deleted Terragrunt unit ${unit_dir}; inspect the backend or credentials before applying." >&2
        exit 1
      fi
      if [[ -s "$state_list_file" ]]; then
        terragrunt plan -destroy -refresh=false -lock=false -out plan.out -no-color >/dev/null
      else
        echo "Deleted Terragrunt unit ${unit_dir} has no resources in remote state."
      fi
    )
    echo "::endgroup::"

    if [[ -s "$state_list_file" ]]; then
      if render_plan_json_if_present "$snapshot_unit_dir"; then
        extra_plan_json_files+=("${snapshot_unit_dir}/plan.json")
      fi
    fi
  done
}

prepare_terragrunt_filter_base
terragrunt_generate_stack
clear_plan_artifacts IaC/bootstrap IaC/live/argocd-apps IaC/live/azuread-applications

echo "::group::Argo CD bootstrap plan"
(
  cd IaC/bootstrap/argocd
  terragrunt plan -lock=false -out plan.out -no-color
)
echo "::endgroup::"
render_plan_json_if_present "IaC/bootstrap/argocd" || true

echo "IaC/live/aws-ssm-parameters is intentionally excluded from PR plans because it manages KMS, IAM, and secret declarations that require the protected production apply role."

echo "::group::Argo CD Application registration plan"
(
  cd IaC/live/argocd-apps
  terragrunt run --all --filter "$(terragrunt_changed_filter 'IaC/live/argocd-apps/*' true)" --parallelism 1 --source-update -- plan -lock=false -out plan.out -no-color
)
echo "::endgroup::"

while IFS= read -r unit_file; do
  unit_dir="$(dirname "$unit_file")"
  if plan_out_present "$unit_dir"; then
    render_plan_json_if_present "$unit_dir" >/dev/null
  fi
done < <(find IaC/live/argocd-apps -mindepth 2 -maxdepth 2 -name terragrunt.hcl -print | sort)

deleted_plan_units=()
while IFS= read -r deleted_unit_dir; do
  deleted_plan_units+=("$deleted_unit_dir")
done < <(terragrunt_deleted_unit_paths)

plan_deleted_terragrunt_units "${deleted_plan_units[@]}"

echo "::group::AzureAD application registration plan"
if azuread_credentials_available; then
  (
    cd IaC/live/azuread-applications
    terragrunt run --all --filter "$(terragrunt_changed_filter 'IaC/live/azuread-applications/*' true)" --parallelism 1 --source-update -- plan -lock=false -out plan.out -no-color
  )

  while IFS= read -r unit_file; do
    unit_dir="$(dirname "$unit_file")"
    if plan_out_present "$unit_dir"; then
      render_plan_json_if_present "$unit_dir" >/dev/null
    fi
  done < <(find IaC/live/azuread-applications -mindepth 2 -maxdepth 2 -name terragrunt.hcl -print | sort)
else
  echo "::warning::Skipping AzureAD application registration plan because ARM_CLIENT_ID, ARM_CLIENT_SECRET, and ARM_TENANT_ID are not configured for this plan run."
fi
echo "::endgroup::"

validate_terraform_plan_policies

echo "IaC/live/kubernetes-secrets is intentionally excluded from PR plans because it reads decrypted SSM parameters."
