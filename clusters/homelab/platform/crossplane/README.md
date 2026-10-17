# Crossplane

This path documents the Crossplane core deployment for the homelab cluster. The
`platform-crossplane` Argo CD Application is registered by the Terragrunt unit
at `IaC/live/argocd-apps/platform-crossplane` and installs the upstream
Crossplane chart with explicit standby replica values into the `crossplane-system` namespace.

This installs only Crossplane core. Providers, ProviderConfigs, Compositions,
and cloud credentials should be added in later, purpose-specific changes with
their secret contracts documented before rollout.

Before declaring the rollout healthy, verify:

```sh
kubectl -n crossplane-system get pods
kubectl get crd | rg 'crossplane.io|pkg.crossplane.io'
```

If Argo CD starts managing Crossplane Provider, Composition, or managed-resource
objects, configure Argo CD annotation-based resource tracking and health
customizations first. Crossplane documents those requirements in its Argo CD
guide.

## Standby for Cordium capacity

The October 17 capacity audit found no installed Providers, Configurations,
Functions, Compositions or CompositeResourceDefinitions. Core and RBAC-manager
replicas are explicitly zero in the owning stack, releasing 512 MiB of Acer
requests while preserving chart resources, CRDs and RBAC. Crossplane APIs have
no active controllers in this state. Restore both replica counts to one through
the stack and protected apply before adding packages or compositions.

Together with measured application reservations, this releases 1,664 MiB; see the
[receipt](../../../../docs/evidence/acer-cordium-capacity-2026-10-17.json).
After GitOps convergence, verify both Deployments have zero replicas and no
remaining active Pods, all affected applications are healthy, Langfuse web is
Ready on Acer, and `zimaboard-1` has at least 2.5 GiB unreserved before starting
one 2 GiB Cordium workspace. Keep at least 1 GiB unreserved on Acer and stop if
either node develops pressure. Acer capacity alone cannot schedule a Workspace.

Rollback: delete the owned smoke workspace through its verified native cleanup
path first, restore original requests, Langfuse web placement and Crossplane replicas in source, then
use protected merge/apply. Check scheduler capacity before starting replacement
Pods. Never move or delete existing database/workspace volumes.
