#!/usr/bin/env bash
set -euo pipefail

phase=nix
hint=unknown
while IFS= read -r line || [[ -n "$line" ]]; do
  next_phase=""
  case "$line" in
  '::group::Kubeconfig setup') next_phase=kubeconfig ;;
  '::group::Kubernetes API check') next_phase=api ;;
  '::group::Terragrunt apply') next_phase=terragrunt ;;
  '::group::Targeted Argo CD apply prerequisites') next_phase=target-prerequisites ;;
  '::group::Targeted Argo CD Application state repair') next_phase=state-repair ;;
  '::group::Targeted Argo CD Application registration apply') next_phase=target-registration ;;
  '::group::Deleted Terragrunt unit state destroy: '*) next_phase=retired-units ;;
  '::group::OpenClaw legacy offsite bucket plan and apply') next_phase=backup-storage ;;
  '::group::Argo CD bootstrap apply') next_phase=bootstrap ;;
  '::group::AWS SSM parameter declaration plan and apply') next_phase=ssm ;;
  '::group::Langfuse blob storage plan and apply') next_phase=langfuse ;;
  '::group::Kubernetes node label apply') next_phase=node-labels ;;
  '::group::AzureAD application registration apply') next_phase=azuread ;;
  '::group::Argo CD Application registration apply') next_phase=argocd-apps ;;
  '::group::External Secrets AWS auth Secret state adoption') next_phase=external-secrets ;;
  '::group::Kubernetes secret materialization apply') next_phase=kubernetes-secrets ;;
  esac
  if [[ -n "$next_phase" ]]; then
    phase="$next_phase"
    hint=unknown
    continue
  fi

  # Classify only into fixed labels; never echo captured output. A matching
  # fragment is a diagnostic hint, not proof of the failure's root cause.
  [[ "$hint" == unknown ]] || continue
  case "$line" in
  *AccessDenied* | *ExpiredToken* | *InvalidClientTokenId*) hint=aws-auth ;;
  *'the server has asked for the client to provide credentials'* | \
    *'Error from server (Unauthorized)'* | *'Error from server (Forbidden)'*) hint=kubernetes-auth ;;
  *Authorization_RequestDenied* | *InvalidAuthenticationToken* | *AADSTS*) hint=entra-auth ;;
  *'TLS handshake timeout'* | *'i/o timeout'* | *'context deadline exceeded'* | \
    *'connection refused'*) hint=network ;;
  *'Plugin did not respond'* | *'Failed to load plugin schemas'* | \
    *'Failed to query available provider packages'* | *'Failed to install provider'*) hint=provider ;;
  *'Error downloading modules'* | *'Failed to download module'*) hint=module-download ;;
  *'Error acquiring the state lock'*) hint=state-lock ;;
  *'another operation (install/upgrade/rollback) is in progress'* | \
    *'cannot re-use a name that is still in use'*) hint=helm-operation ;;
  *'Main advanced after dispatch; refusing to change live state.'* | \
    *'Unable to verify current main; refusing to change live state.'* | \
    *'Invalid production commit context; refusing to change live state.'*) hint=source-guard ;;
  *'::error file='*) hint=policy ;;
  esac
done

printf 'Production apply last recognized phase: %s; details withheld.\n' "$phase"
printf 'Production apply failure hint: %s; details withheld.\n' "$hint"
