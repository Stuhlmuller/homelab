#!/usr/bin/env bash
set -euo pipefail

command_name="${1:?usage: scripts/ci/live-terragrunt.sh plan|apply}"

case "$command_name" in
  plan | apply) ;;
  *)
    echo "usage: scripts/ci/live-terragrunt.sh plan|apply" >&2
    exit 2
    ;;
esac

cleanup() {
  bash scripts/ci/disconnect-octelium.sh
}
trap cleanup EXIT

bash scripts/ci/connect-octelium.sh
bash scripts/ci/install-kubeconfig.sh
curl -ksS --max-time 10 -o /dev/null "${KUBE_API_SERVER_URL:?KUBE_API_SERVER_URL is required}/version"
kubectl --request-timeout=15s version
bash "scripts/ci/terragrunt-${command_name}.sh"
