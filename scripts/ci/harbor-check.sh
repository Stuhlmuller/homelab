#!/usr/bin/env bash
set -euo pipefail

rendered_dir="$(mktemp -d)"
trap 'rm -rf -- "$rendered_dir"' EXIT
helm pull harbor --repo https://helm.goharbor.io --version 1.19.2 --destination "$rendered_dir"
for render in first second; do
  helm template harbor "$rendered_dir/harbor-1.19.2.tgz" --namespace harbor \
    --values clusters/homelab/apps/harbor/values.yaml >"$rendered_dir/${render}.yaml"
done
cmp "$rendered_dir/first.yaml" "$rendered_dir/second.yaml"
kubectl kustomize clusters/homelab/apps/harbor >"$rendered_dir/resources.yaml"
conftest test --policy policy "$rendered_dir/first.yaml" "$rendered_dir/resources.yaml"
yq ea -o=json -I=0 '[.]' "$rendered_dir/first.yaml" "$rendered_dir/resources.yaml" |
  python3 -I scripts/ci/harbor-render-check.py
