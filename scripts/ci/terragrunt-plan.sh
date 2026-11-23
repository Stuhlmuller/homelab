#!/usr/bin/env bash
# shellcheck disable=SC1091 # shared helper path is resolved from this script
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

extra_plan_json_files=()
cleanup_dirs=()
azuread_report_args=()
# OpenTofu >= 1.10 shares providers safely via Terragrunt's automatic cache. Never cache
# .terragrunt-cache, which can contain state, credentials and saved plans.
export TG_USE_PARTIAL_PARSE_CONFIG_CACHE=true
export TG_PROVIDER_CACHE_DIR="${TG_PROVIDER_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/terragrunt/providers}"
mkdir -p "$TG_PROVIDER_CACHE_DIR"

azuread_credentials_available() {
  [[ -n "${ARM_CLIENT_ID:-}" && -n "${ARM_TENANT_ID:-}" ]] || return 1
  case "${ARM_USE_OIDC:-false}" in
    true)
      [[ -n "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" && -n "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]]
      ;;
    false) [[ -n "${ARM_CLIENT_SECRET:-}" ]] ;;
    *) return 1 ;;
  esac
}

cleanup_temp_dirs() {
  local temp_dir

  for temp_dir in "${cleanup_dirs[@]}"; do
    if [[ -d "$temp_dir" ]]; then
      rm -rf "$temp_dir"
    fi
  done

  clear_plan_artifacts IaC/homelab/us-west-2/bootstrap IaC/homelab/us-west-2/apps IaC/homelab/us-west-2/operator/application-backup-storage
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
    find IaC/homelab/us-west-2/bootstrap IaC/homelab/us-west-2/apps IaC/homelab/us-west-2/operator/application-backup-storage \
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
  local source_dir state_list_file

  if ((${#unit_dirs[@]} == 0)); then
    return 0
  fi

  for unit_dir in "${unit_dirs[@]}"; do
    source_dir="$(terragrunt_deleted_unit_source "$unit_dir")"
    if ! terragrunt_unit_affected "$source_dir" "$affected_units"; then
      echo "Terragrunt did not discover deleted unit ${source_dir}; refusing retirement plan." >&2
      return 1
    fi
    if [[ "$unit_dir" == IaC/live/azuread-applications/* ]] && ! azuread_credentials_available; then
      echo "AzureAD credentials are required for deleted AzureAD units." >&2
      return 1
    fi
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
        terragrunt plan -destroy -refresh=false -lock=false -out plan.out -no-color
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
clear_plan_artifacts IaC/homelab/us-west-2/bootstrap IaC/homelab/us-west-2/apps IaC/homelab/us-west-2/operator/application-backup-storage
affected_units="$(terragrunt_affected_units)"
argocd_plan_filters=()
azuread_plan_filters=()
while IFS= read -r unit; do
  [[ -f "$unit/terragrunt.hcl" ]] || continue
  case "$unit" in
    IaC/homelab/us-west-2/apps/*/argocd) argocd_plan_filters+=(--filter "./${unit#IaC/homelab/us-west-2/apps/}") ;;
    IaC/homelab/us-west-2/apps/*/azuread|IaC/homelab/us-west-2/apps/fleet/pilot-user) azuread_plan_filters+=(--filter "./${unit#IaC/homelab/us-west-2/apps/}") ;;
  esac
done <<<"$affected_units"

if terragrunt_active_unit_affected IaC/homelab/us-west-2/bootstrap/argocd "$affected_units"; then
  echo "::group::Argo CD bootstrap plan"
  (
    cd IaC/homelab/us-west-2/bootstrap/argocd
    terragrunt plan -lock=false -out plan.out -no-color
  )
  echo "::endgroup::"
  render_plan_json_if_present "IaC/homelab/us-west-2/bootstrap/argocd"
fi

if terragrunt_active_unit_affected IaC/homelab/us-west-2/operator/application-backup-storage "$affected_units"; then
  echo "::group::OpenClaw legacy offsite bucket plan"
  (
    cd IaC/homelab/us-west-2/operator/application-backup-storage
    terragrunt plan -lock=false -out plan.out -no-color
  )
  echo "::endgroup::"
  render_plan_json_if_present "IaC/homelab/us-west-2/operator/application-backup-storage"
fi

echo "IaC/homelab/us-west-2/shared/aws-ssm-parameters is intentionally excluded from PR plans because it manages KMS, IAM, and secret declarations that require the protected production apply role."
echo "IaC/homelab/us-west-2/apps/langfuse/blob-storage is also excluded: its state includes the runtime S3 key. The protected full or targeted Langfuse apply plans and policy-checks it before application registration."

echo "::group::Argo CD Application registration plan"
(
  cd IaC/homelab/us-west-2/apps
  if ((${#argocd_plan_filters[@]} > 0)); then
    # Each provider fetches Kubernetes OpenAPI independently. Bound concurrent
    # discovery through the CI API proxy; all selected units still get planned.
    terragrunt run --all "${argocd_plan_filters[@]}" --parallelism 2 -- plan -lock=false -out plan.out -no-color
  fi
)
echo "::endgroup::"

while IFS= read -r unit_file; do
  unit_dir="$(dirname "$unit_file")"
  if terragrunt_active_unit_affected "$unit_dir" "$affected_units"; then
    render_plan_json_if_present "$unit_dir" >/dev/null
  fi
done < <(find IaC/homelab/us-west-2/apps -mindepth 3 -maxdepth 3 -name terragrunt.hcl -path '*/argocd/terragrunt.hcl' -print | sort)

deleted_plan_units=()
if ! deleted_plan_paths="$(terragrunt_deleted_unit_paths)"; then
  echo "Unable to determine deleted Terragrunt units; refusing to continue planning." >&2
  exit 1
fi
while IFS= read -r deleted_unit_dir; do
  [[ -n "$deleted_unit_dir" ]] && deleted_plan_units+=("$deleted_unit_dir")
done <<<"$deleted_plan_paths"

plan_deleted_terragrunt_units "${deleted_plan_units[@]}"

echo "::group::AzureAD application registration plan"
if azuread_credentials_available; then
  if [[ -n "${HOMELAB_AZUREAD_PLAN_REPORT_FILE:-}" ]]; then
    azuread_report_args=(
      --report-file "$HOMELAB_AZUREAD_PLAN_REPORT_FILE"
      --report-format json
    )
  fi
  (
    cd IaC/homelab/us-west-2/apps
    if ((${#azuread_plan_filters[@]} > 0)); then
      terragrunt run --all "${azuread_plan_filters[@]}" --parallelism 4 "${azuread_report_args[@]}" -- plan -lock=false -out plan.out -no-color
    fi
  )

  while IFS= read -r unit_file; do
    unit_dir="$(dirname "$unit_file")"
    if terragrunt_active_unit_affected "$unit_dir" "$affected_units"; then
      render_plan_json_if_present "$unit_dir" >/dev/null
    fi
  done < <(find IaC/homelab/us-west-2/apps -mindepth 3 -maxdepth 3 -name terragrunt.hcl \( -path '*/azuread/terragrunt.hcl' -o -path '*/pilot-user/terragrunt.hcl' \) -print | sort)
else
  if ((${#azuread_plan_filters[@]} > 0)); then
    echo "AzureAD credentials are required for affected AzureAD units." >&2
    exit 1
  fi
  echo "::warning::Skipping AzureAD application registration plan because client/tenant IDs and a complete GitHub OIDC session (or explicit client-secret authentication) are not configured for this plan run."
fi
echo "::endgroup::"

validate_terraform_plan_policies

echo "IaC/homelab/us-west-2/shared/kubernetes-secrets is intentionally excluded from PR plans because it reads decrypted SSM parameters."
