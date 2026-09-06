#!/usr/bin/env bash

terragrunt_filter_head_ref() {
  local head_ref="${TERRAGRUNT_FILTER_HEAD_SHA:-${APPLY_HEAD_SHA:-${GITHUB_SHA:-HEAD}}}"

  if ! git rev-parse --verify --quiet "${head_ref}^{commit}" >/dev/null; then
    head_ref="HEAD"
  fi

  printf '%s\n' "$head_ref"
}

terragrunt_generate_stack() {
  (
    cd IaC || exit
    terragrunt stack generate
  )
}

terragrunt_stack_units_at_ref() {
  local ref="$1"
  local path_prefix="${2:-}"

  if ! git cat-file -e "${ref}:IaC/terragrunt.stack.hcl" 2>/dev/null; then
    return 0
  fi

  git show "${ref}:IaC/terragrunt.stack.hcl" | awk -v prefix="$path_prefix" '
    function emit_unit() {
      if (prefix == "" || index(unit_path, prefix) == 1) {
        printf "%s", unit_block
      }
    }

    !in_unit && /^unit "[^"]+"[[:space:]]*\{/ {
      in_unit = 1
      depth = 0
      unit_block = ""
      unit_path = ""
    }

    in_unit {
      unit_block = unit_block $0 ORS

      brace_line = $0
      open_braces = gsub(/\{/, "", brace_line)
      brace_line = $0
      close_braces = gsub(/\}/, "", brace_line)
      depth += open_braces - close_braces

      if ($0 ~ /^  path[[:space:]]*=/) {
        unit_path = $0
        sub(/^[[:space:]]*path[[:space:]]*=[[:space:]]*"/, "", unit_path)
        sub(/".*$/, "", unit_path)
      }

      if (depth == 0) {
        emit_unit()
        in_unit = 0
      }
    }
  '
}

terragrunt_stack_unit_paths_at_ref() {
  terragrunt_stack_units_at_ref "$1" | sed -n 's#^  path[[:space:]]*=[[:space:]]*"\([^"]*\)".*$#IaC/\1#p'
}

terragrunt_normalized_root_source_at_ref() {
  local ref="$1"
  local root_source
  local legacy_plan_block=$'terraform {\n  extra_arguments "plan" {\n    commands  = ["plan"]\n    arguments = ["-out", "plan.out"]\n  }\n}\n\n'

  root_source="$(git show "${ref}:IaC/root.hcl")" || return 1
  printf '%s\n' "${root_source/"$legacy_plan_block"/}"
}

terragrunt_azuread_stack_changed() {
  local base_sha="${APPLY_BASE_SHA:-}"
  local head_sha="${APPLY_HEAD_SHA:-${GITHUB_SHA:-HEAD}}"
  local base_root_source
  local head_root_source
  local base_stack_units
  local head_stack_units

  if [[ -z "$base_sha" || "$base_sha" =~ ^0+$ ]]; then
    return 0
  fi

  if ! git cat-file -e "${base_sha}^{commit}" 2>/dev/null; then
    return 0
  fi

  if ! git cat-file -e "${head_sha}^{commit}" 2>/dev/null; then
    return 0
  fi

  if ! git diff --quiet "$base_sha" "$head_sha" -- \
    IaC/live/azuread-applications \
    IaC/.catalog/units/live/azuread-applications; then
    return 0
  fi

  if ! base_stack_units="$(terragrunt_stack_units_at_ref "$base_sha" 'live/azuread-applications/')" ||
    ! head_stack_units="$(terragrunt_stack_units_at_ref "$head_sha" 'live/azuread-applications/')"; then
    return 0
  fi

  if [[ "$base_stack_units" != "$head_stack_units" ]]; then
    return 0
  fi

  if ! base_root_source="$(terragrunt_normalized_root_source_at_ref "$base_sha")" ||
    ! head_root_source="$(terragrunt_normalized_root_source_at_ref "$head_sha")"; then
    return 0
  fi

  [[ "$base_root_source" != "$head_root_source" ]]
}

terragrunt_stack_changed() {
  local base_ref="${TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF:-}"
  local generated_group="${1:-}"
  local include_plan_inputs="${2:-false}"
  local head_ref="${TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF:-}"
  local repo_root
  local paths=(
    IaC/terragrunt.stack.hcl
    IaC/.catalog
    IaC/modules
    IaC/root.hcl
    IaC/kubernetes-provider.hcl
  )

  if [[ "$include_plan_inputs" == "true" ]]; then
    paths+=(
      flake.nix
      flake.lock
      policy/terraform.rego
      scripts/ci/terragrunt-filter-base.sh
      scripts/ci/terragrunt-plan.sh
      scripts/ci/terragrunt-apply.sh
    )
  fi

  if [[ -n "$generated_group" ]]; then
    paths+=("$generated_group")
  fi

  if ! repo_root="$(git rev-parse --show-toplevel)"; then
    return 0
  fi

  if [[ -z "$base_ref" ]] && ! base_ref="$(terragrunt_filter_base_ref)"; then
    return 0
  fi

  if [[ -z "$head_ref" ]]; then
    head_ref="$(terragrunt_filter_head_ref)"
  fi

  if ! git rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null; then
    return 0
  fi

  if ! git rev-parse --verify --quiet "${head_ref}^{commit}" >/dev/null; then
    return 0
  fi

  ! git -C "$repo_root" diff --quiet "$base_ref" "$head_ref" -- "${paths[@]}"
}

terragrunt_changed_filter() {
  local all_filter="$1"
  local include_plan_inputs="${2:-false}"
  local generated_group="${all_filter%/*}"

  if terragrunt_stack_changed "$generated_group" "$include_plan_inputs"; then
    printf '*\n'
  else
    printf '%s | [main...HEAD]\n' "$all_filter"
  fi
}

terragrunt_argocd_app_filter() {
  local unit="${TERRAGRUNT_ARGOCD_APP:-}"

  if [[ -z "$unit" ]]; then
    terragrunt_changed_filter 'IaC/live/argocd-apps/*'
    return
  fi

  if [[ ! "$unit" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ || ! -f "${unit}/terragrunt.hcl" ]]; then
    echo "Unknown Argo CD Application unit: ${unit}" >&2
    return 1
  fi

  printf '%s\n' "$unit"
}

terragrunt_argocd_app_state_repair_unit() {
  case "${TERRAGRUNT_REPAIR_ARGOCD_APP_STATE:-false}" in
    false | "") return 0 ;;
    true)
      if [[ "${GITHUB_EVENT_NAME:-}" != "workflow_dispatch" ]]; then
        echo "Argo CD Application state repair is allowed only through a protected manual dispatch." >&2
        return 1
      fi
      if [[ -z "${TERRAGRUNT_ARGOCD_APP:-}" ]]; then
        echo "Argo CD Application state repair requires one exact argocd_app." >&2
        return 1
      fi
      terragrunt_argocd_app_filter
      ;;
    *)
      echo "TERRAGRUNT_REPAIR_ARGOCD_APP_STATE must be true or false." >&2
      return 1
      ;;
  esac
}

terragrunt_filter_base_ref() {
  local base_ref="${TERRAGRUNT_FILTER_BASE_SHA:-${APPLY_BASE_SHA:-}}"

  if [[ -z "$base_ref" && -n "${GITHUB_BASE_REF:-}" ]]; then
    base_ref="origin/${GITHUB_BASE_REF}"
  fi

  if [[ -z "$base_ref" && "${GITHUB_EVENT_NAME:-}" == "workflow_dispatch" ]]; then
    base_ref="HEAD^"
  fi

  if [[ -z "$base_ref" ]]; then
    if git rev-parse --verify --quiet "main^{commit}" >/dev/null; then
      base_ref="main"
    else
      base_ref="origin/main"
    fi
  fi

  if [[ -z "$base_ref" || "$base_ref" =~ ^0+$ ]]; then
    return 1
  fi

  printf '%s\n' "$base_ref"
}

prepare_terragrunt_filter_base() {
  local base_ref
  local head_ref

  if ! base_ref="$(terragrunt_filter_base_ref)"; then
    echo "No usable Terragrunt --filter-affected base ref is available; refusing to skip deleted-unit detection." >&2
    return 1
  fi

  head_ref="$(terragrunt_filter_head_ref)"

  if ! git rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null; then
    echo "Terragrunt --filter-affected base ${base_ref} is unavailable; refusing to skip deleted-unit detection." >&2
    return 1
  fi

  if ! git rev-parse --verify --quiet "${head_ref}^{commit}" >/dev/null; then
    echo "Terragrunt --filter-affected head ${head_ref} is unavailable." >&2
    return 1
  fi

  export TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF="$base_ref"
  export TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF="$head_ref"

  if [[ "${CI:-}" != "true" ]]; then
    return 0
  fi

  git switch --detach --quiet "$head_ref"

  git branch --force main "$base_ref"
}

terragrunt_deleted_unit_paths() {
  local base_ref="${TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF:-}"
  local head_ref="${TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF:-}"
  local head_stack_unit_paths

  if [[ -z "$base_ref" ]] && ! base_ref="$(terragrunt_filter_base_ref)"; then
    return 0
  fi

  if [[ -z "$head_ref" ]]; then
    head_ref="$(terragrunt_filter_head_ref)"
  fi

  if ! git rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null; then
    echo "::warning::Terragrunt deleted-unit base ${base_ref} is unavailable; skipping deleted-unit destroy detection."
    return 0
  fi

  if ! git rev-parse --verify --quiet "${head_ref}^{commit}" >/dev/null; then
    echo "::warning::Terragrunt deleted-unit head ${head_ref} is unavailable; skipping deleted-unit destroy detection."
    return 0
  fi

  head_stack_unit_paths="$(terragrunt_stack_unit_paths_at_ref "$head_ref")"

  while IFS= read -r unit_dir; do
    # Catalog templates and operator-owned state are outside the CI apply scope.
    case "$unit_dir" in
      IaC/bootstrap/*|IaC/live/*) ;;
      *) continue ;;
    esac
    if grep -Fxq "$unit_dir" <<<"$head_stack_unit_paths"; then
      continue
    fi
    printf '%s\n' "$unit_dir"
  done < <(
    {
      git diff --name-only --diff-filter=D "$base_ref" "$head_ref" -- 'IaC/**/terragrunt.hcl' \
        | sed 's#/terragrunt\.hcl$##'
      comm -23 \
        <(terragrunt_stack_unit_paths_at_ref "$base_ref" | sort) \
        <(printf '%s\n' "$head_stack_unit_paths" | sed '/^$/d' | sort)
    } | sort -u
  )
}

terragrunt_create_deleted_unit_destroy_stack() {
  local destination="$1"
  local unit_dir="$2"
  local head_ref="${3:-${TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF:-}}"
  local fake_unit_dir

  if [[ -z "$head_ref" ]]; then
    head_ref="$(terragrunt_filter_head_ref)"
  fi

  if ! git rev-parse --verify --quiet "${head_ref}^{commit}" >/dev/null; then
    echo "No usable Terragrunt head ref is available for deleted-unit destroy handling." >&2
    return 1
  fi

  mkdir -p "$destination"
  git archive "$head_ref" | tar -x -C "$destination"

  fake_unit_dir="${destination}/${unit_dir}"
  mkdir -p "$fake_unit_dir"

  cat >"${fake_unit_dir}/terragrunt.hcl" <<'EOF'
include "root" {
  path = find_in_parent_folders("root.hcl")
}

include "kubernetes_provider" {
  path = find_in_parent_folders("kubernetes-provider.hcl")
}

locals {
  root_config = read_terragrunt_config(find_in_parent_folders("root.hcl"))
  aws_region  = local.root_config.locals.aws_region
}

generate "deleted_unit_destroy_config" {
  path      = "deleted-unit-destroy.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<TF
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
    azuread = {
      source = "hashicorp/azuread"
    }
    helm = {
      source = "hashicorp/helm"
    }
    kubernetes = {
      source = "hashicorp/kubernetes"
    }
    random = {
      source = "hashicorp/random"
    }
  }
}

provider "aws" {
  region = "${local.aws_region}"
}

provider "azuread" {}
provider "random" {}

provider "helm" {
  kubernetes = {
    config_path = pathexpand("${local.root_config.locals.kubernetes_config_path}")
  }
}
TF
}
EOF
}
