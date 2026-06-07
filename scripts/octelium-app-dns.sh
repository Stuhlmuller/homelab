#!/usr/bin/env bash
set -euo pipefail

args=()

usage() {
  cat <<'USAGE'
Usage: scripts/octelium-app-dns.sh [options]

Compatibility wrapper for the former VPN-only Octelium app DNS helper.
App hostnames are now clientless Octelium WEB services and must be published as
proxied Cloudflare Tunnel CNAME records. This wrapper delegates to
scripts/octelium-public-dns.sh.

Options:
  --domain DOMAIN                 Octelium Cluster domain. Default: stinkyboi.com
  --zone NAME                     Cloudflare zone name. Default: stinkyboi.com
  --aws-region REGION             AWS region for SSM. Default: us-west-2
  --token-parameter NAME          SSM parameter containing the Cloudflare API token.
  --tunnel-id-parameter NAME      SSM parameter containing the Cloudflare Tunnel UUID.
  --gateway-service NAME          Ignored; retained for compatibility.
  --dry-run                       Print intended changes without writing Cloudflare DNS.
  -h, --help                      Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain|--zone|--aws-region|--token-parameter|--tunnel-id-parameter)
      args+=("$1" "$2")
      shift 2
      ;;
    --gateway-service)
      echo "warning: --gateway-service is ignored; app hostnames now use Cloudflare Tunnel CNAMEs" >&2
      shift 2
      ;;
    --dry-run)
      args+=("$1")
      shift
      ;;
    -h|--help)
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

echo "warning: scripts/octelium-app-dns.sh is deprecated; delegating to scripts/octelium-public-dns.sh" >&2
exec scripts/octelium-public-dns.sh "${args[@]}"
