# Offline Etcd Restore Validation

The [offline validation runbook](../../etcd-offline-restore-validation.md)
and `scripts/etcd-offline-restore-check.py` extend a verified Talos snapshot
with database parsing and restoration into a private local directory.
The helper pins an official etcd `3.6.5` archive, verifies its SHA-256, extracts
only `etcdutl`, and preserves source bytes. It requires the parsed snapshot
metadata to match the backup manifest and retains revision/key count after
checksum-enabled restore. Each invocation has a separate output directory.

**Validation:** twelve behavioral fixtures pass using synthetic input and a fake
client. The native macOS ARM64 release archive matches the published checksum;
its `etcdutl version` and help commands execute. Real snapshot restore remains
pending. No server or network listener starts during this workflow.

**Boundary:** a successful offline restore proves parsing/restoration only.
It does not prove Kubernetes startup, informer/watch recovery, application
consistency, or PVC recovery. The generated local membership is disposable,
and restored data contains the same confidential Kubernetes state as the
snapshot. Keep receipts and data outside Git. Scheduling, offsite copies,
retention, and an isolated control-plane recovery exercise are separate work.

See [[architecture/storage-and-state]],
[[runbooks/talos-control-plane-maintenance]], and
[[operations/validation-gates]] for surrounding recovery contracts.
