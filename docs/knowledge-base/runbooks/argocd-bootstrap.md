# Argo CD Bootstrap

Tags: #runbook #argocd #bootstrap

Canonical runbook: [`docs/argocd-bootstrap.md`](../../argocd-bootstrap.md)

The bootstrap unit is `IaC/bootstrap/argocd`. It installs Argo CD, then hands
steady-state ownership to `clusters/homelab/argocd/self-management`. Preserve
the documented single-apply path, generate the explicit stack from `IaC/`
before entering the generated unit, and keep OIDC secret material outside git.
Emergency recovery also requires validated repository-owned desired state
before mutation; live edits followed by backfilling are not supported.

See [[../architecture/gitops-flow]] and [[validation]].
