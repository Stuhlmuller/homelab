# Image Automation

Tags: #runbook #renovate #images

Canonical runbook: [`docs/image-automation.md`](../../image-automation.md)

Renovate is the only active repository image updater. Helm values, Kustomize,
and raw Kubernetes image references remain reviewed pull requests and every
committed image must include a digest.

See [[../architecture/gitops-flow]], [[../architecture/secrets-and-identity]],
and [[validation]].
