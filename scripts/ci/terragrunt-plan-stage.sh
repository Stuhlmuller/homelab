#!/usr/bin/env bash
set -euo pipefail

stage=nix
reason=unknown
azuread_unit=""

azuread_report_unit() {
  local report_path="${HOMELAB_AZUREAD_PLAN_REPORT_FILE:-}"

  [[ -n "$report_path" && -f "$report_path" && ! -L "$report_path" ]] || return 0
  python3 -I - "$report_path" 2>/dev/null <<'PY' || true
import json
import os
import sys

allowed = {"fleet", "fleet-pilot-user", "grafana", "octelium"}
try:
    if os.path.getsize(sys.argv[1]) > 1048576:
        raise ValueError
    with open(sys.argv[1], "rb") as report:
        records = json.load(report)
    failed = [record.get("Name") for record in records if isinstance(record, dict)
              and record.get("Name") in allowed and record.get("Result") == "failed"]
    if failed:
        print(failed[0])
except (OSError, ValueError, json.JSONDecodeError):
    pass
PY
}

while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
  '::group::Kubeconfig setup') stage=kubeconfig ;;
  '::group::Kubernetes API check') stage=api ;;
  '::group::Argo CD bootstrap plan') stage=bootstrap ;;
  '::group::Argo CD Application registration plan') stage=app ;;
  '::group::AzureAD application registration plan') stage=azuread ;;
  '::group::Terraform plan Conftest policies') stage=policy ;;
  esac
  # Match known fragments, never print captured text. This is a hint, not a cause.
  [[ "$reason" == unknown ]] || continue
  case "$stage:$line" in
  azuread:*Authorization_RequestDenied* | \
    azuread:*'Insufficient privileges to complete the operation'*) reason=entra-authorization ;;
  azuread:*InvalidAuthenticationToken* | azuread:*AADSTS*) reason=entra-authentication ;;
  azuread:*Request_ResourceNotFound* | azuread:*'404 Not Found'*) reason=entra-resource-not-found ;;
  azuread:*TooManyRequests* | azuread:*'429 Too Many Requests'*) reason=entra-throttled ;;
  *AccessDenied* | *ExpiredToken* | *InvalidClientTokenId*) reason=aws-auth ;;
  *'the server has asked for the client to provide credentials'* | \
    *'Error from server (Unauthorized)'* | *'Error from server (Forbidden)'*) reason=kubernetes-auth ;;
  *'TLS handshake timeout'* | *'i/o timeout'* | *'context deadline exceeded'* | \
    *'connection refused'*) reason=network ;;
  *'Plugin did not respond'* | *'Failed to load plugin schemas'* | \
    *'Failed to query available provider packages'* | *'Failed to install provider'*) reason=provider ;;
  policy:*'::error file='*) reason=policy ;;
  esac
done
printf 'Live plan last recognized stage: %s; details withheld.\n' "$stage"
printf 'Live plan failure hint: %s; details withheld.\n' "$reason"
if [[ "$stage" == azuread ]]; then
  azuread_unit="$(azuread_report_unit)"
  if [[ -n "$azuread_unit" ]]; then
    printf 'Live plan first failed AzureAD unit: %s; details withheld.\n' "$azuread_unit"
  fi
fi
