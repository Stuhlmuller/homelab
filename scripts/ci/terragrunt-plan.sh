#!/usr/bin/env bash
set -euo pipefail

echo "::group::Argo CD bootstrap plan"
(
  cd IaC/bootstrap/argocd
  terragrunt --log-disable plan -no-color
)
echo "::endgroup::"

echo "IaC/live/aws-ssm-parameters is intentionally excluded from PR plans because it manages KMS, IAM, and secret declarations that require the protected production apply role."

echo "::group::Argo CD Application registration plan"
(
  cd IaC/live/argocd-apps
  terragrunt run --all --parallelism 1 --source-update plan -no-color
)
echo "::endgroup::"

echo "IaC/live/kubernetes-secrets is intentionally excluded from PR plans because it reads decrypted SSM parameters."
