# Terragrunt catalog

The root catalog configuration lists this local catalog alongside the external
catalog. Browse from a generated unit with `terragrunt catalog`. Local modules
and templates track the reviewed Homelab commit; external module references use
immutable commits.

## Ownership and examples

| Concern | Owner | Existing example |
| --- | --- | --- |
| Reusable resources and typed inputs | `modules/<module>/` | `modules/azuread-oidc-application/` |
| Shared generated-unit behavior | `units/<group>/<template>/` | `units/live/argocd-app/` |
| Unit source, identity and output path | Live `terragrunt.stack.hcl` | `../../homelab/us-west-2/apps/grafana/terragrunt.stack.hcl` |
| Deployment-specific inputs | Live app HCL | `../../homelab/us-west-2/apps/grafana/identity.hcl` |
| Common Application defaults | `../../stack-defaults.hcl` | `argocd_defaults` |
| Account metadata and region | Ancestor `account.hcl` and `region.hcl` | `../../homelab/account.hcl` |

Use a neighboring live stack as the instance example, select an existing template,
and supply its values from the adjacent HCL file. Preserve literal source and path
fields so CI can discover additions and retirements. A reusable stack template is
appropriate when an entire composition repeats.

Run from the repository root after changing templates or live inputs.

```sh
terragrunt --working-dir IaC stack generate
terragrunt hcl validate
python3 scripts/ci/terragrunt-stack-test.py
```

Generated units live under `IaC/homelab/us-west-2/`. Their historical backend
keys are preserved by `IaC/root.hcl`. Catalog `terragrunt.values.hcl` files are
validation fixtures; generation replaces them with live inputs.

Account tags merge before unit-specific tags. Application labels merge before
instance labels. Preserve existing names, selectors, and backend mappings when
reorganizing files. Verify the affected rendered configuration and plan.
