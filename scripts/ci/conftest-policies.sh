#!/usr/bin/env bash
set -euo pipefail

echo "::group::Conftest policies"
conftest verify --policy policy --output github

rendered_dir="$(mktemp -d)"
trap 'rm -rf "$rendered_dir"' EXIT
workflow_event_fixture="${rendered_dir}/workflow-event.yaml"

for event_config in \
  '  pull_request_target:' \
  '  pull_request_target: false' \
  $'  pull_request_target:\n    types: [opened]'; do
  printf '%s\n' 'name: Unsafe event' 'on:' "$event_config" >"$workflow_event_fixture"
  if event_output="$(conftest test --policy policy --output stdout "$workflow_event_fixture" 2>&1)"; then
    echo "Conftest YAML parsing must not allow pull_request_target: ${event_config}" >&2
    exit 1
  fi
  [[ "$event_output" == *"must not use pull_request_target"* ]] || {
    echo "Conftest YAML event fixture failed without the expected policy denial." >&2
    exit 1
  }
done

printf '%s\n' 'name: Safe event' 'on:' '  pull_request:' >"$workflow_event_fixture"
conftest test --policy policy --output github "$workflow_event_fixture"

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
