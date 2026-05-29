#!/usr/bin/env bash
set -euo pipefail

plan_markdown="${TERRAGRUNT_PLAN_MARKDOWN:-${RUNNER_TEMP:-/tmp}/terragrunt-plan.md}"
mkdir -p "$(dirname "$plan_markdown")"

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
  cd IaC/bootstrap/argocd
  terragrunt --log-disable plan -lock=false -no-color
)
echo "::endgroup::"
render_plan_out "Argo CD bootstrap" "IaC/bootstrap/argocd"

echo "IaC/live/aws-ssm-parameters is intentionally excluded from PR plans because it manages KMS, IAM, and secret declarations that require the protected production apply role."

echo "::group::Argo CD Application registration plan"
(
  cd IaC/live/argocd-apps
  terragrunt run --all --parallelism 1 --source-update plan -lock=false -no-color
)
echo "::endgroup::"

while IFS= read -r unit_file; do
  unit_dir="$(dirname "$unit_file")"
  unit_name="$(basename "$unit_dir")"
  render_plan_out "Argo CD Application: ${unit_name}" "$unit_dir"
done < <(find IaC/live/argocd-apps -mindepth 2 -maxdepth 2 -name terragrunt.hcl -print | sort)

echo "IaC/live/kubernetes-secrets is intentionally excluded from PR plans because it reads decrypted SSM parameters."
