---
type: runbook
title: "Argo CD App Rollback"
description: "Repository-owned Argo CD rollback and the separate backup and restore decision required for persistent application data."
tags: ["runbook", "rollback", "argocd"]
---

# Argo CD App Rollback

Canonical runbook: [`docs/rollback-argocd-apps.md`](../../docs/rollback-argocd-apps.md)

Rollback desired state through git and the declared Terragrunt/Argo CD path.
This also applies during incidents; there is no live-edit/backfill exception.
Do not treat application rollback as data rollback: persistent workloads need
their own backup and restore decision.

See [Storage And State](../architecture/storage-and-state.md) and [GitOps Flow](../architecture/gitops-flow.md).
