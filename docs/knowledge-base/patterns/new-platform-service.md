# New Platform Service Pattern

Tags: #pattern #platform #argocd

Use this checklist before adding a shared platform service such as DNS, storage,
ingress, certificate management, secret management, observability plumbing, or a
cluster-wide controller.

## Read First

- [[architecture/gitops-flow]]
- [[architecture/storage-and-state]] when state or storage is involved
- [[architecture/secrets-and-identity]] when credentials or identity are
  involved
- [[operations/validation-gates]]
- Relevant runbook under `docs/`

## Implementation Shape

1. Put desired state under `clusters/homelab/platform/<service>` unless the
   service is intentionally application-scoped.
2. Register the parent Application under
   `IaC/live/argocd-apps/platform-<service>`.
3. Document downstream apps that depend on the service.
4. Add readiness checks before dependent workloads rely on the service.
5. Keep rollback notes close to the runbook.
6. Update the source docs that teach the service before or with the code change.

## Knowledge-Base Update

Update the affected architecture note, [[workloads/inventory]] if dependencies
change, and [[operations/validation-gates]] if validation changes.
