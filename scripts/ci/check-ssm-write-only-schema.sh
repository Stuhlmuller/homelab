#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
module="$repo_root/IaC/modules/aws-ssm-parameters"
lock_file="$repo_root/IaC/live/aws-ssm-parameters/.terraform.lock.hcl"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/ssm-schema.XXXXXX")"
trap 'rm -rf "$work_dir"' EXIT

cp "$module"/*.tf "$lock_file" "$work_dir/"
tofu -chdir="$work_dir" init \
  -backend=false -lockfile=readonly -input=false -no-color >/dev/null
tofu -chdir="$work_dir" validate -no-color >/dev/null
tofu -chdir="$work_dir" providers schema -json | jq -e '
  .provider_schemas["registry.opentofu.org/hashicorp/aws"] as $aws
  | .provider_schemas["registry.opentofu.org/hashicorp/random"] as $random
  | .provider_schemas["registry.opentofu.org/hashicorp/tls"] as $tls
  | $aws.resource_schemas.aws_ssm_parameter.block.attributes.value_wo.write_only == true
  and $aws.resource_schemas.aws_ssm_parameter.block.attributes.value_wo.sensitive == true
  and $aws.resource_schemas.aws_ssm_parameter.block.attributes.value_wo_version.optional == true
  and $aws.ephemeral_resource_schemas.aws_ssm_parameter.block.attributes.arn.required == true
  and $aws.ephemeral_resource_schemas.aws_ssm_parameter.block.attributes.value.sensitive == true
  and $random.ephemeral_resource_schemas.random_password.block.attributes.result.sensitive == true
  and $tls.ephemeral_resource_schemas.tls_private_key.block.attributes.private_key_pem.sensitive == true
' >/dev/null

echo "SSM write-only provider schema checks passed"
