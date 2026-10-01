#!/usr/bin/env bash
set -euo pipefail

values=clusters/homelab/apps/langfuse/values.yaml
# Remove this temporary fence assertion only in the reviewed post-recovery resume.
yq -o=json '.langfuse | [.replicas, .web.replicas, .worker.replicas]' "$values" |
  jq -e 'all(.[]; . == 0)' >/dev/null
# Check the actual pinned chart output: unsupported values silently do nothing.
helm template langfuse langfuse --repo https://langfuse.github.io/langfuse-k8s \
  --version 2.1.1 --namespace langfuse \
  --values "$values" |
  yq ea -o=json -I=0 '[.]' - |
  jq -e --argjson web "$(yq '.langfuse.web.replicas' "$values")" \
    --argjson worker "$(yq '.langfuse.worker.replicas' "$values")" '
    [.[] | select(.kind == "Deployment" and
      (.metadata.name == "langfuse-web" or .metadata.name == "langfuse-worker"))] |
    length == 2 and
    all(.[]; .spec.replicas == (if .metadata.name == "langfuse-web" then $web else $worker end)) and
    ([.[] | select(.metadata.name == "langfuse-web")
      | .spec.template.spec.containers[] | select(.name == "langfuse-web")] |
    length == 1 and (.[0] |
      .livenessProbe.initialDelaySeconds >= 600 and
      .livenessProbe.httpGet.path == "/api/public/health" and
      .livenessProbe.periodSeconds == 10 and
      .livenessProbe.failureThreshold == 3 and
      .readinessProbe.httpGet.path == "/api/public/ready" and
      .readinessProbe.initialDelaySeconds == 20))
  ' >/dev/null
echo "Langfuse: rendered replicas, migration startup allowance and health probes verified"
