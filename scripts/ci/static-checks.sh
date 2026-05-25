#!/usr/bin/env bash
set -euo pipefail

echo "::group::Terragrunt HCL"
terragrunt hcl fmt --check
terragrunt hcl validate
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

echo "::group::Conftest policies"
mapfile -t yaml_files < <(
  find .github clusters \
    \( -name '*.yaml' -o -name '*.yml' \) \
    -not -path './.terragrunt-cache/*' \
    -print 2>/dev/null | sort
)

if ((${#yaml_files[@]} > 0)); then
  conftest test --policy policy --output github "${yaml_files[@]}"
fi
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
