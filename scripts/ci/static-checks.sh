#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/terragrunt-filter-base.sh"

terragrunt_generate_stack

echo "::group::Terragrunt HCL"
terragrunt hcl fmt --check
terragrunt hcl validate
expected_units="$(rg -c '^unit "' IaC/terragrunt.stack.hcl)"
parsed_units="$(terragrunt_stack_unit_paths_at_ref HEAD | wc -l | tr -d ' ')"
if [[ "$parsed_units" -ne "$expected_units" ]]; then
  echo "Parsed ${parsed_units} of ${expected_units} explicit stack units" >&2
  exit 1
fi
echo "::endgroup::"

echo "::group::Terragrunt generated-unit filters"
(
  terragrunt_stack_changed() { return 0; }
  [[ "$(terragrunt_changed_filter 'IaC/live/argocd-apps/*')" == "*" ]]
  terragrunt_stack_changed() { return 1; }
  [[ "$(terragrunt_changed_filter 'IaC/live/argocd-apps/*')" == "IaC/live/argocd-apps/* | [main...HEAD]" ]]
)
echo "::endgroup::"

echo "::group::Operator OpenTofu validation"
(
  cd IaC/operator/github-actions-role-policy
  terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
  terragrunt --log-disable validate -no-color
)
echo "::endgroup::"

echo "::group::Kustomize overlays"
while IFS= read -r overlay; do
  echo "rendering ${overlay}"
  kubectl kustomize "$overlay" >/dev/null
done < <(
  find clusters/homelab/argocd clusters/homelab/apps clusters/homelab/platform \
    -name kustomization.yaml \
    -exec dirname {} \; | sort
)
echo "::endgroup::"

echo "::group::Octelium CI credential lifetime and scope"
yq ea -o=json -I=0 '[.]' docs/examples/octelium/homelab-services.yaml |
  jq -e '
    [.[] | select(.kind == "User" and .metadata.name == "homelab-ci")] as $users |
    [.[] | select(.kind == "Policy" and .metadata.name == "homelab-ci-kubernetes-api-access")] as $policies |
    ($users | length) == 1 and
    $users[0].spec.type == "WORKLOAD" and
    $users[0].spec.session.clientlessDuration == {"days": 30} and
    $users[0].spec.session.accessTokenDuration == {"days": 30} and
    ($policies | length) == 1 and
    $policies[0].spec.rules == [{
      "name": "kubernetes-api-service",
      "effect": "ALLOW",
      "condition": {"all": {"of": [
        {"match": "ctx.user.metadata.name == \"homelab-ci\""},
        {"match": "ctx.user.spec.type == \"WORKLOAD\""},
        {"match": "ctx.session.status.type == \"CLIENTLESS\""},
        {"match": "ctx.service.metadata.name == \"kubernetes-api-ci.default\""},
        {"match": "ctx.service.spec.mode == \"KUBERNETES\""}
      ]}}
    }]
  ' >/dev/null
echo "::endgroup::"

echo "::group::Exact workflow dispatch commits"
for workflow_job in \
  '.github/workflows/homelab-diagnostics.yml:grafana' \
  '.github/workflows/terragrunt-apply.yml:static-policy'; do
  workflow="${workflow_job%%:*}"
  job="${workflow_job##*:}"
  yq -o=json '.' "$workflow" |
    jq -e --arg job "$job" '
      .on.workflow_dispatch.inputs.expected_sha.required == true and
      .jobs[$job].steps[0].name == "Verify Dispatch Commit" and
      .jobs[$job].steps[0].env.ACTUAL_SHA == "${{ github.sha }}" and
      .jobs[$job].steps[0].env.EXPECTED_SHA == "${{ inputs.expected_sha }}" and
      (.jobs[$job].steps[0].run | contains("test \"${ACTUAL_SHA}\" = \"${EXPECTED_SHA}\""))
    ' >/dev/null
done
yq -o=json '.' .github/workflows/terragrunt-apply.yml |
  jq -e '
    (.concurrency == null) and
    .jobs["static-policy"].steps[0].if == "github.event_name == '\''workflow_dispatch'\''" and
    .jobs["terragrunt-apply"].needs == ["static-policy"] and
    .jobs["terragrunt-apply"].concurrency == {
      "group": "terragrunt-apply-production",
      "cancel-in-progress": false,
      "queue": "max"
    }
  ' >/dev/null
echo "::endgroup::"

echo "::group::Renovate config"
jq empty renovate.json
echo "::endgroup::"

echo "::group::Image digest pins"
tag_only_images="$(
  {
    rg -n '^\s*tag:\s*["'\'']?[^"'\''#[:space:]][^#]*$' clusters/homelab || true
    rg -n '^\s*image:\s*[^[:space:]#]+:[^@#[:space:]]+' clusters/homelab || true
  } \
    | rg -v '@sha256:' \
    || true
)"

if [[ -n "$tag_only_images" ]]; then
  echo "Container images must be pinned as tag@sha256:digest:" >&2
  printf '%s\n' "$tag_only_images" >&2
  exit 1
fi
echo "::endgroup::"

echo "::group::Secret scan"
bash scripts/ci/secret-scan.sh
echo "::endgroup::"

echo "::group::Checkov"
if command -v checkov >/dev/null 2>&1; then
  checkov --config-file .checkov.yaml --framework terraform --directory IaC/modules
  checkov --config-file .checkov.yaml --framework kubernetes --directory clusters
  checkov --config-file .checkov.yaml --framework secrets --directory .
elif [[ "${CI:-}" == "true" ]]; then
  echo "checkov is required in CI but was not found in PATH" >&2
  exit 1
else
  echo "::warning::checkov is not available in this local shell; GitHub Actions still enforces Checkov on Linux."
fi
echo "::endgroup::"

echo "::group::Whitespace"
git diff --check
echo "::endgroup::"
