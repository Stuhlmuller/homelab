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

# Exercise the Argo chart parameters against both values revisions. Deployment
# mode ignores the CronJob settings, so validate the rendered workload kind.
rendered="$(mktemp)"
old_values="$(mktemp)"
trap 'rm -f "$rendered" "$old_values"' EXIT

render_stage() {
  helm template descheduler descheduler --repo https://kubernetes-sigs.github.io/descheduler \
    --version 0.33.0 --namespace kube-system --values "$1" --set kind=CronJob --set suspend=true |
    yq ea -o=json -I=0 '[.]' - >"$rendered"
  jq -e '
    ([.[] | select(.kind == "Deployment" or .kind == "DaemonSet" or .kind == "StatefulSet" or .kind == "Job")] | length == 0) and
    ([.[] | select(.kind == "CronJob")] |
      length == 1 and
      .[0].metadata.name == "descheduler" and
      .[0].spec.suspend == true)
  ' "$rendered" >/dev/null
}

render_stage "$values"
python3 -I scripts/ci/descheduler-policy-check.py "$rendered"

# Before the repaired values arrive on main, the previously deployed values
# must also render one suspended CronJob under the same overrides.
# Keep the exact values from 934770124f6e3b3c1b0857ce8e510e0ea7a1e894 in the fixture
# so the same check can run in both shallow and full checkouts.
cat >"$old_values" <<'HELM_VALUES'
kind: Deployment
image:
  repository: harbor.stinkyboi.com/mirror/registry.k8s.io/descheduler/descheduler
  tag: v0.33.0@sha256:de38c88dcb1e7d822c4bd320551cc55e541c160c6ba380d99772949b0c967ab0
deschedulerPolicy:
  profiles:
    - name: conservative
      pluginConfig:
        - name: DefaultEvictor
          args:
            evictSystemCriticalPods: false
            ignorePvcPods: true
            minReplicas: 2
      plugins:
        balance:
          enabled:
            - LowNodeUtilization
        deschedule:
          enabled:
            - RemovePodsViolatingInterPodAntiAffinity
deschedulingInterval: 30m
HELM_VALUES
printf '%s  %s\n' \
  '485464193b084cae0385248894e1c969e793c805eb3d7b2d4139d649418c5c76' "$old_values" |
  sha256sum --check >/dev/null
render_stage "$old_values"
echo "Descheduler: chart overrides render only a suspended CronJob with both values revisions"
