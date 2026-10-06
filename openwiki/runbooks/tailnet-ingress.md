---
type: runbook
title: "Tailnet And App Ingress"
description: "Octelium primary access, Istio ClusterIP ingress, temporary Tailscale fallback, and explicit path-limited public callbacks."
tags: ["runbook", "networking", "ingress"]
---

# Tailnet And App Ingress

Canonical runbook: [`docs/networking-tailnet-ingress.md`](../../docs/networking-tailnet-ingress.md)

Octelium owns primary human-app, Kubernetes, Cordium, and callback access. The
primary Istio gateway is `ClusterIP` only. Tailscale remains deployed as a
temporary Talos/LAN/egress fallback; remove it only after the private Octelium
Kubernetes paths and a replacement Talos transport are validated remotely.
Public callbacks must stay explicit, path-limited, and represented in
repository-owned Istio and tunnel config.

See [Octelium](octelium.md) and [Workload Inventory](../workloads/inventory.md).
