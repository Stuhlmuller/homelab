---
type: runbook
title: "Argo CD App Onboarding"
description: "Application registration through shared Terragrunt inputs, repository source ownership, and ordering versus runtime readiness."
tags: ["runbook", "argocd", "applications"]
sources:
  - id: openwiki-source-d2d8ff2161af78b658d004f0
    resource: repo://clusters/homelab/apps/openclaw-enterprise-operator/README.md
  - id: openwiki-source-d65575b694fbbe7e37dd04e6
    resource: repo://clusters/homelab/apps/openclaw/README.md
  - id: openwiki-source-00d374aa17b82a33b8b28024
    resource: repo://clusters/homelab/apps/openclaw/runtime-backup.yaml
  - id: openwiki-source-b26876230e53fd853d7bcbea
    resource: repo://clusters/homelab/apps/openclaw/values.yaml
  - id: openwiki-source-9824f110ded8ce152ef180f9
    resource: repo://clusters/homelab/argocd/self-management/kustomization.yaml
  - id: openwiki-source-994a8289757a8dfdfff70e1b
    resource: repo://clusters/homelab/platform/network-policy/README.md
  - id: openwiki-source-cb44bee82f523806d88ae83a
    resource: repo://docs/argocd-app-onboarding.md
  - id: openwiki-source-df5b234ace5ca38a67ae3b6b
    resource: repo://docs/evidence/openclaw-enterprise-acceptance.md
  - id: openwiki-source-249f8996a9ec8263ee227cf0
    resource: repo://IaC/homelab/us-west-2/apps/openclaw-enterprise-foundation/stack.hcl
  - id: openwiki-source-1ce4e7c935caaec6b4eb2529
    resource: repo://IaC/homelab/us-west-2/apps/openclaw-enterprise/stack.hcl
  - id: openwiki-source-0c00f6db8dd49d62511a3f75
    resource: repo://IaC/homelab/us-west-2/apps/openclaw/stack.hcl
  - id: openwiki-source-9c3fe2e8035c7eb9d09bfd26
    resource: repo://IaC/homelab/us-west-2/apps/platform-envoy-gateway/stack.hcl
  - id: openwiki-source-e6bd097f07292b202c6eecb6
    resource: repo://IaC/homelab/us-west-2/apps/platform-network-policy-canary/stack.hcl
  - id: openwiki-source-03cba9ca7ae035a0dcbbccef
    resource: repo://IaC/homelab/us-west-2/apps/platform-network-policy/stack.hcl
  - id: openwiki-source-d2206c7f78c1ec59c3551c13
    resource: repo://scripts/config/openclaw-enterprise.json
  - id: openwiki-source-79ade26d1f528d349dc08fed
    resource: repo://scripts/network-policy-canary-node.py
  - id: openwiki-source-1d91dece74882a3fae04c364
    resource: repo://scripts/network-policy-cleanup.py
  - id: openwiki-source-ba849f5dbd0942cee0b0087d
    resource: repo://scripts/network-policy-ownership.py
generated: { by: "codex", at: "2026-10-24T03:50:35.181Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-27T10:41:09.582Z
---

# Argo CD App Onboarding

Canonical runbook: [`docs/argocd-app-onboarding.md`](../../docs/argocd-app-onboarding.md)

Register applications in `IaC/homelab/us-west-2/apps/<app>/terragrunt.stack.hcl` with the shared
`IaC/terragrunt-catalog/units/live/argocd-app` template. Put per-app inputs in
`IaC/homelab/us-west-2/apps/<app>/stack.hcl`, load common defaults from `IaC/stack-defaults.hcl`,
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

The Enterprise AppProject is included in Argo CD self-management and can
reconcile after merge. The separate foundation and stock-chart Applications
are declared in the root Terragrunt stack, but require a later protected apply.
Both disable automatic sync, pruning, self-heal and retries. Run the focused
[`openclaw-enterprise-registration-test.py`](../../scripts/ci/openclaw-enterprise-registration-test.py)
after stack generation to inspect their rendered sources and resource allowlist.
Registration does not prove database or secret readiness; complete sync still
requires storage, capacity, policy and live gates.
The legacy `openclaw` Application remains registered with a zero-replica
gateway, suspended backup writer, and read-only recovery reader. The separate
Enterprise journal-operator bundle has no Argo or Terragrunt registration. Its
exact-source image passed signed publication and authenticated pull in protected
[run `40056484158`](https://github.com/Stuhlmuller/homelab/actions/runs/40056484158),
but reconciliation remains disabled pending placement and private bootstrap-key
proof.

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
