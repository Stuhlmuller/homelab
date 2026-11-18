#!/usr/bin/env bash
set -euo pipefail

# Keep this render tied to the declared chart and values contract. A chart bump
# must update the fixture together with the owning stack.
python3 - <<'PYTHON'
from pathlib import Path

source = " ".join(Path("IaC/homelab/us-west-2/apps/descheduler/stack.hcl").read_text().split())
expected = ' '.join('''
{
  repoURL = "https://kubernetes-sigs.github.io/descheduler"
  chart = "descheduler"
  path = "."
  targetRevision = "0.33.0"
  helm = {
    releaseName = "descheduler"
    valueFiles = ["$values/clusters/homelab/apps/descheduler/values.yaml"]
    parameters = [ { name = "kind" value = "CronJob" }, { name = "suspend" value = "true" } ]
  }
}
'''.split())
assert source.count(expected) == 1, "Descheduler stack changed: update the cadence render fixture"
PYTHON

values=clusters/homelab/apps/descheduler/values.yaml
yq -o=json '.' "$values" |
  jq -e '.kind == "CronJob" and .suspend == true and .deschedulingInterval == "30m" and (has("schedule") | not)' >/dev/null

# Check the chart output: Deployment mode ignores the CronJob schedule value.
rendered="$(mktemp)"
pinned_values="$(mktemp)"
trap 'rm -f "$rendered" "$pinned_values"' EXIT
helm template descheduler descheduler --repo https://kubernetes-sigs.github.io/descheduler \
  --version 0.33.0 --namespace kube-system --values "$values" |
  yq ea -o=json -I=0 '[.]' - >"$rendered"
jq -e '
    ([.[] | select(.kind == "Deployment")] | length == 0) and
    ([.[] | select(.kind == "CronJob")] |
      length == 1 and
      .[0].metadata.name == "descheduler" and
      .[0].spec.suspend == true)
  ' "$rendered" >/dev/null
echo "Descheduler: only a suspended CronJob renders during staging"
python3 -I scripts/ci/descheduler-policy-check.py "$rendered"

# The Argo values ref stays on the old inert revision during stage one. Its
# Helm parameter must still render a zero-replica Deployment after sync.
git show 934770124f6e3b3c1b0857ce8e510e0ea7a1e894:clusters/homelab/apps/descheduler/values.yaml >"$pinned_values"
helm template descheduler descheduler --repo https://kubernetes-sigs.github.io/descheduler \
  --version 0.33.0 --namespace kube-system --values "$pinned_values" --set kind=CronJob --set suspend=true |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '([.[] | select(.kind == "Deployment")] | length == 0) and
    ([.[] | select(.kind == "CronJob" and .metadata.name == "descheduler") | .spec.suspend] == [true])' >/dev/null
echo "Descheduler: pinned old values plus chart override render only a suspended CronJob"
