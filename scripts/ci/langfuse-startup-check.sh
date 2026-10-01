#!/usr/bin/env bash
set -euo pipefail

values=clusters/homelab/apps/langfuse/values.yaml
# Keep the global fallback aligned with both roles, including a forward fence.
yq -o=json '.langfuse | [.replicas, .web.replicas, .worker.replicas]' "$values" |
  jq -e 'unique | length == 1' >/dev/null
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
      .resources.requests.memory == "2Gi" and
      .resources.limits.memory == "2Gi" and
      .livenessProbe.initialDelaySeconds >= 600 and
      .livenessProbe.httpGet.path == "/api/public/health" and
      .livenessProbe.periodSeconds == 10 and
      .livenessProbe.failureThreshold == 3 and
      .readinessProbe.httpGet.path == "/api/public/ready" and
      .readinessProbe.initialDelaySeconds == 20))
  ' >/dev/null
echo "Langfuse: rendered replicas, web memory budget, startup allowance and health probes verified"

# Keep the recovery copy managed without redeploying its one-shot writer.
kubectl kustomize clusters/homelab/apps/langfuse |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '
    [.[] | select(.kind == "Job" and
      (.metadata.name | startswith("langfuse-empty-schema-recovery")))] as $jobs |
    [.[] | select(.kind == "ConfigMap" and
      (.metadata.name | startswith("langfuse-empty-schema-recovery")))] as $code |
    [.[] | select(.kind == "PersistentVolumeClaim" and .metadata.name == "langfuse-migration-recovery")] as $claims |
    ($jobs | length == 0) and ($code | length == 0) and ($claims | length == 1) and
    ($claims[0] | .metadata.namespace == "langfuse" and
      .spec.storageClassName == "nfs-default" and
      .spec.accessModes == ["ReadWriteOnce"] and
      .spec.resources.requests.storage == "1Gi" and
      .metadata.annotations["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false")
  ' >/dev/null
echo "Langfuse: recovery volume retained and one-shot Job/ConfigMap absent"
