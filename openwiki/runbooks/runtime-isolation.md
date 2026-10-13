---
type: runbook
title: "Runtime Isolation"
description: "Pod Security, service accounts, Istio authorization, workload security contexts, and unenforced NetworkPolicy limits on flannel."
tags: ["runbook", "security", "kubernetes"]
sources:
  - id: openwiki-source-e6fd9160ab2341143a5d45c8
    resource: repo://docs/image-egress-hardening.md
  - id: openwiki-source-556eb082b86343ef048df9f7
    resource: repo://docs/runtime-isolation.md
  - id: openwiki-source-221eda5e9e283a2549066105
    resource: repo://scripts/network-policy-inventory.py
generated: { by: "codex", at: "2026-10-13T03:34:25.328Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-13T05:09:09.786Z
---

# Runtime Isolation

Canonical runbook: [`docs/runtime-isolation.md`](../../docs/runtime-isolation.md)

Pod Security, service accounts, Istio authorization, and workload security
contexts are enforced desired state. NetworkPolicy objects remain intent-only
where the current flannel data plane cannot enforce them.

## Egress enforcement prerequisite

The 2026-10-12 read-only audit found all Flannel and ztunnel instances Ready,
but readiness does not add egress enforcement. Gateway API CRDs and a
`GatewayClass` are absent; existing Istio Gateway objects use the legacy API.
There is no NRI configuration or `kube-network-policies` deployment.

Do not enable default-deny egress, `REGISTRY_ONLY`, an egress waypoint, or the
existing NetworkPolicies globally. Some policies are incomplete or deliberately
broad, and image pulls are node/containerd traffic rather than pod egress.
`zimaboard-2` is not a safe canary because it has no dedicated isolation/taint,
limited capacity, system DaemonSets, and a live backup workload.

First add Gateway API, a repository-owned NRI policy dataplane, and a
capacity-isolated worker through their declared owners. Before activation,
compare private read-only Pod/NetworkPolicy snapshots and all rendered policies
with `scripts/network-policy-inventory.py --fail-on-findings`. A disposable
ambient canary must prove exact allowed DNS/destinations and denial of
undeclared domains, direct IPs, alternate ports, IPv6, and gateway bypasses.

See [Validation Gates](../operations/validation-gates.md) and [Workload Inventory](../workloads/inventory.md).
