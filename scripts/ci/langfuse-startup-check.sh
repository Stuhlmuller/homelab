#!/usr/bin/env bash
set -euo pipefail

# Check the actual pinned chart output: unsupported values silently do nothing.
helm template langfuse langfuse --repo https://langfuse.github.io/langfuse-k8s \
  --version 2.1.1 --namespace langfuse \
  --values clusters/homelab/apps/langfuse/values.yaml |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '
    [.[] | select(.kind == "Deployment" and .metadata.name == "langfuse-web")
      | .spec.template.spec.containers[] | select(.name == "langfuse-web")] |
    length == 1 and (.[0] |
      .livenessProbe.initialDelaySeconds >= 600 and
      .livenessProbe.httpGet.path == "/api/public/health" and
      .livenessProbe.periodSeconds == 10 and
      .livenessProbe.failureThreshold == 3 and
      .readinessProbe.httpGet.path == "/api/public/ready" and
      .readinessProbe.initialDelaySeconds == 20)
  ' >/dev/null
echo "Langfuse: rendered migration startup allowance and health probes verified"
