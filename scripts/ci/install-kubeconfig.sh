#!/usr/bin/env bash
set -euo pipefail

: "${KUBE_CONFIG_B64:?KUBE_CONFIG_B64 must contain the base64-encoded kubeconfig}"

install -m 0700 -d "$HOME/.kube"
printf '%s' "$KUBE_CONFIG_B64" | base64 --decode >"$HOME/.kube/config"
chmod 0600 "$HOME/.kube/config"

if [ -n "${KUBE_API_SERVER_URL:-}" ] || [ -n "${KUBE_TLS_SERVER_NAME:-}" ]; then
  current_context="$(kubectl config current-context)"
  cluster_name="$(kubectl config view -o "jsonpath={.contexts[?(@.name==\"${current_context}\")].context.cluster}")"

  test -n "${cluster_name}" || {
    echo "Could not find the kubeconfig cluster for context ${current_context}." >&2
    exit 1
  }

  if [ -n "${KUBE_API_SERVER_URL:-}" ]; then
    kubectl config set-cluster "${cluster_name}" --server="${KUBE_API_SERVER_URL}" >/dev/null
  fi

  if [ -n "${KUBE_TLS_SERVER_NAME:-}" ]; then
    kubectl config set-cluster "${cluster_name}" --tls-server-name="${KUBE_TLS_SERVER_NAME}" >/dev/null
  fi
fi
