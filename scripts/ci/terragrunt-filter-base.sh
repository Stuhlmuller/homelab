#!/usr/bin/env bash

prepare_terragrunt_filter_base() {
  if [[ "${CI:-}" != "true" ]]; then
    return 0
  fi

  local base_ref="${TERRAGRUNT_FILTER_BASE_SHA:-${APPLY_BASE_SHA:-}}"
  local head_ref="${TERRAGRUNT_FILTER_HEAD_SHA:-${APPLY_HEAD_SHA:-${GITHUB_SHA:-HEAD}}}"

  if [[ -z "$base_ref" && -n "${GITHUB_BASE_REF:-}" ]]; then
    base_ref="origin/${GITHUB_BASE_REF}"
  fi

  if [[ -z "$base_ref" && "${GITHUB_EVENT_NAME:-}" == "workflow_dispatch" ]]; then
    base_ref="HEAD^"
  fi

  if [[ -z "$base_ref" ]]; then
    base_ref="origin/main"
  fi

  if [[ -z "$base_ref" || "$base_ref" =~ ^0+$ ]]; then
    echo "::warning::No usable Terragrunt --filter-affected base ref was available; using the existing main ref."
    return 0
  fi

  if ! git rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null; then
    echo "::warning::Terragrunt --filter-affected base ${base_ref} is unavailable; using the existing main ref."
    return 0
  fi

  if git rev-parse --verify --quiet "${head_ref}^{commit}" >/dev/null; then
    git switch --detach --quiet "$head_ref"
  fi

  git branch --force main "$base_ref"
}
