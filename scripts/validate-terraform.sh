#!/usr/bin/env bash
set -euo pipefail

tofu fmt -check -recursive terraform >/dev/null
terragrunt hcl fmt --check --working-dir terraform/live/homelab >/dev/null

find terraform/modules -name '*.tf' -print0 | xargs -0 -n1 dirname | sort -u | while read -r module_dir; do
  tofu -chdir="$module_dir" init -backend=false -input=false >/dev/null
  tofu -chdir="$module_dir" validate >/dev/null
done
