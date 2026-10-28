---
type: runbook
title: "NFS Storage"
description: "QNAP NFS exports, default StorageClass and media volumes, with provisioning, persistence, backup, and restore validation."
tags: ["runbook", "storage", "nfs"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-27T21:30:24.345Z
sources:
  - id: openwiki-source-80ce7a2e5d2f59ee74027e0c
    resource: repo://docs/storage-nfs.md
---

# NFS Storage

Canonical runbook: [`docs/storage-nfs.md`](../../docs/storage-nfs.md)

The QNAP export at `10.1.0.2` backs the default `nfs-default` StorageClass and
explicit media volumes. Validate provisioning, persistence, backup, and restore
before relying on a stateful workload.

See [Storage And State](../architecture/storage-and-state.md) and [Workload Inventory](../workloads/inventory.md).
