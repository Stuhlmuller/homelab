# kubernetes-node-labels

Selected labels, annotations and taints on existing nodes. State encryption uses the caller’s AWS KMS key.

## Interface

See [variables.tf](variables.tf) for input types, defaults and validation.

This module exposes no outputs.

## Usage

These repository callers provide complete input and provider wiring examples. Plan and apply through their declared Terragrunt stack.

- [live/kubernetes-node-labels](../../units/live/kubernetes-node-labels/terragrunt.hcl)

## State

Keep the module directory, resource labels and caller unit paths stable. Moving declarations between files in this directory preserves addresses. Backend keys are owned by [root.hcl](../../../root.hcl).
