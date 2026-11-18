# aws-ssm-parameters

Runtime SSM parameters, generated secret material and IAM reader permissions.

## Interface

See [variables.tf](variables.tf) for input types, defaults and validation.

This module exposes no outputs.

## Usage

These repository callers provide complete input and provider wiring examples. Plan and apply through their declared Terragrunt stack.

- [live/aws-ssm-parameters](../../units/live/aws-ssm-parameters/terragrunt.hcl)

## State

Keep the module directory, resource labels and caller unit paths stable. Moving declarations between files in this directory preserves addresses. Backend keys are owned by [root.hcl](../../../root.hcl).
