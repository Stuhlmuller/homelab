#!/usr/bin/env bash
set -euo pipefail

echo "::group::Argo CD bootstrap apply"
(
  cd IaC/bootstrap/argocd
  terragrunt --log-disable apply -no-color -auto-approve
)
echo "::endgroup::"

echo "::group::AWS SSM parameter declaration apply"
(
  cd IaC/live/aws-ssm-parameters
  terragrunt --log-disable apply -no-color -auto-approve
)
echo "::endgroup::"

echo "::group::AzureAD application registration apply"
(
  cd IaC/live/azuread-applications
  terragrunt run --all --parallelism 1 --source-update apply -no-color -auto-approve
)
echo "::endgroup::"

echo "::group::Argo CD Application registration apply"
(
  cd IaC/live/argocd-apps
  terragrunt run --all --parallelism 1 --source-update apply -no-color -auto-approve
)
echo "::endgroup::"

echo "::group::Kubernetes secret materialization apply"
(
  cd IaC/live/kubernetes-secrets
  terragrunt run --all --parallelism 1 --source-update apply -no-color -auto-approve
)
echo "::endgroup::"
