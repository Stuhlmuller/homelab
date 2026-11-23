#!/usr/bin/env bash

terragrunt_filter_head_ref() {
  printf '%s\n' "${TERRAGRUNT_FILTER_HEAD_SHA:-${APPLY_HEAD_SHA:-${GITHUB_SHA:-HEAD}}}"
}

terragrunt_generate_stack() {
  (
    cd IaC || exit
    terragrunt stack generate
  )
}

# Keep unit identity literal in the stack. Locals may compose values, while
# ownership and retirement checks read unit blocks without evaluating providers.
terragrunt_stack_units() {
  local path_prefix="${1:-}"

  awk -v prefix="$path_prefix" '
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

terragrunt_stack_units_at_ref() {
  local ref="$1"
  local path_prefix="${2:-}"
  local source

  if ! git cat-file -e "${ref}:IaC/terragrunt.stack.hcl" 2>/dev/null; then
    return 0
  fi

  source="$(git show "${ref}:IaC/terragrunt.stack.hcl")" || return 1
  terragrunt_stack_units "$path_prefix" <<<"$source"
}

terragrunt_stack_unit_paths() {
  terragrunt_stack_units | sed -n 's#^  path[[:space:]]*=[[:space:]]*"\([^"]*\)".*$#IaC/\1#p'
}

terragrunt_stack_unit_paths_at_ref() {
  local ref="$1"
  local stack_file
  local unit_path
  local app
  local stack_files
  local source
  local unit_paths
  local repo_root
  local paths=()

  repo_root="$(git rev-parse --show-toplevel)" || return 1
  if git cat-file -e "${ref}:IaC/terragrunt.stack.hcl" 2>/dev/null; then
    source="$(terragrunt_stack_units_at_ref "$ref")" || return 1
    sed -n 's#^  path[[:space:]]*=[[:space:]]*"\([^"]*\)".*$#IaC/\1#p' <<<"$source"
    return
  fi

  stack_files="$(git -C "$repo_root" ls-tree -r --name-only "$ref" -- IaC/homelab/us-west-2)" || return 1
  stack_files="$(sed -n '\#/terragrunt.stack.hcl$#p' <<<"$stack_files")"
  if [[ -z "$stack_files" ]]; then
    echo "No Terragrunt stacks found at ${ref}; refusing deleted-unit detection." >&2
    return 1
  fi

  while IFS= read -r stack_file; do
    source="$(git show "${ref}:${stack_file}")" || return 1
    unit_paths="$(sed -n 's#^  path[[:space:]]*=[[:space:]]*"\([^"]*\)".*$#\1#p' <<<"$source")"
    while IFS= read -r unit_path; do
      [[ -n "$unit_path" ]] || continue
      case "$stack_file:$unit_path" in
        */apps/*/terragrunt.stack.hcl:argocd)
          app="${stack_file#IaC/homelab/us-west-2/apps/}"
          paths+=("IaC/live/argocd-apps/${app%/terragrunt.stack.hcl}")
          ;;
        */apps/*/terragrunt.stack.hcl:azuread)
          app="${stack_file#IaC/homelab/us-west-2/apps/}"
          paths+=("IaC/live/azuread-applications/${app%/terragrunt.stack.hcl}")
          ;;
        */apps/fleet/terragrunt.stack.hcl:pilot-user) paths+=("IaC/live/azuread-applications/fleet-pilot-user") ;;
        */apps/langfuse/terragrunt.stack.hcl:blob-storage) paths+=("IaC/live/langfuse-blob-storage") ;;
        */shared/terragrunt.stack.hcl:*) paths+=("IaC/live/$unit_path") ;;
        */bootstrap/terragrunt.stack.hcl:*) paths+=("IaC/bootstrap/$unit_path") ;;
        */operator/terragrunt.stack.hcl:*) paths+=("IaC/operator/$unit_path") ;;
        *) echo "Unknown Terragrunt unit in ${stack_file}: ${unit_path}" >&2; return 1 ;;
      esac
    done <<<"$unit_paths"
  done <<<"$stack_files"
  if ((${#paths[@]} > 0)); then
    printf '%s\n' "${paths[@]}"
  fi
}

# Run Git discovery once. Exact paths from its output can be replayed in the
# current checkout for saved plans, or excluded from a scoped retirement run.
terragrunt_affected_units() {
  local default_branch
  default_branch="$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null)" || default_branch=""
  if [[ -n "$default_branch" && "$default_branch" != "origin/main" ]]; then
    echo "Terragrunt --filter-affected requires the repository default branch to be main." >&2
    return 1
  fi
  if [[ "$(git rev-parse --verify --quiet main)" != "$TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF" ||
    "$(git rev-parse --verify --quiet HEAD)" != "$TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF" ]]; then
    echo "Terragrunt --filter-affected requires local main and HEAD to match the comparison commits." >&2
    return 1
  fi
  python3 -I "$(dirname "${BASH_SOURCE[0]}")/terragrunt-affected-units.py"
}

terragrunt_unit_affected() {
  grep -Fxq "$1" <<<"$2"
}

terragrunt_active_unit_affected() {
  [[ -f "$1/terragrunt.hcl" ]] && terragrunt_unit_affected "$1" "$2"
}

terragrunt_argocd_app_filter() {
  local unit="${TERRAGRUNT_ARGOCD_APP:-}"

  if [[ ! "$unit" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ || ! -f "${unit}/argocd/terragrunt.hcl" ]]; then
    echo "Unknown Argo CD Application unit: ${unit}" >&2
    return 1
  fi

  printf '%s/argocd\n' "$unit"
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
    # A queued PR merge may predate new units on main; those are not PR retirements.
    if [[ "${GITHUB_EVENT_NAME:-}" == "pull_request" ]] &&
      ! base_ref="$(git merge-base "$base_ref" "$(terragrunt_filter_head_ref)")"; then
      echo "No common ancestor is available for the Terragrunt PR comparison; refusing deleted-unit detection." >&2
      return 1
    fi
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
  local base_ref base_sha
  local head_ref head_sha

  if ! base_ref="$(terragrunt_filter_base_ref)"; then
    echo "No usable Terragrunt --filter-affected base ref is available; refusing to skip deleted-unit detection." >&2
    return 1
  fi

  head_ref="$(terragrunt_filter_head_ref)"

  if ! base_sha="$(git rev-parse --verify --quiet "${base_ref}^{commit}")"; then
    echo "Terragrunt --filter-affected base ${base_ref} is unavailable; refusing to skip deleted-unit detection." >&2
    return 1
  fi

  if ! head_sha="$(git rev-parse --verify --quiet "${head_ref}^{commit}")"; then
    echo "Terragrunt --filter-affected head ${head_ref} is unavailable." >&2
    return 1
  fi

  export TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF="$base_sha"
  export TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF="$head_sha"

  if [[ "${CI:-}" != "true" ]]; then
    return 0
  fi

  git switch --detach --quiet "$head_sha" || return 1
  git branch --force main "$base_sha" || return 1
  # Terragrunt 1.2 selects the default branch through origin/HEAD when present.
  if git show-ref --verify --quiet refs/remotes/origin/main; then
    git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
  else
    return 0
  fi
}

terragrunt_deleted_unit_paths() {
  local base_ref="${TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF:-}"
  local head_ref="${TERRAGRUNT_EFFECTIVE_FILTER_HEAD_REF:-}"
  local head_stack_unit_paths
  local base_stack_unit_paths
  local deleted_files
  local candidates
  local unit_dir
  local repo_root
  local deleted_paths=()

  repo_root="$(git rev-parse --show-toplevel)" || return 1
  if [[ -z "$base_ref" ]] && ! base_ref="$(terragrunt_filter_base_ref)"; then
    echo "Unable to determine deleted-unit base; refusing reconciliation." >&2
    return 1
  fi

  if [[ -z "$head_ref" ]]; then
    head_ref="$(terragrunt_filter_head_ref)" || return 1
  fi

  if ! git rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null ||
    ! git rev-parse --verify --quiet "${head_ref}^{commit}" >/dev/null; then
    echo "Deleted-unit comparison revision is unavailable; refusing reconciliation." >&2
    return 1
  fi

  # Capture all fallible Git reads before emitting any deletion candidate.
  head_stack_unit_paths="$(terragrunt_stack_unit_paths_at_ref "$head_ref")" || return 1
  base_stack_unit_paths="$(terragrunt_stack_unit_paths_at_ref "$base_ref")" || return 1
  deleted_files="$(git -C "$repo_root" diff --name-only --diff-filter=D "$base_ref" "$head_ref" -- 'IaC/**/terragrunt.hcl')" || return 1
  while IFS= read -r unit_dir; do
    [[ -n "$unit_dir" ]] || continue
    deleted_paths+=("${unit_dir%/terragrunt.hcl}")
  done <<<"$deleted_files"
  candidates="$(printf '%s\n' "$base_stack_unit_paths" "${deleted_paths[@]}" | sort -u)" || return 1

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
  done <<<"$candidates"
}

terragrunt_retired_argocd_app_path() {
  local app="$1"
  local deleted_units="$2"
  local unit="IaC/live/argocd-apps/$app"

  if [[ ! "$app" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] ||
     ! grep -Fxq "$unit" <<<"$deleted_units"; then
    echo "Unknown deleted Argo CD Application unit: ${app}" >&2
    return 1
  fi
  printf '%s\n' "$unit"
}

terragrunt_kiali_teardown_complete() {
  local remaining
  if ! remaining="$(kubectl --request-timeout=15s -n monitoring get \
    kialis.kiali.io/kiali deployment.apps/kiali service/kiali --ignore-not-found -o name)"; then
    echo "Unable to verify Kiali teardown before retiring the operator." >&2
    return 1
  fi
  if [[ -n "$remaining" ]]; then
    echo "Kiali retirement requires completed server teardown; Kiali resources still exist." >&2
    return 1
  fi
}

terragrunt_retired_argocd_app_plan() {
  local app="$1"
  local live_app="$2"
  local plan="$3"

  jq -e --arg app "$app" --argjson live "$live_app" '
    def identity:
      .apiVersion == "argoproj.io/v1alpha1" and .kind == "Application" and
      .metadata.namespace == "argocd" and .metadata.name == $app;
    def cascading:
      identity and ((.metadata.finalizers // []) | index("resources-finalizer.argocd.argoproj.io") != null);

    .resource_changes // [] |
    if length == 0 then
      $live == null
    else
      length == 1 and
      (.[0] |
        .address == "kubernetes_manifest.this" and .mode == "managed" and
        .type == "kubernetes_manifest" and .change.actions == ["delete"] and
        (.change.before.manifest | identity) and (.change.before.object | identity)) and
      ($live == null or ($live | cascading))
    end
  ' "$plan" >/dev/null
}

# Resolve a stable backend identity to the configuration path at the base.
terragrunt_deleted_unit_source() {
  local unit_dir="$1"
  local base_sha="$TERRAGRUNT_EFFECTIVE_FILTER_BASE_REF"
  local source_dir

  source_dir="$unit_dir"
  if ! git cat-file -e "${base_sha}:${unit_dir}/terragrunt.hcl" 2>/dev/null &&
     ! git cat-file -e "${base_sha}:IaC/terragrunt.stack.hcl" 2>/dev/null; then
    case "$unit_dir" in
      IaC/live/argocd-apps/*) source_dir="IaC/homelab/us-west-2/apps/${unit_dir##*/}/argocd" ;;
      IaC/live/azuread-applications/fleet-pilot-user) source_dir="IaC/homelab/us-west-2/apps/fleet/pilot-user" ;;
      IaC/live/azuread-applications/*) source_dir="IaC/homelab/us-west-2/apps/${unit_dir##*/}/azuread" ;;
      IaC/live/langfuse-blob-storage) source_dir="IaC/homelab/us-west-2/apps/langfuse/blob-storage" ;;
      IaC/live/*) source_dir="IaC/homelab/us-west-2/shared/${unit_dir#IaC/live/}" ;;
      IaC/bootstrap/*) source_dir="IaC/homelab/us-west-2/bootstrap/${unit_dir#IaC/bootstrap/}" ;;
    esac
  fi
  printf '%s\n' "$source_dir"
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
  git -C "$destination" init -q

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
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.56.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "3.9.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "3.2.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "3.2.1"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.0"
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
