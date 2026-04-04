#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <terragrunt-unit-path> <lock-id>" >&2
  exit 1
fi

unit_path="$1"
lock_id="$2"

if [[ ! -d "$unit_path" ]]; then
  echo "terragrunt unit not found: $unit_path" >&2
  exit 1
fi

TG_TF_PATH="${TG_TF_PATH:-tofu}" terragrunt --working-dir "$unit_path" force-unlock -force "$lock_id"
