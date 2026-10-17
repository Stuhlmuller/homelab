---
type: runbook
title: "Image Automation"
description: "Renovate image updates, mandatory digest pins, and reviewed Helm, Kustomize, and Kubernetes image changes."
tags: ["runbook", "renovate", "images"]
---

# Image Automation

Canonical runbook: [`docs/image-automation.md`](../../docs/image-automation.md)

Renovate is the only active repository image updater. Helm values, Kustomize,
and raw Kubernetes image references remain reviewed pull requests and every
committed image must include a digest.

See [GitOps Flow](../architecture/gitops-flow.md), [Secrets And Identity](../architecture/secrets-and-identity.md),
and [Validation](validation.md).
