# kubernetes-secret-from-ssm

Ephemeral SSM reads and write-only Opaque Kubernetes Secret data. Increment data_revision after rotating source values.

## Interface

See [variables.tf](variables.tf) for input types, defaults and validation.

This module exposes no outputs.

## Usage

These repository callers provide complete input and provider wiring examples. Plan and apply through their declared Terragrunt stack.

- [live/kubernetes-secrets/external-secrets-aws-ssm-auth](../../units/live/kubernetes-secrets/external-secrets-aws-ssm-auth/terragrunt.hcl)

## State

Keep the module directory, resource labels and caller unit paths stable. Moving declarations between files in this directory preserves addresses. Backend keys are owned by [root.hcl](../../../root.hcl).
