---
type: runbook
title: "Homelab Onboarding"
description: "Canonical Talos control-plane, Kubernetes API, and QNAP endpoints with links to cluster onboarding and maintenance."
tags: ["runbook", "onboarding", "talos"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-27T21:30:24.345Z
sources:
  - id: openwiki-source-9bdcfe9208171929589f54da
    resource: repo://ONBOARDING.md
---

# Homelab Onboarding

Canonical guide: [`ONBOARDING.md`](../../ONBOARDING.md)

The current Talos control-plane address is `10.1.0.199`, the Kubernetes API is
`https://10.1.0.199:6443`, and the QNAP NFS server is `10.1.0.2`. Treat the
canonical guide and repository-owned Talos files as the operational source.

See [Cluster Topology](../architecture/cluster-topology.md) and [Talos Control-Plane Maintenance](talos-control-plane-maintenance.md).
