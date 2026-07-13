# NFS Storage

Tags: #runbook #storage #nfs

Canonical runbook: [`docs/storage-nfs.md`](../../storage-nfs.md)

The QNAP export at `10.1.0.2` backs the default `nfs-default` StorageClass and
explicit media volumes. Validate provisioning, persistence, backup, and restore
before relying on a stateful workload.

See [[../architecture/storage-and-state]] and [[../workloads/inventory]].
