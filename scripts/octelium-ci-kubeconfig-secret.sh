#!/usr/bin/env bash
set -euo pipefail

domain="stinkyboi.com"
secret_name="homelab-ci-kubeconfig"
kubeconfig=""

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-ci-kubeconfig-secret.sh --kubeconfig PATH [options]

Store a Kubernetes kubeconfig in Octelium for the clientless CI Kubernetes
Service. The kubeconfig stays outside git and is reconciled through the
authenticated Octelium admin API.

Options:
  --kubeconfig PATH   Source kubeconfig file (required).
  --domain DOMAIN     Octelium Cluster domain. Default: stinkyboi.com
  --secret-name NAME  Octelium Secret name. Default: homelab-ci-kubeconfig
  -h, --help          Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kubeconfig) kubeconfig="$2"; shift 2 ;;
    --domain) domain="$2"; shift 2 ;;
    --secret-name) secret_name="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$kubeconfig" && -f "$kubeconfig" ]] || { echo "error: --kubeconfig must name a readable file" >&2; exit 1; }
command -v octeliumctl >/dev/null || { echo "error: octeliumctl is required" >&2; exit 127; }

if octeliumctl get secret "$secret_name" --domain "$domain" >/dev/null 2>&1; then
  octeliumctl delete secret "$secret_name" --domain "$domain" >/dev/null
fi
octeliumctl create secret "$secret_name" --domain "$domain" --file "$kubeconfig" >/dev/null
echo "Reconciled Octelium secret ${secret_name}."
