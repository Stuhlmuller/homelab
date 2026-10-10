# Harbor cold bootstrap

Recovery-only image overlays for an empty cluster or unavailable registry.
Normal Harbor sources use retained internal images; these overlays are not
registered in the steady-state Application.

Through a reviewed temporary recovery change to `IaC/stacks/harbor/stack.hcl`:

- Append `$values/clusters/homelab/apps/harbor-bootstrap/values.yaml` after the
  normal Harbor Helm values. This changes only the chart's image repositories.
- Change the repository Kustomize source path to
  `clusters/homelab/apps/harbor-bootstrap`. This restores upstream Python and
  PostgreSQL references without changing their pins, PVCs, scripts or credentials.
- Use the documented Talos mirror rollback before attempting upstream pulls.
  Keep recovery access, external secret material and the supported bootstrap
  prerequisites available; do not delete caches or data to manufacture a test.

Validate both paths before protected merge:

```sh
nix develop --command kubectl kustomize clusters/homelab/apps/harbor
nix develop --command kubectl kustomize clusters/homelab/apps/harbor-bootstrap
nix develop --command python3 -I scripts/ci/harbor-images-check.py
```

Apply the reviewed source change through the documented Terragrunt/Argo path.
After Harbor is Healthy, publish and completely download the reviewed catalog.
Remove both temporary source overrides through a second reviewed change,
verify internal image pulls, then restore strict Talos mirrors. Cold-bootstrap
acceptance remains required; successful rendering alone does not prove recovery.

See [image delivery](../../../../docs/harbor-image-mirroring.md) and
[application recovery](../../../../docs/application-recovery.md).
