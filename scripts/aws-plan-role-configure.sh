#!/usr/bin/env bash
set -euo pipefail

execute=false
case "${1:-}" in
  "") ;;
  --execute) execute=true ;;
  *) echo "Usage: scripts/aws-plan-role-configure.sh [--execute]" >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || { echo "Usage: scripts/aws-plan-role-configure.sh [--execute]" >&2; exit 2; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

terragrunt --working-dir IaC stack generate >/dev/null
role_arn="$(terragrunt --working-dir IaC/operator/github-actions-role-policy output -raw plan_role_arn)"
if [[ ! "$role_arn" =~ ^arn:aws:iam::[0-9]{12}:role/Github-TF-Plan$ ]]; then
  echo "error: operator state did not return the dedicated Github-TF-Plan role ARN" >&2
  exit 1
fi

if [[ "$execute" == "false" ]]; then
  echo "Would publish the operator-managed plan role ARN to Stuhlmuller/homelab homelab-plan."
  exit 0
fi

gh auth status >/dev/null
gh variable set AWS_PLAN_ROLE_TO_ASSUME_HOMELAB \
  --repo Stuhlmuller/homelab --env homelab-plan --body "$role_arn"
published_arn="$(gh variable get AWS_PLAN_ROLE_TO_ASSUME_HOMELAB \
  --repo Stuhlmuller/homelab --env homelab-plan --json value --jq .value)"
if [[ "$published_arn" != "$role_arn" ]]; then
  echo "error: GitHub plan role variable did not match operator state" >&2
  exit 1
fi
echo "Published and verified the dedicated homelab-plan AWS role."
