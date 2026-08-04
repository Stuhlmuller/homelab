# Image Automation

Tags: #runbook #argocd #images

Canonical runbook: [`docs/argocd-image-updater.md`](../../argocd-image-updater.md)

Argo CD Image Updater opens pull requests for declared targets; it must not
leave live-only parameter overrides as steady state. Image pins outside managed
write-back targets remain repository-reviewed digest pins. Renovate excludes
Image Updater write-back targets so each image has one update owner; BusyBox is
the deliberate exception because its Deluge Helm and raw-manifest references
must move together. OctoBot remains manually review-pinned pending its PVC
migration.

GitHub App Contents and Pull requests write permissions are an external
prerequisite. Expanded permissions require installation-owner approval; they do
not require SSM credential rotation when the App identity is unchanged.

See [[../architecture/gitops-flow]] and [[validation]].
