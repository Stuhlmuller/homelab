---
name: homelab-app-onboarding
description: Add a homelab workload or platform Application through the shared generated Terragrunt stack and existing Helm/Kustomize layout. Use for new app deployments or registration changes, not ordinary app source-code development.
---

# Homelab App Onboarding

Start with the relevant [inventory entry](../../../docs/knowledge-base/workloads/inventory.md)
and [onboarding contract](../../../docs/argocd-app-onboarding.md). Read the nearest
workload README and only the storage, secret or ingress runbooks the app needs.

## Minimal registration

Add runtime desired state under `clusters/homelab/apps/<app>` or the appropriate
platform directory. Register it in `IaC/terragrunt.stack.hcl` through the shared
Application template; do not copy a generated live unit or a full CRD:

```hcl
unit "argocd_apps_example" {
  source                 = "./.catalog/units/live/argocd-app"
  path                   = "live/argocd-apps/example"
  no_dot_terragrunt_stack = true

  values = {
    defaults     = local.argocd_defaults
    dependencies = ["external-secrets"]
    spec = {
      project = "homelab-workloads"
    }
  }
}
```

`example` and its dependency are teaching placeholders; choose only the actual
dependencies and project permissions needed by the app. Common source, revision,
destination and sync behavior come from stack defaults. Set `spec.destination`
only for differing destination fields and `spec.sources` for Helm or a platform
path. Source lists replace defaults in full; chart versions and all sources
must remain explicit. See [Terragrunt merge semantics](../terragrunt-workflows/SKILL.md).

## Complete the app boundary

- Select chart ownership from [chart organization](../../../docs/knowledge-base/patterns/helm-chart-organization.md).
  Prefer upstream charts plus local values and existing shared chart patterns;
  do not vendor generated manifests or duplicate templates to add one workload.
- Define resource requests, probes, image digest pins, service and namespace
  ownership. Render before choosing `homelab-workloads`; apps requiring cluster
  resources need the reviewed broader AppProject permissions. Check the exact
  [workload AppProject](../../../clusters/homelab/argocd/self-management/workloads-appproject.yaml)
  namespace/source allowlists; add required permissions through reviewed code
  before registration, rather than assuming a new namespace is already allowed.
- Add only the required [secret contract](../homelab-secret-contracts/SKILL.md),
  storage/backup/restore and access rules. Octelium is the normal UI entrypoint;
  public callbacks need the documented exception in the onboarding runbook.
- Inventory and [publish required images](../homelab-harbor-images/SKILL.md)
  before a consuming reference reaches `main`.
- Keep Terragrunt registration dependencies separate from the app's runtime
  Synced/Healthy prerequisites, and document both in its README.

Generate the stack and inspect the resulting Application. For a new unit using
the same shared module, copy a reviewed peer's `.terraform.lock.hcl` to its new
live directory and commit it; generation does not create provider locks. For a
different provider/module contract, initialize its lock deliberately and review
the selected versions before readonly validation. Run the affected gates from
[Terragrunt workflows](../terragrunt-workflows/SKILL.md). Update the workload
inventory and affected architecture notes in the same change. For authorized
delivery, finish [release verification](../homelab-release-verification/SKILL.md),
including the original user action after rollout.
