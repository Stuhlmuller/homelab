# Argo CD App Registrations

This directory is the Terragrunt entry point for registering homelab
applications with Argo CD. Each child directory owns exactly one Argo CD
Application and sources the repository-local
`IaC/modules/argocd-application-kubernetes` module.

The 15 requested apps are registered here along with one supporting
`platform-storage` Application for the QNAP NFS provisioner and default
StorageClass desired state. `platform-storage` is not one of the requested apps;
it exists so Kubernetes storage changes are still delivered through Argo CD.

## Conventions

- Use one `IaC/live/argocd-apps/<app>/terragrunt.hcl` file per Application.
- Include `IaC/root.hcl` from every unit.
- Source the local Kubernetes-backed Application module. Do not require a
  locally authenticated Argo CD API provider for routine app registration.
- Declare every upstream relationship with a `dependencies` block.
- Use `sync_policy.automated` with prune and self-heal by default. Any future
  exception must be documented beside the app registration.
- Put non-secret chart values and raw manifests under
  `clusters/homelab/apps/<app>/` or `clusters/homelab/platform/storage/`.

## Readiness Semantics

Terragrunt dependencies guarantee registration order only. Operational
readiness still requires Argo CD sync and health checks, documented in
`docs/validation-runbook.md`, before dependent apps are considered ready for
rollout.
