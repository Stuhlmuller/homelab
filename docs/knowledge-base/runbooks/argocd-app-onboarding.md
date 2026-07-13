# Argo CD App Onboarding

Tags: #runbook #argocd #applications

Canonical runbook: [`docs/argocd-app-onboarding.md`](../../argocd-app-onboarding.md)

Register applications through `IaC/live/argocd-apps/<app>` and keep runtime
state under `clusters/homelab/apps/<app>` or `clusters/homelab/platform/<service>`.
Use `main` for repository-backed sources and treat Terragrunt dependencies as
ordering only; readiness still requires Argo CD `Synced` and `Healthy` status.

See [[../architecture/gitops-flow]], [[../workloads/inventory]], and
[[../patterns/new-application]].
