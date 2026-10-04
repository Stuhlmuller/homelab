#!/usr/bin/env bash
# Fixed retirement of the staged, never-activated SIEM. Output stays private in CI.
set -euo pipefail
umask 077

root="$(git rev-parse --show-toplevel)"
cd "$root"
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REF:-}" == refs/heads/main ]]
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
[[ "${TERRAGRUNT_RETIRE_WAZUH:-}" == true && "${TERRAGRUNT_ARGOCD_APP:-}" == wazuh ]]
[[ "${TERRAGRUNT_REPAIR_ARGOCD_APP_STATE:-false}" == false ]]
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]
[[ "$(git ls-remote https://github.com/Stuhlmuller/homelab.git refs/heads/main | cut -f1)" == "$GITHUB_SHA" ]]

require_absent() {
  local found
  found="$(kubectl --request-timeout=30s "$@" --ignore-not-found -o name)"
  [[ -z "$found" ]]
}

check_inactive() {
  local app
  require_absent get namespace wazuh
  require_absent get pv wazuh-indexer-local wazuh-manager-local
  require_absent get storageclass wazuh-local
  require_absent get clusterrole wazuh-collector
  require_absent get clusterrolebinding wazuh-collector
  app="$(kubectl --request-timeout=30s -n argocd get application wazuh --ignore-not-found -o json)"
  if [[ -n "$app" ]]; then
    jq -e '
      .metadata.name == "wazuh" and .metadata.namespace == "argocd" and
      .spec.destination.namespace == "wazuh" and
      .spec.syncPolicy.automated.enabled == false and
      (.operation // null) == null and (.metadata.finalizers // []) == []
    ' <<<"$app" >/dev/null
  fi
}

check_inactive
plan_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/wazuh-retire.XXXXXX")"
trap 'rm -rf "$plan_dir"' EXIT
printf '%s\n' '{"wazuh_retirement":true}' >"$plan_dir/retirement-policy.json"

prepare_plan() {
  local kind="$1" unit="$2"
  (
    cd "$root/$unit"
    terragrunt init -no-color
    terragrunt plan -out "$plan_dir/$kind.plan" -no-color
    terragrunt --log-disable show -json "$plan_dir/$kind.plan" >"$plan_dir/$kind.json"
  )
  python3 -I "$root/scripts/ci/wazuh-retire-plan.py" "$kind" "$plan_dir/$kind.json"
  conftest test --policy "$root/policy" --data "$plan_dir/retirement-policy.json" \
    --output github "$plan_dir/$kind.json"
}

# Validate both plans before either write. A shared-unit drift fails closed.
prepare_plan app IaC/live/argocd-apps/wazuh
prepare_plan ssm IaC/live/aws-ssm-parameters
check_inactive
[[ "$(git ls-remote https://github.com/Stuhlmuller/homelab.git refs/heads/main | cut -f1)" == "$GITHUB_SHA" ]]
(
  cd IaC/live/argocd-apps/wazuh
  terragrunt apply -no-color "$plan_dir/app.plan"
  terragrunt --log-disable state list >"$plan_dir/app-state.txt"
)
[[ ! -s "$plan_dir/app-state.txt" ]]
require_absent -n argocd get application wazuh
(
  cd IaC/live/aws-ssm-parameters
  terragrunt apply -no-color "$plan_dir/ssm.plan"
)
aws ssm describe-parameters --region us-west-2 \
  --parameter-filters Key=Path,Option=Recursive,Values=/homelab/wazuh/ \
  --query 'Parameters[].Name' --output json | jq -e 'length == 0' >/dev/null
check_inactive
echo "Verified Wazuh Application, runtime resources and unused credentials are absent."
