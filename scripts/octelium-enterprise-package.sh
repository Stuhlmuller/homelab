#!/usr/bin/env bash
set -euo pipefail

DEFAULT_DOMAIN="octelium.stinkyboi.com"
DEFAULT_VERSION="0.22.0"
PACKAGE="octeliumee"

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-enterprise-package.sh [options]

Install or upgrade the Octelium Enterprise package in an already running
Octelium Cluster.

Options:
  --domain DOMAIN       Octelium Cluster domain. Default: octelium.stinkyboi.com
  --version VERSION     Package version to install. Default: 0.22.0
                        Use "latest" to omit --version.
  --upgrade             Upgrade an existing enterprise package installation.
  --kubeconfig PATH     Kubeconfig for the Octelium Cluster.
  -h, --help            Show this help text.

Requirements:
  - octops v0.29.0 or later
  - kubeconfig access to the Octelium Cluster control plane
USAGE
}

domain="${DEFAULT_DOMAIN}"
version="${DEFAULT_VERSION}"
upgrade=false
kubeconfig=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      if [[ $# -lt 2 ]]; then
        echo "error: --domain requires a value" >&2
        exit 2
      fi
      domain="$2"
      shift 2
      ;;
    --version)
      if [[ $# -lt 2 ]]; then
        echo "error: --version requires a value" >&2
        exit 2
      fi
      version="$2"
      shift 2
      ;;
    --upgrade)
      upgrade=true
      shift
      ;;
    --kubeconfig)
      if [[ $# -lt 2 ]]; then
        echo "error: --kubeconfig requires a value" >&2
        exit 2
      fi
      kubeconfig="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v octops >/dev/null 2>&1; then
  echo "error: octops is required; install octops v0.29.0 or later first." >&2
  exit 127
fi

cmd=(octops install-package "${domain}" --package "${PACKAGE}")

if [[ "${version}" != "latest" ]]; then
  cmd+=(--version "${version}")
fi

if [[ "${upgrade}" == "true" ]]; then
  cmd+=(--upgrade)
fi

if [[ -n "${kubeconfig}" ]]; then
  cmd+=(--kubeconfig "${kubeconfig}")
fi

printf 'Running:'
printf ' %q' "${cmd[@]}"
printf '\n'

exec "${cmd[@]}"
