---
type: runbook
title: "Runtime Isolation"
description: "Current Pod Security and Istio boundaries, plus dormant firewall-only kube-router NetworkPolicy prerequisites and canary gates."
tags: ["runbook", "security", "kubernetes"]
sources:
  - id: openwiki-source-994a8289757a8dfdfff70e1b
    resource: repo://clusters/homelab/platform/network-policy/README.md
  - id: openwiki-source-df5b234ace5ca38a67ae3b6b
    resource: repo://docs/evidence/openclaw-enterprise-acceptance.md
  - id: openwiki-source-e6fd9160ab2341143a5d45c8
    resource: repo://docs/image-egress-hardening.md
  - id: openwiki-source-556eb082b86343ef048df9f7
    resource: repo://docs/runtime-isolation.md
  - id: openwiki-source-a347fb1739a2d297e214f41a
    resource: repo://scripts/network-policy-qualification.py
generated: { by: "codex", at: "2026-10-19T10:02:28.692Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-19T10:09:06.381Z
---

# Runtime Isolation

Canonical runbook: [`docs/runtime-isolation.md`](../../docs/runtime-isolation.md)

Pod Security, service accounts, Istio authorization, and workload security
contexts are enforced desired state. Existing `NetworkPolicy` objects remain
intent-only while Flannel is the sole active CNI and the staged firewall-only
kube-router Application selects no node.

## Egress enforcement prerequisite

The 2026-10-12 read-only audit found all Flannel and ztunnel instances Ready,
but readiness does not add egress enforcement. Gateway API CRDs and a
`GatewayClass` were absent; existing Istio Gateway objects use the legacy API.
Envoy Gateway and firewall-only kube-router are now staged in GitOps with
automatic sync disabled. The prior source-only NRI fragment is not the chosen
enforcement path.

Do not enable default-deny egress, `REGISTRY_ONLY`, an egress waypoint, or the
existing NetworkPolicies globally. Some policies are incomplete or deliberately
broad, and image pulls are node/containerd traffic rather than pod egress.
`zimaboard-2` is not a safe canary because it has no dedicated isolation/taint,
limited capacity, system DaemonSets, and a live backup workload.

Before activation, finish image publication and policy owner/render review, then
admit an isolated tainted canary with measured capacity and local-storage
placement. No existing worker currently qualifies without risking unrelated
stateful workloads. Compare private read-only Pod/NetworkPolicy snapshots and
all rendered policies with `scripts/network-policy-inventory.py`. Qualify
allowed DNS/API/storage/mesh traffic and denied direct IP, alternate port,
IPv6, and gateway bypass on the canary. Prove enforcer restart, API loss,
IP reuse, rescheduling, cold reboot, and ownership-limited cleanup before
expanding to another node. Stock Enterprise's public TCP/443 requirement
remains broad egress; Kubernetes `NetworkPolicy` does not provide an FQDN
allowlist.

The protected [`network-policy-qualification.py`](../../scripts/network-policy-qualification.py)
checks the live firewall-only DaemonSet image, flags, host mount and RBAC, then
checks the admitted tainted node, three fixed fixture Pods and their policy.
Its TCP/UDP allow-and-deny probe writes a private receipt that explicitly lists
the lifecycle scenarios still unverified. The qualifier does not create the
fixture or attest node reboot, enforcer recovery, or real workload traffic;
those remain live gates before enforcement expands.

See [Validation Gates](../operations/validation-gates.md) and [Workload Inventory](../workloads/inventory.md).
