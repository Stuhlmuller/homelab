# aws-langfuse-blob-storage

Langfuse bucket, IAM client and SecureString credential publication. Raw events expire after 30 days, noncurrent versions after seven days.

## Interface

See [variables.tf](variables.tf) for input types, defaults and validation.

See [outputs.tf](outputs.tf) for `bucket_name`, `region`.

## Usage

These repository callers provide complete input and provider wiring examples. Plan and apply through their declared Terragrunt stack.

- [live/langfuse-blob-storage](../../units/live/langfuse-blob-storage/terragrunt.hcl)

## State

Keep the module directory, resource labels and caller unit paths stable. Moving declarations between files in this directory preserves addresses. Backend keys are owned by [root.hcl](../../../root.hcl).
