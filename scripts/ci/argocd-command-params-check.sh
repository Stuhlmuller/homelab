#!/usr/bin/env bash
set -euo pipefail

chart_dir="$(mktemp -d)"
trap 'rm -rf -- "$chart_dir"' EXIT
bootstrap="$(terragrunt --log-disable --working-dir IaC/homelab/us-west-2/bootstrap/argocd \
  render --json --write=false --no-color)"
chart="$(jq -er '.inputs.chart' <<<"$bootstrap")"
version="$(jq -er '.inputs.chart_version' <<<"$bootstrap")"
repo="$(jq -er '.inputs.repository' <<<"$bootstrap")"
digest="$(jq -er --arg chart "$chart" --arg version "$version" --arg repo "$repo" '
  [.charts[] | select(.chart == $chart and .version == $version and .repository == $repo)] |
  select(length == 1) | .[0].sha256
' scripts/config/harbor-helm-charts.json)"
HELM_CACHE_HOME="$chart_dir/cache" HELM_REPOSITORY_CONFIG="$chart_dir/repositories.yaml" \
  helm pull "$chart" --repo "$repo" --version "$version" --destination "$chart_dir"
package="$chart_dir/$chart-$version.tgz"
[[ "$(sha256sum "$package" | cut -d ' ' -f1)" == "$digest" ]] || {
  echo "Argo CD chart checksum does not match the committed chart inventory" >&2
  exit 1
}
jq -er '.inputs.values | select(length == 1) | .[0]' <<<"$bootstrap" |
  helm template "$(jq -er '.inputs.name' <<<"$bootstrap")" "$package" \
    --namespace "$(jq -er '.inputs.namespace' <<<"$bootstrap")" --values - >"$chart_dir/helm.yaml"
kubectl kustomize clusters/homelab/argocd/self-management >"$chart_dir/self-management.yaml"
for manifests in "$chart_dir/helm.yaml" "$chart_dir/self-management.yaml"; do
  yq ea -o=json -I=0 '[.]' "$manifests" | jq -e '
    map(select(.kind == "ConfigMap" and .metadata.namespace == "argocd" and
      .metadata.name == "argocd-cmd-params-cm")) |
    .[0] as $params | length == 1 and
    $params.data."controller.sync.timeout.seconds" == "900" and $params.data."server.insecure" == "true" and
    $params.metadata.annotations."argocd.argoproj.io/sync-options" == "Prune=false" and
    $params.metadata.annotations."argocd.argoproj.io/compare-options" == "IgnoreExtraneous"
  ' >/dev/null || {
    echo "Command parameters or handoff annotations missing from ${manifests##*/}" >&2
    exit 1
  }
done
yq ea -o=json -I=0 '[.]' "$chart_dir/helm.yaml" | jq -e '
  any(.[]; .kind == "StatefulSet" and .metadata.name == "argocd-application-controller" and
    .spec.template.metadata.annotations."homelab.stuhlmuller.dev/sync-timeout-revision" == "v2")
' >/dev/null
