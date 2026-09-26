#!/usr/bin/env bash
set -euo pipefail

stage=nix
reason=unknown
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
