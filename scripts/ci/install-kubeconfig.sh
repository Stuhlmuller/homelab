#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == --tailscale ]]; then
  [[ $# -eq 1 && "${GITHUB_ACTIONS:-}" == true ]] || {
    echo 'Tailscale kubeconfig setup requires an ephemeral GitHub Actions runner.' >&2
    exit 1
  }
  [[ ! -e "$HOME/.kube/config" ]] || {
    echo 'Refusing to replace an existing runner kubeconfig.' >&2
    exit 1
  }
  umask 077
  install -m 0700 -d "$HOME/.kube"
  kubectl config set-cluster homelab-ci \
    --server=https://homelab-tailscale-operator.tail67beb.ts.net >/dev/null
  kubectl config set-credentials homelab-ci >/dev/null
  kubectl config set-context homelab-ci --cluster=homelab-ci --user=homelab-ci >/dev/null
  kubectl config use-context homelab-ci >/dev/null
  chmod 0600 "$HOME/.kube/config"
  exit 0
fi
[[ $# -eq 0 ]] || { echo 'Usage: install-kubeconfig.sh [--tailscale]' >&2; exit 2; }

# Retained until the protected CI transport cutover is accepted.
: "${KUBE_API_SERVER_URL:?KUBE_API_SERVER_URL must contain the public Octelium Kubernetes URL}"
: "${OCTELIUM_AUTH_TOKEN:?OCTELIUM_AUTH_TOKEN must contain the Octelium clientless access token}"

install -m 0700 -d "$HOME/.kube"
kubectl config set-cluster homelab-ci --server="$KUBE_API_SERVER_URL" >/dev/null
kubectl config set-credentials homelab-ci --token="$OCTELIUM_AUTH_TOKEN" >/dev/null
kubectl config set-context homelab-ci --cluster=homelab-ci --user=homelab-ci >/dev/null
kubectl config use-context homelab-ci >/dev/null
chmod 0600 "$HOME/.kube/config"
