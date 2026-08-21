#!/usr/bin/env bash
set -euo pipefail

: "${KUBE_API_SERVER_URL:?KUBE_API_SERVER_URL must contain the public Octelium Kubernetes URL}"
: "${OCTELIUM_AUTH_TOKEN:?OCTELIUM_AUTH_TOKEN must contain the Octelium clientless access token}"
OCTELIUM_DOMAIN="${OCTELIUM_DOMAIN:-stinkyboi.com}"
export OCTELIUM_DOMAIN

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"${script_dir}/install-kubeconfig.sh"
if kubectl --request-timeout=15s version; then
  exit 0
fi

echo "::warning::Kubernetes clientless endpoint check failed; falling back to Octelium CLI publish."
"${script_dir}/install-octelium-client.sh"
"${script_dir}/connect-octelium.sh"

export KUBE_API_SERVER_URL="https://${OCTELIUM_KUBE_LOCAL_HOST:-127.0.0.1}:${OCTELIUM_KUBE_LOCAL_PORT:-16443}"
export KUBE_TLS_SERVER_NAME="${KUBE_TLS_SERVER_NAME:-10.1.0.199}"
"${script_dir}/install-kubeconfig.sh"
kubectl --request-timeout=15s version
