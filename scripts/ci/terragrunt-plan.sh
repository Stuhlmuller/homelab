#!/usr/bin/env bash
set -euo pipefail

echo "::group::Argo CD bootstrap plan"
(
  cd IaC/bootstrap/argocd
  terragrunt --log-disable plan -no-color
)
echo "::endgroup::"

echo "::group::AWS SSM parameter declaration plan"
(
  cd IaC/live/aws-ssm-parameters
  terragrunt --log-disable plan -no-color
)
echo "::endgroup::"

echo "::group::Argo CD Application registration plan"
(
  cd IaC/live/argocd-apps
  terragrunt run --all plan -no-color
)
echo "::endgroup::"

echo "IaC/live/kubernetes-secrets is intentionally excluded from PR plans because it reads decrypted SSM parameters."
