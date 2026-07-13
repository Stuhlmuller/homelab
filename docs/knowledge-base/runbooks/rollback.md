# Argo CD App Rollback

Tags: #runbook #rollback #argocd

Canonical runbook: [`docs/rollback-argocd-apps.md`](../../rollback-argocd-apps.md)

Rollback desired state through git and the declared Terragrunt/Argo CD path.
Do not treat application rollback as data rollback: persistent workloads need
their own backup and restore decision.

See [[../architecture/storage-and-state]] and [[../architecture/gitops-flow]].
