# aws-backup-bucket

Private versioned backup bucket and optional prefix-scoped GitHub OIDC publisher. Bucket destruction is protected.

## Interface

See [variables.tf](variables.tf) for input types, defaults and validation.

See [outputs.tf](outputs.tf) for `bucket_name`, `bucket_arn`, `region`, `publisher_role_arn`.

## Usage

These repository callers provide complete input and provider wiring examples. Plan and apply through their declared Terragrunt stack.

- [operator/etcd-backup-storage](../../units/operator/etcd-backup-storage/terragrunt.hcl)
- [operator/application-backup-storage](../../units/operator/application-backup-storage/terragrunt.hcl)

## State

Keep the module directory, resource labels and caller unit paths stable. Moving declarations between files in this directory preserves addresses. Backend keys are owned by [root.hcl](../../../root.hcl).
