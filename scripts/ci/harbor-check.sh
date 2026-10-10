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
{
  kubectl kustomize clusters/homelab/apps/harbor
  printf '\n---\n'
  # The CI-created Job participates in prerequisite/policy checks without
  # becoming a periodically recreated Argo application resource.
  cat clusters/homelab/apps/harbor/signing-job.yaml
} >"$rendered_dir/resources.yaml"
kubectl kustomize clusters/homelab/apps/harbor-bootstrap >"$rendered_dir/recovery.yaml"
recovery_images="$(yq ea -N '.. | select(tag == "!!map" and has("image")) | .image | select(tag == "!!str")' "$rendered_dir/recovery.yaml")"
[[ -n "$recovery_images" ]]
if rg -q '^harbor\.stinkyboi\.com/' <<<"$recovery_images" || \
   rg -qv '@sha256:[0-9a-f]{64}$' <<<"$recovery_images"; then
  echo "Harbor recovery workloads must use pinned upstream images" >&2
  exit 1
fi
conftest test --policy policy "$rendered_dir/first.yaml" "$rendered_dir/resources.yaml"
yq ea -o=json -I=0 '[.]' "$rendered_dir/first.yaml" "$rendered_dir/resources.yaml" |
  python3 -I scripts/ci/harbor-render-check.py
