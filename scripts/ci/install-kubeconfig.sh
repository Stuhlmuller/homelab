#!/usr/bin/env bash
set -euo pipefail

: "${KUBE_API_SERVER_URL:?KUBE_API_SERVER_URL must contain the public Octelium Kubernetes URL}"
: "${OCTELIUM_AUTH_TOKEN:?OCTELIUM_AUTH_TOKEN must contain the Octelium clientless access token}"

install -m 0700 -d "$HOME/.kube"
kubectl config set-cluster homelab-ci --server="$KUBE_API_SERVER_URL" >/dev/null
kubectl config set-credentials homelab-ci --token="$OCTELIUM_AUTH_TOKEN" >/dev/null
kubectl config set-context homelab-ci --cluster=homelab-ci --user=homelab-ci >/dev/null
kubectl config use-context homelab-ci >/dev/null
chmod 0600 "$HOME/.kube/config"
