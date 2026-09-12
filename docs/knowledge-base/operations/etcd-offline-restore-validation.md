# Offline Etcd Restore Validation

The [offline validation runbook](../../etcd-offline-restore-validation.md)
and `scripts/etcd-offline-restore-check.py` extend a verified Talos snapshot
with database parsing and restoration into a private local directory.
The helper pins an official etcd `3.6.5` archive, verifies its SHA-256, extracts
only `etcdutl`, and preserves source bytes. It requires the parsed snapshot
metadata to match the backup manifest and retains revision/key count after
checksum-enabled restore. Each invocation has a separate output directory.

**Validation:** twelve behavioral fixtures pass using synthetic input and a fake
client. On 2026-09-07, the merged helper completed one real offline restore
using the checksum-pinned etcd `3.6.5` macOS ARM64 tool in 2.68 seconds.
Revision `37730997` and `2919` MVCC keys were preserved; the original snapshot
and manifest digests were unchanged. Fixed metadata and tool provenance are
retained in private receipts. No server or network listener started.

**Boundary:** a successful offline restore proves parsing/restoration only.
It does not prove Kubernetes startup, informer/watch recovery, application
consistency, PVC recovery, or restored-tree power-loss durability. The generated
local membership is disposable,
and restored data contains the same confidential Kubernetes state as the
snapshot. Keep receipts and data outside Git. The
[local scheduler](../../talos-etcd-schedule.md) and
[[operations/etcd-offsite-publication|manual offsite publisher]] have separate
first-run evidence; the downloaded scheduled snapshot was not this restore's
source. An isolated control-plane recovery exercise remains open.

See [[architecture/storage-and-state]],
[[runbooks/talos-control-plane-maintenance]], and
[[operations/validation-gates]] for surrounding recovery contracts.
