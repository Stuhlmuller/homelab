# kubernetes-node-labels

Selected labels, annotations and taints on existing nodes. State and plan encryption come from the shared [Terragrunt root](../../../root.hcl); this module has no encryption-only inputs. See the [encryption guide](../../../../docs/state-encryption.md).

## Interface

See [variables.tf](variables.tf) for input types, defaults and validation.

This module exposes no outputs.

## Usage

These repository callers provide complete input and provider wiring examples. Plan and apply through their declared Terragrunt stack.

- [live/kubernetes-node-labels](../../units/live/kubernetes-node-labels/terragrunt.hcl)

## State

Keep the module directory, resource labels and caller unit paths stable. Moving declarations between files in this directory preserves addresses. Backend keys are owned by [root.hcl](../../../root.hcl).
