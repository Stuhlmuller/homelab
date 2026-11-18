# Argo CD Image Updater

The declared native controller runs one idle replica until an operator explicitly
enrolls a workload through the shared Terragrunt `argocd-app` unit. It uses digest
resolution and Argo CD write-back; it does not commit hashes or select versions.
No workload is currently enrolled. Deployment readiness is not yet established.

See the [operator guide](../../../../docs/argocd-image-updater.md) for exact tag
selection, absent override fields, Renovate exceptions, pause/source-edit handoff,
permanent removal, protected delivery, and validation limits. The historical
`managed-images.yaml` remains a compatibility catalog, not native CR enrollment.
