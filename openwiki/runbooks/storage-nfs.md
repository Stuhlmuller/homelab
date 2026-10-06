---
type: runbook
title: "NFS Storage"
description: "QNAP NFS exports, default StorageClass and media volumes, with provisioning, persistence, backup, and restore validation."
tags: ["runbook", "storage", "nfs"]
---

# NFS Storage

Canonical runbook: [`docs/storage-nfs.md`](../../docs/storage-nfs.md)

The QNAP export at `10.1.0.2` backs the default `nfs-default` StorageClass and
explicit media volumes. Validate provisioning, persistence, backup, and restore
before relying on a stateful workload.

See [Storage And State](../architecture/storage-and-state.md) and [Workload Inventory](../workloads/inventory.md).
