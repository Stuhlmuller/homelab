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
Application manifests live in `../terragrunt.stack.hcl` unit `values`.
