#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

plan_markdown="${TERRAGRUNT_PLAN_MARKDOWN:-${RUNNER_TEMP:-/tmp}/terragrunt-plan.md}"
mkdir -p "$(dirname "$plan_markdown")"
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
}

trap cleanup_temp_dirs EXIT

clear_plan_artifacts() {
  find "$@" \( -name plan.out -o -name plan.json \) -type f -delete
}

render_plan_out() {
  local title="$1"
  local unit_dir="$2"

  {
    printf '<details>\n'
    printf '<summary>%s</summary>\n\n' "$title"
    printf '~~~~text\n'
    (
      cd "$unit_dir"
      terragrunt --log-disable show -no-color plan.out
    )
    printf '~~~~\n\n'
    printf '</details>\n\n'
  } >>"$plan_markdown"
}

render_plan_out_if_present() {
  local title="$1"
  local unit_dir="$2"

  if [[ -f "${unit_dir}/plan.out" ]]; then
    render_plan_out "$title" "$unit_dir"
    return 0
  fi

  return 1
}

render_plan_json_if_present() {
  local unit_dir="$1"

  if [[ -f "${unit_dir}/plan.out" ]]; then
    (
      cd "$unit_dir"
      terragrunt --log-disable show -json plan.out >plan.json
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

append_plan_note() {
  local message="$1"

  {
    printf '> %s\n\n' "$message"
  } >>"$plan_markdown"
}

append_deleted_unit_note() {
  local message="$1"
  shift

  {
    printf '### Deleted Terragrunt Units\n\n'
    printf '%s\n\n' "$message"
    for unit_dir in "$@"; do
      printf -- '- `%s`\n' "$unit_dir"
    done
    printf '\n'
  } >>"$plan_markdown"
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

  append_deleted_unit_note "The current checkout deleted these Terragrunt units. The plan script creates temporary empty Terragrunt units at the deleted paths, reuses \`root.hcl\` so each fake unit points at the original backend key, lists the state resources, and plans their removal without replaying deleted module code." "${unit_dirs[@]}"

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
      {
        printf '<details>\n'
        printf '<summary>Deleted Terragrunt unit state: %s</summary>\n\n' "$unit_dir"
        printf '~~~~text\n'
        cat "$state_list_file"
        printf '~~~~\n\n'
        printf '</details>\n\n'
      } >>"$plan_markdown"

      if render_plan_json_if_present "$snapshot_unit_dir"; then
        extra_plan_json_files+=("${snapshot_unit_dir}/plan.json")
      fi
    else
      append_plan_note "Deleted Terragrunt unit \`${unit_dir}\` had no resources in remote state."
    fi
  done
}

prepare_terragrunt_filter_base
clear_plan_artifacts IaC/bootstrap IaC/live/argocd-apps IaC/live/azuread-applications

{
  printf '## Terragrunt Plan Output\n\n'
  printf 'Rendered from saved `plan.out` files with `terragrunt show -no-color plan.out`.\n\n'
  if [[ -n "${GITHUB_SHA:-}" ]]; then
    printf 'Source commit: `%s`.\n\n' "$GITHUB_SHA"
  fi
  printf '> `IaC/live/aws-ssm-parameters` and `IaC/live/kubernetes-secrets` are intentionally excluded from PR plans because they require protected apply credentials or decrypted SSM reads.\n\n'
} >"$plan_markdown"

echo "::group::Argo CD bootstrap plan"
(
  cd IaC/bootstrap
  terragrunt run --all --filter 'IaC/bootstrap/argocd | [main...HEAD]' --parallelism 1 -- plan -lock=false -no-color
)
echo "::endgroup::"
if ! render_plan_out_if_present "Argo CD bootstrap" "IaC/bootstrap/argocd"; then
  append_plan_note "No affected Argo CD bootstrap units were planned."
fi
render_plan_json_if_present "IaC/bootstrap/argocd" || true

echo "IaC/live/aws-ssm-parameters is intentionally excluded from PR plans because it manages KMS, IAM, and secret declarations that require the protected production apply role."

echo "::group::Argo CD Application registration plan"
(
  cd IaC/live/argocd-apps
  terragrunt run --all --filter 'IaC/live/argocd-apps/* | [main...HEAD]' --parallelism 1 --source-update -- plan -lock=false -no-color
)
echo "::endgroup::"

planned_app_count=0
while IFS= read -r unit_file; do
  unit_dir="$(dirname "$unit_file")"
  unit_name="$(basename "$unit_dir")"
  if render_plan_out_if_present "Argo CD Application: ${unit_name}" "$unit_dir"; then
    planned_app_count=$((planned_app_count + 1))
    render_plan_json_if_present "$unit_dir" >/dev/null
  fi
done < <(find IaC/live/argocd-apps -mindepth 2 -maxdepth 2 -name terragrunt.hcl -print | sort)

if [[ "$planned_app_count" -eq 0 ]]; then
  append_plan_note "No affected Argo CD Application registration units were planned."
fi

deleted_plan_units=()
while IFS= read -r deleted_unit_dir; do
  deleted_plan_units+=("$deleted_unit_dir")
done < <(terragrunt_deleted_unit_paths)

plan_deleted_terragrunt_units "${deleted_plan_units[@]}"

echo "::group::AzureAD application registration plan"
if azuread_credentials_available; then
  (
    cd IaC/live/azuread-applications
    terragrunt run --all --filter 'IaC/live/azuread-applications/* | [main...HEAD]' --parallelism 1 --source-update -- plan -lock=false -no-color
  )

  planned_azuread_count=0
  while IFS= read -r unit_file; do
    unit_dir="$(dirname "$unit_file")"
    unit_name="$(basename "$unit_dir")"
    if render_plan_out_if_present "AzureAD application: ${unit_name}" "$unit_dir"; then
      planned_azuread_count=$((planned_azuread_count + 1))
      render_plan_json_if_present "$unit_dir" >/dev/null
    fi
  done < <(find IaC/live/azuread-applications -mindepth 2 -maxdepth 2 -name terragrunt.hcl -print | sort)

  if [[ "$planned_azuread_count" -eq 0 ]]; then
    append_plan_note "No AzureAD application registration plans were rendered."
  fi
else
  echo "::warning::Skipping AzureAD application registration plan because ARM_CLIENT_ID, ARM_CLIENT_SECRET, and ARM_TENANT_ID are not configured for this plan run."
  append_plan_note "AzureAD application registration plans were skipped because the plan environment did not provide \`ARM_CLIENT_ID\`, \`ARM_CLIENT_SECRET\`, and \`ARM_TENANT_ID\`. Production apply still fails fast when \`IaC/live/azuread-applications\` changes and those credentials are absent."
fi
echo "::endgroup::"

validate_terraform_plan_policies

echo "IaC/live/kubernetes-secrets is intentionally excluded from PR plans because it reads decrypted SSM parameters."
