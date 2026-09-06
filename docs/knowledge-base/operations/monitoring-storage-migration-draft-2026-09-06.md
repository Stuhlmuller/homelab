# Monitoring Storage Migration Draft

Status: design only; healthy storage placement and restore gates remain open.
No node or new storage device is selected, and no rollout is authorized by this
note. Preserve existing history and retention; do not initialize an empty
replacement to bypass a failed migration.

## Current Contract And Evidence

`IaC/terragrunt.stack.hcl` pins kube-prometheus-stack `85.2.0`.
`clusters/homelab/apps/prometheus/values.yaml` retains Prometheus history for
`15d` on a `50Gi` NFS claim and Alertmanager state on a `10Gi` NFS claim.
Read-only inspection confirmed Operator `v0.90.1`, Prometheus
`v3.11.3-distroless`, Alertmanager `v0.32.1`, and Alertmanager retention `120h`.
Each has one replica; both currently run on `acer`. Keep these versions,
resource names, Services, authentication, scrape selectors, and notification
routing unchanged during the storage move.

The operator owns both StatefulSets through their respective CRs. Existing
PVCs have no owner references; both StatefulSets specify `Retain` for scale-down
and deletion. The old claims must stay retained and explicitly protected from
Argo pruning. Mount layouts are `prometheus-db` at `/prometheus` and
`alertmanager-db` at `/alertmanager`; preserve those subdirectories. Runtime
ownership is UID `1000`, GID/fsGroup `2000`.

Read-only September 6 measurements put Prometheus blocks, WAL, and head chunks
at approximately `8GiB` combined; Alertmanager's directory is approximately
`8KiB`. The NFS kubelet volume metrics report the shared export's filesystem
usage, so they must not be interpreted as either application's directory size.
Use Prometheus's own TSDB size metrics and an offline directory inventory for
copy sizing. The requested PVC capacities are not hard quotas on NFS or hostPath.

Only `acer` currently has sufficient local disk headroom for the unchanged
`50Gi`/`10Gi` budgets and verification copies. Its `/var` filesystem is XFS on
the existing system disk. However, its bit-flip/image/etcd corruption incident
remains unresolved: see [[continuous-improvement]], Acer storage-integrity
finding. Existing worker disks are approximately 32 GB system eMMC devices;
read-only Talos inventory found no spare independent data device. The small
worker cannot satisfy Prometheus memory requirements. This is a hardware gate,
not permission to move persistent data onto unverified storage.

## Why A New Claim Name Is Required

Changing only `storageClassName` cannot move an already-bound PVC. Pinned
Operator `v0.90.1` responds to immutable StatefulSet update errors by deleting
that StatefulSet with foreground propagation, then recreating it. Both the
Prometheus and Alertmanager controllers use this shared updater. This is
controller reconciliation of committed desired state; no operator-issued
StatefulSet deletion is required.

A new `storage.volumeClaimTemplate.metadata.name` also changes the mounted
claim name in both pinned controllers. Use new names such as `prometheus-local`
and `alertmanager-local`, with separately declared retained PV/PVCs whose names
match `<template-name>-<existing-statefulset-name>-0`. Never rebind or overwrite
the old PVC. The chart renders storage, zero replicas, init containers, and
retention policy directly from its values.

Sources: [pinned StatefulSet updater](https://github.com/prometheus-operator/prometheus-operator/blob/v0.90.1/pkg/k8s/statefulset.go#L63-L94),
[Prometheus claim naming](https://github.com/prometheus-operator/prometheus-operator/blob/v0.90.1/pkg/prometheus/common.go#L333-L340),
[Alertmanager storage](https://github.com/prometheus-operator/prometheus-operator/blob/v0.90.1/pkg/alertmanager/statefulset.go).

## Proposed GitOps Sequence

Run Prometheus and Alertmanager migrations separately. Each numbered phase
requires a distinct reviewed revision and observed live gate; Argo sync waves
alone are not evidence that the prior writer stopped.

1. **Prepare without changing active storage.** Add retained target PV/PVCs,
   checkpoint/verification storage, and bounded migration/restore Jobs through
   the Prometheus Application's repository Kustomize source. Use the existing
   `media-postgres/local-storage.yaml` static local pattern only after the target
   hardware is accepted. A dedicated block device needs its own declared Talos
   provisioning path; do not repartition the control-plane disk implicitly.
   Preserve old and new claims with `Prune=false,Delete=false` and explicit
   StatefulSet `Retain` policies. Verify binding, ownership, capacity, and a
   repository-owned write/recreate smoke test on the new target.
2. **Fence one writer.** Commit that CR's `replicas: 0`, keeping `paused: false`.
   Pause would prevent the operator from processing the fence. Observe the
   exact CR generation, StatefulSet desired/actual zero, no owned Pods including
   terminating Pods, and no other writable mounts of either data claim. Preserve
   the existing 600-second Prometheus and 120-second Alertmanager shutdown grace.
   The checkpoint Job must independently reject a missing fence before writing.
3. **Checkpoint and prove restore.** Mount the old claim read-only. Create a
   dated immutable archive of its complete cold directory, including Prometheus
   WAL/head data and Alertmanager silences/notification log. Publish checksums
   atomically and verify the source inventory remains unchanged. Restore the
   archive into separate disposable scratch and boot the exact application
   version with no external network, scrape targets, rules, remote writes, or
   notification receivers. Verify successful WAL/state replay, historical
   query/time-range invariants or silence-state invariants, and clean shutdown.
   Do not call a checksum-only copy a restore proof. Preserve the source and
   archive if any check fails; the production writer stays fenced.
4. **Prepare new storage while still fenced.** Commit the new claim-template
   name, storage class, verified node affinity, and startup guard; keep replicas
   zero. Let the operator recreate the empty StatefulSet and verify its PVC
   references. A separately gated Job restores the verified checkpoint into an
   empty staging directory on the target, normalizes ownership to `1000:2000`,
   verifies content, and atomically publishes data plus a completion marker. It
   must never overwrite an existing target or report completion while a writer
   is active. The runtime init guard refuses startup without the matching
   verified marker; only the migration Job can publish it.
5. **Start and verify one writer.** After the restore Job has completed and no
   copy writer remains, commit replicas one. Confirm the sole Pod mounts the
   new claim on the verified node, startup replay succeeds, historical data and
   current ingestion survive, and no unsupported-filesystem warning returns.
   For Alertmanager, verify retained silences/notification state and the existing
   Grafana/Prometheus routing. Notification delivery testing needs its normal
   explicit authorization. Start the second workload's sequence only afterward.
6. **Soak and restore normal bootstrap.** Keep original claims, checkpoints,
   and rollback data through the documented soak and a successful new backup
   and restore cycle. Remove incident-only Jobs and startup guards in a later
   reviewed cleanup revision so a fresh cluster retains the documented one-apply
   bootstrap. Do not delete historical PVs as part of that cleanup.

Prometheus recommends snapshots for recurring live backups and warns that
omitting WAL/head data loses recent samples. The cold checkpoint above avoids
an inconsistent live directory copy. A declared recurring snapshot/copy path,
its restricted API authority, and independent target remain design gates;
never silently replace them with copying a live TSDB directory.
See [upstream storage guidance](https://prometheus.io/docs/prometheus/latest/storage/).

## Resource And Capacity Gates

Prometheus currently has no requests or limits; observed steady state is roughly
`80m` CPU and `1Gi` working memory. Initial **test budgets**, not validated final
limits, are Prometheus `250m` CPU / `1536Mi` memory requests, Alertmanager `25m`
CPU / existing `200Mi` memory request, and a serial verification Job with
`250m` CPU / `1536Mi` requests and `1` CPU / `3Gi` limits. A streaming copy Job
can start with `100m` CPU / `128Mi` requests and `1` CPU / `512Mi` limits.
Measure compaction and cold WAL replay peaks before approving runtime limits;
do not impose a low CPU ceiling from the steady-state sample.

Keep `15d` and `120h` retention and the `50Gi`/`10Gi` capacity contracts. Budget
those capacities plus two additional measured dataset copies for checkpoint and
isolated restore, while retaining the node's normal disk reserve. Validate
filesystem free space directly: static hostPath capacity requests neither
reserve nor cap bytes. A future size cap must leave compaction/WAL headroom and
must not shorten the promised history; halt for capacity if both cannot fit.

Current node-loss memory headroom is already insufficient; see
[[audit-2026-09-04]]. Node-local volumes also prevent automatic rescheduling onto
another node. Explicitly document recovery time and measured spare resources;
this migration cannot claim HA or node-loss tolerance.

## Rollback And Remaining Decisions

Before any new writes, fence the replacement and return the CR to the retained
original template only after verifying its checkpoint identity. Once local
writes begin, the old NFS copy is stale. Fence the local writer, take and prove
another complete checkpoint, restore into a **new retained rollback claim**,
and change the template name again while replicas remain zero. Start only after
the same content and single-writer gates pass. Preserve both prior copies.
Returning to NFS is an emergency rollback with its original reliability risk,
not completion of the storage repair.

Required decisions: tested healthy storage hardware/placement; accepted
maintenance interruption and rollback RPO/RTO; a capacity/reservation budget
validated under replay/compaction; independent backup destination and recurring
backup authority; exact private restore invariants. Until those gates pass,
keep this plan a draft and current persistent data untouched.
