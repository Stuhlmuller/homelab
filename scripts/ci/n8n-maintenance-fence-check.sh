#!/usr/bin/env bash
set -euo pipefail

stack=IaC/homelab/us-west-2/apps/n8n/stack.hcl
base=clusters/homelab/apps/n8n/values.yaml
fence=clusters/homelab/apps/n8n/maintenance-fence.values.yaml
version=4.4.0
[[ $# -eq 0 || ( $# -eq 1 && $1 == --source-only ) ]]

active_revisions="$(rg -N '^[[:space:]]*targetRevision[[:space:]]*=' "$stack" |
  sed -E 's/^[[:space:]]*//; s/[[:space:]]*=[[:space:]]*/ = /')"
expected_revisions=$'targetRevision = "4.4.0"\ntargetRevision = local.shared.target_revision\ntargetRevision = local.shared.target_revision'
[[ "$active_revisions" == "$expected_revisions" ]]
active_value_files="$(rg -N '^[[:space:]]*valueFiles[[:space:]]*=' "$stack" |
  sed -E 's/^[[:space:]]*//; s/[[:space:]]*=[[:space:]]*/ = /')"
expected_value_files="valueFiles = [\"\$values/clusters/homelab/apps/n8n/values.yaml\"]"
[[ "$active_value_files" == "$expected_value_files" ]]
[[ "${1:-}" != --source-only ]] || exit 0
[[ "$(yq -o=json -I=0 '.' "$fence")" == '{"controllers":{"n8n":{"replicas":0}}}' ]]

chart_dir="$(mktemp -d)"
trap 'rm -rf -- "$chart_dir"' EXIT
helm pull app-template --repo https://bjw-s-labs.github.io/helm-charts \
  --version "$version" --destination "$chart_dir"
chart="$chart_dir/app-template-$version.tgz"

render_controllers() {
  helm template n8n "$chart" --namespace automation -f "$base" "$@" |
    yq ea -o=json -I=0 \
      '[select(.kind == "Deployment" or .kind == "Job") |
        {"kind": .kind, "name": .metadata.name, "replicas": .spec.replicas}]' -
}

[[ "$(render_controllers)" == '[{"kind":"Deployment","name":"n8n","replicas":1}]' ]]
[[ "$(render_controllers -f "$fence")" == '[{"kind":"Deployment","name":"n8n","replicas":0}]' ]]
echo 'n8n maintenance fence renders one active replica, zero fenced replicas, and no Job'
