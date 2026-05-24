# Argo CD App Registrations

This directory is the Terragrunt entry point for registering homelab
applications with Argo CD. Each child directory owns exactly one Argo CD
Application and sources the `argocd-application` module from the configured
Terragrunt catalog.

The 13 requested apps are registered here along with one supporting
`platform-storage` Application for the QNAP NFS provisioner and default
StorageClass desired state. `platform-storage` is not one of the requested apps;
it exists so Kubernetes storage changes are still delivered through Argo CD.

## Conventions

- Use one `IaC/live/argocd-apps/<app>/terragrunt.hcl` file per Application.
- Include `IaC/root.hcl` from every unit.
- Source the catalog module from the pinned Terragrunt catalog commit.
- Declare every upstream relationship with a `dependencies` block.
- Use `sync_policy.automated` only when the app is safe to reconcile without an
  unmet external prerequisite.
- Put non-secret chart values and raw manifests under
  `clusters/homelab/apps/<app>/` or `clusters/homelab/platform/storage/`.

## Readiness Semantics

Terragrunt dependencies guarantee registration order only. Operational
readiness still requires Argo CD sync and health checks, documented in
`docs/validation-runbook.md`, before dependent apps are considered ready for
rollout.
