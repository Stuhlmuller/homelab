#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 && "${1:-}" == --tailscale && "${GITHUB_ACTIONS:-}" == true ]] || {
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
