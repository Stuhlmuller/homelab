---
type: runbook
title: "Argo CD App Onboarding"
description: "Application registration through shared Terragrunt inputs, repository source ownership, and ordering versus runtime readiness."
tags: ["runbook", "argocd", "applications"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-19T07:08:11.339Z
sources:
  - id: openwiki-source-994a8289757a8dfdfff70e1b
    resource: repo://clusters/homelab/platform/network-policy/README.md
  - id: openwiki-source-cb44bee82f523806d88ae83a
    resource: repo://docs/argocd-app-onboarding.md
  - id: openwiki-source-00c8a32293c8aaa55d3daba4
    resource: repo://IaC/platform-envoy-gateway/stack.hcl
  - id: openwiki-source-e3e84b128839afbc47f478f7
    resource: repo://IaC/platform-network-policy/stack.hcl
generated: { by: "codex", at: "2026-10-19T07:08:11.339Z" }
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

See [GitOps Flow](../architecture/gitops-flow.md), [Workload Inventory](../workloads/inventory.md), and
[New Application Pattern](../patterns/new-application.md).
