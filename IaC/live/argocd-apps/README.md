# Argo CD App Registrations

This directory contains generated Terragrunt entry points for registering
homelab applications with Argo CD. The committed source lives in
`IaC/.catalog/units/live/argocd-app/terragrunt.hcl`, and
`IaC/terragrunt.stack.hcl` indexes unit identities and output paths. It loads
per-app inputs from `IaC/stacks/<app>/stack.hcl` and regenerates each child
directory. Common Application defaults live in `IaC/stack-defaults.hcl`.

The requested apps are registered here along with supporting Applications for
shared platform services. `platform-dns` owns CoreDNS resolver policy,
`platform-storage` owns the QNAP NFS provisioner and default StorageClass
desired state, and `media-postgres` owns the shared PostgreSQL instance for
Sonarr, Radarr, and Prowlarr. `n8n-postgres` owns the dedicated PostgreSQL
instance for n8n. These support apps are not counted as requested workloads;
they exist so dependency state is still delivered through Argo CD.

## Conventions

- Use the shared `IaC/.catalog/units/live/argocd-app/terragrunt.hcl` template
  for every active Application. Register its unit in `IaC/terragrunt.stack.hcl`
  and put per-app inputs in `IaC/stacks/<app>/stack.hcl`.
- Include `IaC/root.hcl` from every unit.
- Source the local Kubernetes-backed Application module. Do not require a
  locally authenticated Argo CD API provider for routine app registration.
- Pass the `Application` as a raw `manifest` using Argo CD CRD field names such
  as `repoURL`, `targetRevision`, and `syncPolicy`.
- Register ordinary namespaced Applications in `homelab-workloads`. Keep
  platform controllers and Applications that need audited cluster resources
  in `homelab`. Update the selected project manifest under
  `clusters/homelab/argocd/self-management` when a source, destination, or
  resource requirement changes.
- Declare every upstream relationship with `inputs.dependencies` in the app's
  stack file, using sibling app names such as `external-secrets` or an explicit
  relative path to a non-Application unit.
- Use `spec.syncPolicy.automated` with prune and self-heal by default. Any future
  exception must be documented beside the app registration.
- Put non-secret chart values and raw manifests under
  `clusters/homelab/apps/<app>/` or `clusters/homelab/platform/<service>/`.
- Keep repo-declared workload images pinned as `tag@sha256:digest`; Renovate
  owns reviewed image update pull requests.
- Keep retired Applications registered until the live Argo CD resource has
  synced to an empty target or has been explicitly destroyed. Deleting the
  Terragrunt directory alone leaves the live Application unmanaged.

## Readiness Semantics

Terragrunt dependencies guarantee registration order only. Operational
readiness still requires Argo CD sync and health checks, documented in
`docs/validation-runbook.md`, before dependent apps are considered ready for
rollout.
