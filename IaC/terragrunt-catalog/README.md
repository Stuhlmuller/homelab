# Terragrunt catalog

`modules/` contains local OpenTofu modules. `units/` contains Terragrunt templates.
Run `terragrunt stack generate` from `IaC/` after changing templates or app inputs.
Generated unit paths stay under `bootstrap/`, `live/`, and `operator/` because they determine existing state keys.
