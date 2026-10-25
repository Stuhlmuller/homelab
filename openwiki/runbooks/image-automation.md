---
type: runbook
title: "Image Automation"
description: "Renovate image updates, mandatory digest pins, and reviewed Helm, Kustomize, and Kubernetes image changes."
tags: ["runbook", "renovate", "images"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-19T22:53:09.781Z
sources:
  - id: openwiki-source-c728e68797517895d00bd9f9
    resource: repo://clusters/homelab/apps/renovate/cronjob.yaml
  - id: openwiki-source-37ab85ec674316a7b7b7cf23
    resource: repo://docs/image-automation.md
generated: { by: "codex", at: "2026-10-19T22:53:09.781Z" }
---

# Image Automation

Canonical runbook: [`docs/image-automation.md`](../../docs/image-automation.md)

Renovate is the only active repository image updater. Helm values, Kustomize,
and raw Kubernetes image references remain reviewed pull requests and every
committed image must include a digest.

The hourly in-cluster runner is unsuspended in full dry-run mode. The legacy
GitHub Action remains the only PR writer until the reviewed cutover.

See [GitOps Flow](../architecture/gitops-flow.md), [Secrets And Identity](../architecture/secrets-and-identity.md),
and [Validation](validation.md).
