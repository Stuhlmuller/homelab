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
  cd IaC/live/argocd-apps
  terragrunt_stack_changed() { return 0; }
  [[ "$(terragrunt_changed_filter 'IaC/live/argocd-apps/*')" == "*" ]]
  terragrunt_stack_changed() { [[ "${2:-false}" == "true" ]]; }
  [[ "$(terragrunt_changed_filter 'IaC/live/argocd-apps/*' true)" == "*" ]]
  [[ "$(terragrunt_changed_filter 'IaC/live/argocd-apps/*')" == "IaC/live/argocd-apps/* | [main...HEAD]" ]]
  [[ "$(TERRAGRUNT_ARGOCD_APP=affine terragrunt_argocd_app_filter)" == "affine" ]]
  if TERRAGRUNT_ARGOCD_APP=../bootstrap terragrunt_argocd_app_filter; then
    echo "Unsafe Argo CD Application unit filter was accepted" >&2
    exit 1
  fi
  [[ -z "$(TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=false terragrunt_argocd_app_state_repair_unit)" ]]
  if TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=invalid terragrunt_argocd_app_state_repair_unit; then
    echo "Invalid Argo CD Application state repair value was accepted" >&2
    exit 1
  fi
  if TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=true GITHUB_EVENT_NAME=push \
    TERRAGRUNT_ARGOCD_APP=affine terragrunt_argocd_app_state_repair_unit; then
    echo "Non-dispatch Argo CD Application state repair was accepted" >&2
    exit 1
  fi
  if TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=true GITHUB_EVENT_NAME=workflow_dispatch \
    terragrunt_argocd_app_state_repair_unit; then
    echo "Untargeted Argo CD Application state repair was accepted" >&2
    exit 1
  fi
  if TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=true GITHUB_EVENT_NAME=workflow_dispatch \
    TERRAGRUNT_ARGOCD_APP=../bootstrap terragrunt_argocd_app_state_repair_unit; then
    echo "Unsafe Argo CD Application state repair target was accepted" >&2
    exit 1
  fi
  [[ "$(TERRAGRUNT_REPAIR_ARGOCD_APP_STATE=true GITHUB_EVENT_NAME=workflow_dispatch \
    TERRAGRUNT_ARGOCD_APP=affine terragrunt_argocd_app_state_repair_unit)" == "affine" ]]
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

echo "::group::Prowlarr config normalization"
bash scripts/ci/prowlarr-config-check.sh
echo "::endgroup::"

echo "::group::Octelium catalog security contracts"
yq ea -o=json -I=0 '[.]' docs/examples/octelium/homelab-services.yaml |
  jq -e '
    [.[] | select(.kind == "User" and .metadata.name == "homelab-ci")] as $users |
    [.[] | select(.kind == "Policy" and .metadata.name == "homelab-ci-kubernetes-api-access")] as $policies |
    [.[] | select(.kind == "Service" and .metadata.name == "nofx")] as $nofx |
    ($users | length) == 1 and
    $users[0].spec.type == "WORKLOAD" and
    $users[0].spec.session.clientlessDuration == {"days": 30} and
    $users[0].spec.session.accessTokenDuration == {"days": 30} and
    ($nofx | length) == 1 and
    ($nofx[0].spec.isAnonymous // false) == false and
    $nofx[0].spec.authorization.policies == ["homelab-human-web-access"] and
    $nofx[0].spec.config.http.header.authorizationMode == "PASS" and
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
      .jobs[$job].steps[0].env.ACTUAL_REF == "${{ github.ref }}" and
      .jobs[$job].steps[0].env.ACTUAL_SHA == "${{ github.sha }}" and
      .jobs[$job].steps[0].env.EXPECTED_SHA == "${{ inputs.expected_sha }}" and
      (.jobs[$job].steps[0].run | contains("refs/heads/main")) and
      (.jobs[$job].steps[0].run | contains("test \"${ACTUAL_SHA}\" = \"${EXPECTED_SHA}\""))
    ' >/dev/null
done
yq -o=json '.' .github/workflows/terragrunt-apply.yml |
  jq -e '
    (.concurrency == null) and
    .on.workflow_dispatch.inputs.repair_argocd_app_state == {
      "description": "Untaint the selected Argo CD Application before reconciling it",
      "required": false,
      "default": false,
      "type": "boolean"
    } and
    .jobs["static-policy"].steps[0].if == "github.event_name == '\''workflow_dispatch'\''" and
    .jobs["terragrunt-apply"].needs == ["static-policy"] and
    .jobs["terragrunt-apply"].env.TERRAGRUNT_ARGOCD_APP == "${{ inputs.argocd_app }}" and
    .jobs["terragrunt-apply"].env.TERRAGRUNT_REPAIR_ARGOCD_APP_STATE == "${{ inputs.repair_argocd_app_state }}" and
    .jobs["terragrunt-apply"].concurrency == {
      "group": "terragrunt-apply-production",
      "cancel-in-progress": false,
      "queue": "max"
    } and
    (.jobs["terragrunt-apply"].steps[] | select(.name == "Resolve Last Successful Apply").run | contains("event=push"))
  ' >/dev/null
bash -n scripts/ci/terragrunt-apply.sh
rg -Fq 'terragrunt run -- untaint -no-color kubernetes_manifest.this' scripts/ci/terragrunt-apply.sh
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
