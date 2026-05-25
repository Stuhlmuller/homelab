#!/usr/bin/env bash
set -euo pipefail

: "${KUBE_CONFIG_B64:?KUBE_CONFIG_B64 must contain the base64-encoded kubeconfig}"

install -m 0700 -d "$HOME/.kube"
printf '%s' "$KUBE_CONFIG_B64" | base64 --decode >"$HOME/.kube/config"
chmod 0600 "$HOME/.kube/config"
