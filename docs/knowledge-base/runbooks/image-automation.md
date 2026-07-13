# Image Automation

Tags: #runbook #argocd #images

Canonical runbook: [`docs/argocd-image-updater.md`](../../argocd-image-updater.md)

Argo CD Image Updater opens pull requests for declared targets; it must not
leave live-only parameter overrides as steady state. Image pins outside managed
write-back targets remain repository-reviewed digest pins.

See [[../architecture/gitops-flow]] and [[validation]].
