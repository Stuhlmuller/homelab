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
