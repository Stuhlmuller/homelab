#!/usr/bin/env bash
set -euo pipefail

stack=IaC/homelab/us-west-2/apps/n8n/stack.hcl
base=clusters/homelab/apps/n8n/values.yaml
fence=clusters/homelab/apps/n8n/maintenance-fence.values.yaml
version=4.4.0

rg -Fq 'targetRevision = "4.4.0"' "$stack"
rg -Fq 'valueFiles  = ["$values/clusters/homelab/apps/n8n/values.yaml"]' "$stack"
! rg -Fq 'maintenance-fence.values.yaml' "$stack"
! rg -Fq 'migration-v1.values.yaml' "$stack"
! rg -Fq 'migration-github-trigger-v1.values.yaml' "$stack"
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
