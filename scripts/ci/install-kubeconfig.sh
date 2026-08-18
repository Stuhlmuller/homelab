#!/usr/bin/env bash
set -euo pipefail

install -m 0700 -d "$HOME/.kube"

if [ -n "${KUBE_CONFIG_B64:-}" ]; then
  printf '%s' "$KUBE_CONFIG_B64" | base64 --decode >"$HOME/.kube/config"

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
else
  : "${KUBE_API_SERVER_URL:?KUBE_API_SERVER_URL must contain the public Octelium Kubernetes URL}"
  : "${OCTELIUM_AUTH_TOKEN:?OCTELIUM_AUTH_TOKEN must contain the Octelium clientless access token}"

  kubectl config set-cluster homelab-ci --server="$KUBE_API_SERVER_URL" >/dev/null
  kubectl config set-credentials homelab-ci --token="$OCTELIUM_AUTH_TOKEN" >/dev/null
  kubectl config set-context homelab-ci --cluster=homelab-ci --user=homelab-ci >/dev/null
  kubectl config use-context homelab-ci >/dev/null
fi

chmod 0600 "$HOME/.kube/config"
