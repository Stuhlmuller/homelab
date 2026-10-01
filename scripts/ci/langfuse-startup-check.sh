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

# Temporary recovery stage: the native image entrypoint must never run first.
kubectl kustomize clusters/homelab/apps/langfuse |
  yq ea -o=json -I=0 '[.]' - |
  jq -e '
    [.[] | select(.kind == "Job")] as $jobs |
    [.[] | select(.kind == "PersistentVolumeClaim" and .metadata.name == "langfuse-migration-recovery")] as $claims |
    ($jobs | length == 1) and ($claims | length == 1) and
    ($claims[0] | .spec.storageClassName == "nfs-default" and
      .metadata.annotations["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false") and
    ($jobs[0].spec | .backoffLimit == 0 and .parallelism == 1 and .completions == 1 and
      (has("activeDeadlineSeconds") | not) and
      (.template.spec | .restartPolicy == "Never" and .serviceAccountName == "langfuse" and
        .automountServiceAccountToken == false and
        (.containers | length == 1) and
        (.containers[0] | .command == ["node", "/recovery-code/recover-empty-schema.mjs"] and
          .image == "docker.io/langfuse/langfuse:4.35.0@sha256:a5d8d2457702ab7e051bc0788d73871970caebd10aae6635e87cfb736e4067cd" and
          ((.env // []) | length == 0)) and
        any(.volumes[]; .name == "recovery" and .persistentVolumeClaim.claimName == "langfuse-migration-recovery") and
        any(.volumes[]; .name == "credentials" and .secret.secretName == "langfuse-secrets" and
          .secret.items == [{key: "clickhouse-password", path: "clickhouse-password"}])))
  ' >/dev/null
echo "Langfuse: retained recovery volume and guarded native Job verified"
