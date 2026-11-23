# Kubernetes GitOps monorepo layout review

Keep the existing single-cluster layout and Terragrunt deployment roots. The
useful change would be to classify shared controllers consistently under
`platform/`. Start with cert-manager and External Secrets because their
cluster-wide contracts are consumed by multiple workloads. Leave larger
moves, including Istio and ingress, for separate reviews of their dependencies.

## Target structure

```text
.talos/                                  # Node configuration
IaC/
  terragrunt-catalog/{modules,units}/      # Reusable provisioning
  homelab/us-west-2/
    bootstrap/                            # Install Argo CD
    apps/<application>/                   # Render and register Applications
    shared/                               # Shared infrastructure units
    operator/                             # Separately operated infrastructure
clusters/homelab/
  argocd/self-management/                 # Argo CD configuration and projects
  platform/
    cert-manager/                         # Proposed move from apps/
    external-secrets/                     # Proposed move from apps/
    ...                                   # Storage, DNS, network policy, etc.
  apps/<workload>/                         # Workload manifests and Helm values
builds/                                   # Image build inputs
```

Register a new workload under `IaC/homelab/us-west-2/apps/` and place its
runtime source under `clusters/homelab/apps/`. A shared controller can keep
the same registration convention and explicitly point to `platform/`.
The reviewed version on `main` is the deployment intent. Add another cluster
root only when there is another independently reconciled cluster. Extract
shared bases or charts when two targets actually need them.

## Paths a future move would change

| Surface | Required updates for the two proposed moves |
| --- | --- |
| Argo CD | Update both the Kustomize source path and Helm `$values` paths in the [cert-manager stack](../IaC/homelab/us-west-2/apps/cert-manager/stack.hcl) and [External Secrets stack](../IaC/homelab/us-west-2/apps/external-secrets/stack.hcl). Retain Application names, projects, destinations, source order and revisions. The [self-management Application](../clusters/homelab/argocd/self-management/application.yaml) keeps its own source path. |
| Terragrunt | Edit the two authored `stack.hcl` inputs and regenerate from them. Keep the [default app source root](../IaC/stack-defaults.hcl) for conventional workloads and use the existing per-app source override. Keep unit directories and dependency paths because [backend keys](../IaC/root.hcl) depend on unit paths. Update the direct External Secrets namespace path in the [apply script](../scripts/ci/terragrunt-apply.sh) and [fixture](../scripts/ci/terragrunt-apply-test.py). |
| CI and policy | Add both new platform roots to the Kustomize render step in [validate.yml](../.github/workflows/validate.yml), which currently discovers app roots and names selected platform roots explicitly. Update the cert-manager values and expected source paths in [offline static checks](../scripts/ci/offline-checks.sh) and the path assertion in the [Enterprise foundation test](../scripts/ci/openclaw-enterprise-foundation-test.py) as applicable. The [Conftest input collector](../scripts/ci/conftest-policies.sh) already scans both trees. |

For any later expansion, check bootstrap manifest paths in the
[Argo CD unit](../IaC/terragrunt-catalog/units/bootstrap/argocd/terragrunt.hcl),
direct child sources such as [Cordium bootstrap](../clusters/homelab/apps/cordium/cordium-bootstrap-application.yaml),
and path consumers in [Terragrunt Plan](../.github/workflows/terragrunt-plan.yml),
[app equivalence checks](../scripts/ci/terragrunt-app-equivalence.py),
[Renovate](../renovate.json), and
[Harbor chart inventory](../scripts/config/harbor-image-charts.json). These
are expansion checks, with edits driven by the actual component being moved.

For a future implementation, compare generated Applications and rendered
resources before and after each move. Verify that CI renders the relocated
root and that no plan replaces a registration or changes its state key.
Switch the source paths on the same Applications so inventory ownership
stays continuous. This review proposes paths only.
