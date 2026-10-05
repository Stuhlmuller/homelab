# New Terragrunt Unit Pattern

Tags: #pattern #terragrunt #opentofu

Use this checklist before adding or changing a Terragrunt unit.

## Read First

- `.agents/skills/terragrunt-workflows/SKILL.md`
- [[architecture/gitops-flow]]
- [[operations/validation-gates]]
- Nearby peer units in the same stack
- `IaC/root.hcl`

## Implementation Shape

1. Reuse an existing template under `IaC/.catalog/units/...`, or add the
   smallest new one when the existing templates do not fit. Argo CD workloads
   and platform services share `live/argocd-app`; common inputs belong in the
   shared `IaC/stack-defaults.hcl`, with per-app inputs in
   `IaC/stacks/<app>/stack.hcl`.
2. Register the unit in `IaC/terragrunt.stack.hcl` with its historical live
   path and `no_dot_terragrunt_stack = true`. For Applications, load the app
   file's `inputs` with `read_terragrunt_config` as the unit's `values`. Keep
   `source` and `path` literal so CI can identify units across revisions.
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

## Knowledge-Base Update

Update [[architecture/gitops-flow]] and [[operations/validation-gates]] when the
unit changes workflow, bootstrap behavior, module ownership, validation, or
dependency structure.
