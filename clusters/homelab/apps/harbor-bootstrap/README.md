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

## Bootstrap controller dependencies

Once normal controller references are internal, recovering only Harbor's own
images is insufficient. Before an empty-cluster apply, include these inactive
values in the same reviewed temporary recovery change, after normal values:

| Application | Recovery values under this directory |
| --- | --- |
| cert-manager | `cert-manager-values.yaml` |
| external-secrets | `external-secrets-values.yaml` |
| traefik | `traefik-values.yaml` |
| each Istio Helm source | `istio-values.yaml` plus the corresponding `istio-pilot-values.yaml`, `istio-cni-values.yaml` or `istio-ztunnel-values.yaml` when that source deploys the component |

Use `$values/clusters/homelab/apps/harbor-bootstrap/<file>` in the owning
Application's `helm.valueFiles`. Preserve every normal value file and its order;
append the recovery override last. The root bootstrap Argo CD release requires the recovery override below.
Flannel and Talos bootstrap images require the reviewed node mirror rollback.
No recovery file is registered in the normal stack.

These overrides let certificate issuance, ExternalSecret-backed Harbor
credentials and the node-facing registry route start before Harbor has content.
They change only repositories and retain cataloged digests. They contain no
credentials. Restore all normal source lists after verified publication and
private transport acceptance. The cold install/restore sequence remains
unproven; render acceptance cannot establish the documented single-apply path.

The Kustomize recovery overlay handles both the retained Python repository and
the staged Chainguard Python replacement. CI rejects any remaining Harbor image
in recovery workloads, so a later self-hosted image change must update this
profile before rollout. The full catalog coverage gate checks the preserved pins.

For the bootstrap Argo CD Helm release, append
`file("${get_repo_root()}/clusters/homelab/apps/harbor-bootstrap/argocd-values.yaml")`
after its normal `values` entry in a reviewed temporary change to
`IaC/.catalog/units/bootstrap/argocd/terragrunt.hcl`. This also restores Dex, Redis
and init/hook repositories while retaining normal digests and version labels.
The profile must be removed after Harbor availability is verified.
