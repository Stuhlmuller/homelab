# Image Automation

Tags: #runbook #renovate #images

Canonical runbook: [`docs/argocd-image-updater.md`](../../argocd-image-updater.md)

Renovate is the only active repository image updater. Helm values, Kustomize,
and raw Kubernetes image references remain reviewed pull requests and every
committed image must include a digest.

Argo CD Image Updater was retired on 2026-08-26 after months of failed GitHub
App pushes and discovery of a stale Radarr `5.x` selector against desired
version `6.3.0`. Its marker-only Application stays registered until Argo CD has
pruned the controller resources. The former SSM credential paths are inert
OpenTofu state tombstones with no ExternalSecret consumer or reader IAM grant.

See [[../architecture/gitops-flow]], [[../architecture/secrets-and-identity]],
and [[validation]].
