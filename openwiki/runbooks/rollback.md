---
type: runbook
title: "Argo CD App Rollback"
description: "Repository-owned Argo CD rollback and the separate backup and restore decision required for persistent application data."
tags: ["runbook", "rollback", "argocd"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-27T21:30:24.345Z
sources:
  - id: openwiki-source-8a1a5b8d575c44deffc46d40
    resource: repo://docs/rollback-argocd-apps.md
---

# Argo CD App Rollback

Canonical runbook: [`docs/rollback-argocd-apps.md`](../../docs/rollback-argocd-apps.md)

Rollback desired state through git and the declared Terragrunt/Argo CD path.
This also applies during incidents; there is no live-edit/backfill exception.
Do not treat application rollback as data rollback: persistent workloads need
their own backup and restore decision.

See [Storage And State](../architecture/storage-and-state.md) and [GitOps Flow](../architecture/gitops-flow.md).
