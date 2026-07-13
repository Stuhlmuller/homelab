# Argo CD Bootstrap

Tags: #runbook #argocd #bootstrap

Canonical runbook: [`docs/argocd-bootstrap.md`](../../argocd-bootstrap.md)

The bootstrap unit is `IaC/bootstrap/argocd`. It installs Argo CD, then hands
steady-state ownership to `clusters/homelab/argocd/self-management`. Preserve
the documented single-apply path and keep OIDC secret material outside git.

See [[../architecture/gitops-flow]] and [[validation]].
