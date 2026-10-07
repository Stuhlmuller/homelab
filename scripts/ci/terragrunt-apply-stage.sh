#!/usr/bin/env bash
set -euo pipefail

phase=nix
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
  '::group::Kubeconfig setup') phase=kubeconfig ;;
  '::group::Kubernetes API check') phase=api ;;
  '::group::Terragrunt apply') phase=terragrunt ;;
  '::group::Targeted Argo CD apply prerequisites') phase=target-prerequisites ;;
  '::group::Targeted Argo CD Application state repair') phase=state-repair ;;
  '::group::Targeted Argo CD Application registration apply') phase=target-registration ;;
  '::group::Deleted Terragrunt unit state destroy: '*) phase=retired-units ;;
  '::group::Argo CD bootstrap apply') phase=bootstrap ;;
  '::group::AWS SSM parameter declaration plan and apply') phase=ssm ;;
  '::group::Langfuse blob storage plan and apply') phase=langfuse ;;
  '::group::Kubernetes node label apply') phase=node-labels ;;
  '::group::AzureAD application registration apply') phase=azuread ;;
  '::group::Argo CD Application registration apply') phase=argocd-apps ;;
  '::group::External Secrets AWS auth Secret state adoption') phase=external-secrets ;;
  '::group::Kubernetes secret materialization apply') phase=kubernetes-secrets ;;
  esac
done

printf 'Production apply last recognized phase: %s; details withheld.\n' "$phase"
