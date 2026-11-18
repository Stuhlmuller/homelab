# aws-github-actions-role-policy

Policy for an existing GitHub Actions apply role and the External Secrets permissions boundary.

## Interface

See [variables.tf](variables.tf) for input types, defaults and validation.

See [outputs.tf](outputs.tf) for `policy_arn`, `external_secrets_boundary_policy_arn`.

## Usage

These repository callers provide complete input and provider wiring examples. Plan and apply through their declared Terragrunt stack.

- [operator/github-actions-role-policy](../../units/operator/github-actions-role-policy/terragrunt.hcl)

## State

Keep the module directory, resource labels and caller unit paths stable. Moving declarations between files in this directory preserves addresses. Backend keys are owned by [root.hcl](../../../root.hcl).
