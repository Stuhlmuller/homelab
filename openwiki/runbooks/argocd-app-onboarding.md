---
type: runbook
title: "Argo CD App Onboarding"
description: "Application registration through shared Terragrunt inputs, repository source ownership, and ordering versus runtime readiness."
tags: ["runbook", "argocd", "applications"]
sources:
  - id: openwiki-source-79a5080e527bf9a6d04fc9fe
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/journal-delivery.yaml
  - id: openwiki-source-eadf0e51039eed966d58db54
    resource: repo://clusters/homelab/argocd/self-management/openclaw-enterprise-appproject.yaml
  - id: openwiki-source-cb44bee82f523806d88ae83a
    resource: repo://docs/argocd-app-onboarding.md
  - id: openwiki-source-5e8e516a25e2448b5e0205a4
    resource: repo://IaC/openclaw-enterprise-foundation/stack.hcl
  - id: openwiki-source-c4a1630a18962f8a58f367ec
    resource: repo://IaC/openclaw-enterprise/stack.hcl
  - id: openwiki-source-00c8a32293c8aaa55d3daba4
    resource: repo://IaC/platform-envoy-gateway/stack.hcl
  - id: openwiki-source-17718b74140783bc6aaf9388
    resource: repo://IaC/platform-network-policy-canary/stack.hcl
  - id: openwiki-source-f25343448eed330eba7e8617
    resource: repo://IaC/platform-network-policy-cleanup/stack.hcl
  - id: openwiki-source-e3e84b128839afbc47f478f7
    resource: repo://IaC/platform-network-policy/stack.hcl
generated: { by: "codex", at: "2026-10-20T01:43:56.313Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-20T01:43:56.313Z
---

# Argo CD App Onboarding

Canonical runbook: [`docs/argocd-app-onboarding.md`](../../docs/argocd-app-onboarding.md)

Register applications in `IaC/terragrunt.stack.hcl` with the shared
`IaC/terragrunt-catalog/units/live/argocd-app` template. Put per-app inputs in
`IaC/<app>/stack.hcl`, load common defaults from `IaC/stack-defaults.hcl`,
and keep runtime state under
`clusters/homelab/apps/<app>` or `clusters/homelab/platform/<service>`. Use
`main` for repository-backed sources and treat Terragrunt dependencies as
ordering only; readiness still requires Argo CD `Synced` and `Healthy` status.

The OpenClaw Enterprise prerequisites use dormant platform registrations.
`platform-network-policy` has no selected node; its canary and cleanup
Applications also have automatic sync and prune disabled. Their workflow must
first admit a measured tainted node, publish fixture images, qualify policy
traffic and prove ownership-limited cleanup. `platform-envoy-gateway` likewise
stays unsynced until the shared Gateway/Envoy CRDs, mirrored images and private
route are qualified. The CRD Helm source is the single shared CRD owner and
must become ready before its controller source. Registration alone neither
enforces policies nor serves an Enterprise route.

The separate Enterprise foundation and controller Applications are also only
declared source. Their dedicated AppProject scopes both source repositories,
three destination namespaces, and rendered resource kinds. Its namespaced PVC
allowlist now covers the dormant, retained operations-journal claim. The pinned upstream
chart, local values, and lifecycle hooks are one multi-source Application;
both Enterprise Applications disable automatic sync, pruning, self-heal, and
retries. Registering them does not satisfy PostgreSQL, secret, capacity, or
network-policy gates. Use the protected serialized full-sync path only after
those prerequisites and its implementation are verified.

See [GitOps Flow](../architecture/gitops-flow.md), [Workload Inventory](../workloads/inventory.md), and
[New Application Pattern](../patterns/new-application.md).
