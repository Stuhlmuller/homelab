---
type: pattern
title: "New Terragrunt Unit Pattern"
description: "Explicit Terragrunt stack registration, shared templates, historical state paths, committed inputs, and unit validation."
tags: ["pattern", "terragrunt", "opentofu"]
---

# New Terragrunt Unit Pattern

Use this checklist before adding or changing a Terragrunt unit.

## Read First

- `.agents/skills/terragrunt-workflows/SKILL.md`
- [GitOps Flow](../architecture/gitops-flow.md)
- [Validation Gates](../operations/validation-gates.md)
- Nearby peer units in the same stack
- `IaC/root.hcl`

## Implementation Shape

1. Reuse an existing template under `IaC/terragrunt-catalog/units/...`, or add the
   smallest new one when the existing templates do not fit. Argo CD workloads
   and platform services share `live/argocd-app`; common inputs belong in the
   shared `IaC/stack-defaults.hcl`, with per-app inputs in
   `IaC/homelab/us-west-2/apps/<app>/stack.hcl`.
2. Register the unit in `IaC/homelab/us-west-2/apps/<app>/terragrunt.stack.hcl` with an app-local output
   path and `no_dot_terragrunt_stack = true`. For Applications, load the app
   file's `inputs` with `read_terragrunt_config` as the unit's `values`. Keep
   `source` and `path` literal so CI can identify units across revisions.
   `IaC/root.hcl` maps each generated path to its existing backend key.
3. Run `terragrunt stack generate` from `IaC/` before focused validation.
4. Include the root config used by nearby units.
5. Use a local module or pinned catalog module source.
6. Keep module inputs explicit in HCL or committed non-secret data.
7. Do not introduce `get_env`, `TF_VAR_*`, shell-exported values, or hidden
   environment-derived desired state for normal inputs.
8. Use `dependencies` for registration ordering when outputs are not needed.
9. Use `dependency` blocks only when the unit must consume another unit's
   outputs.
10. Format and validate the smallest affected scope before planning or applying.

The repository-local Application module fixes its API-owned computed fields:
metadata annotations/labels, destination name, and qualifying multi-source
chart/ref/directory paths. Callers supply the manifest, with no unused computed
field override. The SSM-backed Kubernetes Secret module likewise fixes `Opaque`
and rejects empty or `REPLACE_ME` values; ephemeral reads, write-only data and
the caller's rotation revision remain unchanged. See the
[Application module](../../IaC/terragrunt-catalog/modules/argocd-application-kubernetes/main.tf)
and [Secret module](../../IaC/terragrunt-catalog/modules/kubernetes-secret-from-ssm/main.tf).
The native HCL regression `scripts/ci/argocd-computed-fields-test.py` covers
omitted, null, dot and explicit source paths. Use explicit null comparisons:
OpenTofu's `contains` rejects a null search value, even in a list containing null.

## Knowledge-Base Update

Update [GitOps Flow](../architecture/gitops-flow.md) and [Validation Gates](../operations/validation-gates.md) when the
unit changes workflow, bootstrap behavior, module ownership, validation, or
dependency structure.

## State identity for additional units

Application units ending in `/argocd` retain their historical Application state
keys. Existing identity and storage units retain explicit legacy mappings in
`IaC/root.hcl`. Additional app-local units use their full relative path as the
state identity, so a new sibling cannot inherit the Application's state.
The stack regression renders both units and checks their distinct backend keys.

App identity inputs live beside each app stack in `identity.hcl` (and Fleet's
`pilot-user.hcl`). Catalog units consume generated values. The local
`azuread-oidc-application` module owns the shared registration, SSO password,
owner lookup and parameter resources at their existing root resource addresses.

Langfuse blob-storage inputs live beside its stack in
[`blob-storage.hcl`](../../IaC/homelab/us-west-2/apps/langfuse/blob-storage.hcl)
and reach the catalog template through unit `values`.

After generation, run `terragrunt find --filter 'type=unit'` with
`--working-dir IaC/homelab/us-west-2` to discover live units
without including catalog templates.

Account metadata comes from the nearest `account.hcl`; deployment region comes
from the nearest `region.hcl`. The root retains the historical Homelab fallback
for legacy destroy/recovery paths outside that hierarchy. Backend location and
state encryption remain independent of the deployment region. Only units whose
modules consume AWS region or tags pass those inputs; state encryption stays shared.

Application dependency entries are paths relative to the generated unit, such as
`../../cert-manager/argocd`, `../../../shared/aws-ssm-parameters`, or
`../blob-storage`. The template joins these paths without interpreting app names.

The [local catalog guide](https://github.com/Stuhlmuller/homelab/blob/3b2256219bcc0cb70596a94fc17e66491e284a9f/IaC/terragrunt-catalog/README.md) maps module,
template and live-input ownership with existing examples. Catalog discovery
includes both the local catalog and the external repository.

## Module File Organization

Local modules keep input declarations in `variables.tf`, outputs in `outputs.tf`
and provider requirements in `versions.tf`. State encryption belongs to the shared
Terragrunt root, which generates the compatible backend policy.
Larger modules separate publisher IAM, reader IAM and credential publication
into responsibility-specific files within the same module directory.
The owning Terragrunt stacks show how each module is used.
These file boundaries preserve resource addresses and the historical backend
key mappings in `IaC/root.hcl`.

Backend derivation uses named locals in `IaC/root.hcl` for unit prefixes,
legacy application exceptions, regional/shared fallback paths and the final
state key. `SharedAppTemplateTest.test_backend_state_mapping_compatibility`
renders representative callers to protect those historical mappings.
