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
  }
}
'''.split())
assert source.count(expected) == 1, "Descheduler stack changed: update the cadence render fixture"
PYTHON

values=clusters/homelab/apps/descheduler/values.yaml
yq -o=json '.' "$values" |
  jq -e '.kind == "Deployment" and .deschedulingInterval == "30m" and (has("schedule") | not)' >/dev/null

# Check the chart output: Deployment mode ignores the CronJob schedule value.
helm template descheduler descheduler --repo https://kubernetes-sigs.github.io/descheduler \
  --version 0.33.0 --namespace kube-system --values "$values" |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '
    ([.[] | select(.kind == "CronJob")] | length == 0) and
    ([.[] | select(.kind == "Deployment")] |
      length == 1 and
      .[0].metadata.name == "descheduler" and
      ([.[0].spec.template.spec.containers[] |
        select(.name == "descheduler") | .args[] |
        select(startswith("--descheduling-interval="))] == ["--descheduling-interval=30m"]))
  ' >/dev/null
echo "Descheduler: Deployment renders exactly one 30-minute interval"
