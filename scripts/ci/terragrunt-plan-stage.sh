#!/usr/bin/env bash
set -euo pipefail

stage=nix
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
  '::group::Kubeconfig setup') stage=kubeconfig ;;
  '::group::Kubernetes API check') stage=api ;;
  '::group::Argo CD bootstrap plan') stage=bootstrap ;;
  '::group::Argo CD Application registration plan') stage=app ;;
  '::group::AzureAD application registration plan') stage=azuread ;;
  '::group::Terraform plan Conftest policies') stage=policy ;;
  esac
done
printf 'Live plan last recognized stage: %s; details withheld.\n' "$stage"
