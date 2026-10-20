#!/usr/bin/env bash
set -euo pipefail

[[ $# == 0 && "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REF:-}" == refs/heads/main &&
  "${GITHUB_SHA:-}" == "${EXPECTED_SHA:-}" && "${GH_REPO:-}" == Stuhlmuller/homelab &&
  "${EXPECTED_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || exit 2

config=scripts/config/openclaw-enterprise.json
jq -e '
  .schemaVersion == 1 and
  (.installationPhase == "lifecycle-validation" or
   .installationPhase == "production-inactive" or
   .installationPhase == "active") and
  .source.repository == "https://github.com/openclaw/openclaw-enterprise" and
  .source.revision == "33bb74590a749f37934da4502fca6035cd234a55"
' "$config" >/dev/null

foundation="$(kubectl --request-timeout=15s -n argocd get application openclaw-enterprise-foundation -o json)"
jq -e '
  .metadata.name == "openclaw-enterprise-foundation" and
  .spec.project == "openclaw-enterprise" and
  .spec.destination.namespace == "openclaw-system" and
  .spec.sources == [{"repoURL":"https://github.com/Stuhlmuller/homelab.git",
                     "path":"clusters/homelab/apps/openclaw-enterprise-foundation",
                     "targetRevision":"main"}] and
  .spec.syncPolicy == {
    "automated": {"allowEmpty": false, "enabled": false, "prune": false, "selfHeal": false},
    "syncOptions": ["CreateNamespace=false", "ServerSideApply=true"],
    "retry": {"limit": 0, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "2m"}}
  } and
  .operation == null
' <<<"$foundation" >/dev/null

enterprise="$(kubectl --request-timeout=15s -n argocd get application openclaw-enterprise -o json)"
jq -e '
  .metadata.name == "openclaw-enterprise" and
  .spec.project == "openclaw-enterprise" and
  .spec.destination.namespace == "openclaw-system" and
  .spec.sources == [
    {"repoURL":"https://github.com/openclaw/openclaw-enterprise.git",
     "path":"deploy/helm/openclaw-enterprise",
     "targetRevision":"33bb74590a749f37934da4502fca6035cd234a55",
     "helm":{"releaseName":"oce","valueFiles":["$values/clusters/homelab/apps/openclaw-enterprise/values.yaml"]}},
    {"repoURL":"https://github.com/Stuhlmuller/homelab.git",
     "path":".","targetRevision":"main","ref":"values",
     "directory":{"include":".argocd-values-ref-placeholder.yaml"}},
    {"repoURL":"https://github.com/Stuhlmuller/homelab.git",
     "path":"clusters/homelab/apps/openclaw-enterprise","targetRevision":"main"}
  ] and
  .spec.syncPolicy == {
    "automated": {"allowEmpty": false, "enabled": false, "prune": false, "selfHeal": false},
    "syncOptions": ["CreateNamespace=false", "ServerSideApply=true"],
    "retry": {"limit": 0, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "2m"}}
  } and
  .operation == null
' <<<"$enterprise" >/dev/null

argocd app wait platform-envoy-gateway --core --sync --health --operation --timeout 600 >/dev/null
[[ "$(gh api "repos/${GH_REPO}/git/ref/heads/main" --jq .object.sha)" == "$EXPECTED_SHA" ]] || exit 2
argocd app sync openclaw-enterprise-foundation --core --revisions "$EXPECTED_SHA" --source-positions 1 --timeout 1800 >/dev/null
argocd app wait openclaw-enterprise-foundation --core --sync --health --operation --timeout 1800 >/dev/null
kubectl --request-timeout=15s -n argocd get application openclaw-enterprise-foundation -o json |
  jq -e --arg sha "$EXPECTED_SHA" '.status.operationState.phase == "Succeeded" and .status.sync.revisions == [$sha] and .status.health.status == "Healthy"' >/dev/null
[[ "$(gh api "repos/${GH_REPO}/git/ref/heads/main" --jq .object.sha)" == "$EXPECTED_SHA" ]] || exit 2
argocd app sync openclaw-enterprise --core \
  --revisions 33bb74590a749f37934da4502fca6035cd234a55 --source-positions 1 \
  --revisions "$EXPECTED_SHA" --source-positions 2 \
  --revisions "$EXPECTED_SHA" --source-positions 3 \
  --timeout 1800 >/dev/null
argocd app wait openclaw-enterprise --core --sync --health --operation --timeout 1800 >/dev/null
kubectl --request-timeout=15s -n argocd get application openclaw-enterprise -o json |
  jq -e --arg sha "$EXPECTED_SHA" '
    .status.operationState.phase == "Succeeded" and
    .status.sync.revisions == ["33bb74590a749f37934da4502fca6035cd234a55", $sha, $sha] and
    .status.health.status == "Healthy"
  ' >/dev/null
