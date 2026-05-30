#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

plan_markdown="${TERRAGRUNT_PLAN_MARKDOWN:-${RUNNER_TEMP:-/tmp}/terragrunt-plan.md}"
mkdir -p "$(dirname "$plan_markdown")"

clear_plan_outs() {
  find "$@" -name plan.out -type f -delete
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

append_plan_note() {
  local message="$1"

  {
    printf '> %s\n\n' "$message"
  } >>"$plan_markdown"
}

prepare_terragrunt_filter_base
clear_plan_outs IaC/bootstrap IaC/live/argocd-apps

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
  terragrunt run --all --filter-affected --parallelism 1 -- plan -lock=false -no-color
)
echo "::endgroup::"
if ! render_plan_out_if_present "Argo CD bootstrap" "IaC/bootstrap/argocd"; then
  append_plan_note "No affected Argo CD bootstrap units were planned."
fi

echo "IaC/live/aws-ssm-parameters is intentionally excluded from PR plans because it manages KMS, IAM, and secret declarations that require the protected production apply role."

echo "::group::Argo CD Application registration plan"
(
  cd IaC/live/argocd-apps
  terragrunt run --all --filter-affected --parallelism 1 --source-update -- plan -lock=false -no-color
)
echo "::endgroup::"

planned_app_count=0
while IFS= read -r unit_file; do
  unit_dir="$(dirname "$unit_file")"
  unit_name="$(basename "$unit_dir")"
  if render_plan_out_if_present "Argo CD Application: ${unit_name}" "$unit_dir"; then
    planned_app_count=$((planned_app_count + 1))
  fi
done < <(find IaC/live/argocd-apps -mindepth 2 -maxdepth 2 -name terragrunt.hcl -print | sort)

if [[ "$planned_app_count" -eq 0 ]]; then
  append_plan_note "No affected Argo CD Application registration units were planned."
fi

echo "IaC/live/kubernetes-secrets is intentionally excluded from PR plans because it reads decrypted SSM parameters."
