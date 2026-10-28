---
type: runbook
title: "Argo CD Bootstrap"
description: "Argo CD bootstrap, transfer to GitOps self-management, single-apply setup, and repository-owned emergency recovery."
tags: ["runbook", "argocd", "bootstrap"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-27T21:30:24.345Z
sources:
  - id: openwiki-source-9cda10a2794e2ba86d411094
    resource: repo://docs/argocd-bootstrap.md
---

# Argo CD Bootstrap

Canonical runbook: [`docs/argocd-bootstrap.md`](../../docs/argocd-bootstrap.md)

The bootstrap unit is `IaC/homelab/us-west-2/bootstrap/argocd`. It installs Argo CD, then hands
steady-state ownership to `clusters/homelab/argocd/self-management`. Preserve
the documented single-apply path, generate the explicit stack from `IaC/`
before entering the generated unit, and keep OIDC secret material outside git.
Emergency recovery also requires validated repository-owned desired state
before mutation; live edits followed by backfilling are not supported.

See [GitOps Flow](../architecture/gitops-flow.md) and [Validation](validation.md).
