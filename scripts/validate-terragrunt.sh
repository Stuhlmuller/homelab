#!/usr/bin/env bash
set -euo pipefail

if ! command -v terragrunt >/dev/null 2>&1; then
  echo "terragrunt is required for Terragrunt validation" >&2
  exit 1
fi

terragrunt hcl fmt --check --diff --working-dir terraform/live/homelab
