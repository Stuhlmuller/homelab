# Terragrunt Unit Catalog

This directory stores the committed Terragrunt unit templates used by
`../terragrunt.stack.hcl`.

Run stack generation from `IaC/` before validating or applying units:

```sh
terragrunt stack generate
```

Generated unit files are written back to their historical paths under
`IaC/bootstrap`, `IaC/live`, and `IaC/operator` so existing backend state keys
stay unchanged. Edit the templates here, not the generated `terragrunt.hcl`
files in those live paths.

Argo CD Applications share `units/live/argocd-app`. Per-app dependencies and
sparse `metadata`/`spec` overrides live in `../terragrunt.stack.hcl` unit
`values`; common inputs live in `local.argocd_defaults`. The template constructs
the raw Application manifest. See the
[onboarding example](../../docs/argocd-app-onboarding.md#register-with-shared-defaults)
and [chart organization decision](../../docs/knowledge-base/patterns/helm-chart-organization.md).

The catalog's `terragrunt.values.hcl` is only a shape fixture for HCL validation.
Stack generation replaces it with the real values. Never add production
defaults there or edit generated live files.
