#!/usr/bin/env bash
set -euo pipefail

echo "::group::Conftest policies"
workflow_files=()
while IFS= read -r yaml_file; do
  workflow_files+=("$yaml_file")
done < <(
  find .github \
    \( -name '*.yaml' -o -name '*.yml' \) \
    -not -path './.terragrunt-cache/*' \
    -print 2>/dev/null | sort
)

if ((${#workflow_files[@]} > 0)); then
  conftest test --policy policy --output github "${workflow_files[@]}"
fi

rendered_dir="$(mktemp -d)"
trap 'rm -rf "$rendered_dir"' EXIT
rendered_files=()

while IFS= read -r overlay; do
  rendered_file="${rendered_dir}/$(printf '%s' "$overlay" | tr '/.' '__').yaml"
  echo "rendering ${overlay} for policy evaluation"
  kubectl kustomize "$overlay" >"$rendered_file"
  rendered_files+=("$rendered_file")
done < <(
  find clusters/homelab/argocd clusters/homelab/apps clusters/homelab/platform \
    -name kustomization.yaml \
    -exec dirname {} \; | sort
)

if ((${#rendered_files[@]} > 0)); then
  conftest test --policy policy --output github "${rendered_files[@]}"
fi
echo "::endgroup::"
