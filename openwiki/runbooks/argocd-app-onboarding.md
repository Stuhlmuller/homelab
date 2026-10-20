---
type: runbook
title: "Argo CD App Onboarding"
description: "Application registration through shared Terragrunt inputs, repository source ownership, and ordering versus runtime readiness."
tags: ["runbook", "argocd", "applications"]
sources:
  - id: openwiki-source-994a8289757a8dfdfff70e1b
    resource: repo://clusters/homelab/platform/network-policy/README.md
  - id: openwiki-source-cb44bee82f523806d88ae83a
    resource: repo://docs/argocd-app-onboarding.md
  - id: openwiki-source-00c8a32293c8aaa55d3daba4
    resource: repo://IaC/platform-envoy-gateway/stack.hcl
  - id: openwiki-source-17718b74140783bc6aaf9388
    resource: repo://IaC/platform-network-policy-canary/stack.hcl
  - id: openwiki-source-e3e84b128839afbc47f478f7
    resource: repo://IaC/platform-network-policy/stack.hcl
  - id: openwiki-source-79ade26d1f528d349dc08fed
    resource: repo://scripts/network-policy-canary-node.py
  - id: openwiki-source-1d91dece74882a3fae04c364
    resource: repo://scripts/network-policy-cleanup.py
  - id: openwiki-source-ba849f5dbd0942cee0b0087d
    resource: repo://scripts/network-policy-ownership.py
generated: { by: "codex", at: "2026-10-20T15:35:56.635Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-20T15:35:56.635Z
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

After the traffic probe, two reviewed GitOps commits prune the fixtures and
then the enforcer; each may include native OpenWiki metadata. Apply the
fixture prune and verify the live `network-policy-canary` namespace and all
fixture workloads are absent before ownership capture. Keep the emptied
canary Application automated with `allowEmpty` through cleanup and node
release; disable automatic sync afterward. The cleanup Application then
syncs a reviewed Pod to the admitted node; private capture and owner approval
gate rule deletion. Capture through release require assigned Pods to match
the reviewed system DaemonSet identities plus that cleanup Pod while it runs.
After deletion, release rechecks that only the reviewed system Pods remain
before removing the taint; a system Pod restart blocks this immutable
placement path pending reviewed recovery.

See [GitOps Flow](../architecture/gitops-flow.md), [Workload Inventory](../workloads/inventory.md), and
[New Application Pattern](../patterns/new-application.md).
