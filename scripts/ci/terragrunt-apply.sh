#!/usr/bin/env bash
set -euo pipefail

echo "::group::Argo CD bootstrap apply"
(
  cd IaC/bootstrap/argocd
  terragrunt --log-disable apply -no-color -auto-approve
)
echo "::endgroup::"

echo "::group::Live stack apply"
(
  cd IaC/live
  terragrunt run --all apply -no-color -auto-approve
)
echo "::endgroup::"
