#!/usr/bin/env bash
set -euo pipefail

: "${OCTELIUM_AUTH_TOKEN:?OCTELIUM_AUTH_TOKEN must contain the homelab-plan token}"
KUBE_API_SERVER_URL="${KUBE_API_SERVER_URL:-https://kubernetes-api-plan.stinkyboi.com}"

for command in kubectl mktemp; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "error: ${command} is required" >&2
    exit 127
  }
done

plan_home="$(mktemp -d "${TMPDIR:-/tmp}/homelab-plan-access.XXXXXX")"
trap 'rm -rf "$plan_home"' EXIT

HOME="$plan_home" \
  KUBECONFIG="$plan_home/.kube/config" \
  KUBE_API_SERVER_URL="$KUBE_API_SERVER_URL" \
  OCTELIUM_AUTH_TOKEN="$OCTELIUM_AUTH_TOKEN" \
  bash scripts/ci/install-kubeconfig.sh
unset OCTELIUM_AUTH_TOKEN

kubectl_plan=(
  kubectl
  --kubeconfig "$plan_home/.kube/config"
  --request-timeout=15s
)

"${kubectl_plan[@]}" get applications.argoproj.io grafana --namespace argocd >/dev/null
"${kubectl_plan[@]}" get customresourcedefinitions.apiextensions.k8s.io >/dev/null
"${kubectl_plan[@]}" get --raw=/apis >/dev/null
"${kubectl_plan[@]}" get --raw=/openapi/v2 >/dev/null

require_denied() {
  local label="$1"
  local error_file
  shift
  error_file="$(mktemp "${TMPDIR:-/tmp}/homelab-plan-denial.XXXXXX")"

  if "$@" >/dev/null 2>"$error_file"; then
    echo "error: ${label} unexpectedly succeeded" >&2
    rm -f "$error_file"
    exit 1
  fi
  if ! grep -Fq 'Octelium: Unauthorized request' "$error_file"; then
    echo "error: ${label} was not denied by Octelium policy" >&2
    sed 's/^/  /' "$error_file" >&2
    rm -f "$error_file"
    exit 1
  fi
  rm -f "$error_file"
}

require_denied \
  "Secret list" \
  "${kubectl_plan[@]}" get secrets --all-namespaces
require_denied \
  "Pod list outside the provider allowlist" \
  "${kubectl_plan[@]}" get pods --all-namespaces
require_denied \
  "Application list" \
  "${kubectl_plan[@]}" get applications.argoproj.io --namespace argocd
require_denied \
  "Application watch" \
  "${kubectl_plan[@]}" get applications.argoproj.io grafana \
  --namespace argocd --watch-only
require_denied \
  "server-side dry-run namespace creation" \
  "${kubectl_plan[@]}" create namespace homelab-plan-deny-test \
  --dry-run=server -o name
require_denied \
  "non-resource metrics read" \
  "${kubectl_plan[@]}" get --raw=/metrics

echo "Octelium plan access allows only provider-required reads and denies other resources, mutations, and unapproved non-resource paths."
