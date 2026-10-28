---
type: operation
title: "OpenClaw Runtime State"
description: "OpenClaw local SQLite and NFS ownership, Talos subPath mount failures, identity locks, backup checks, and recovery limits."
tags: ["operations", "openclaw", "storage"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-27T21:30:24.345Z
sources:
  - id: openwiki-source-ab3ca049e4829053c335f750
    resource: repo://clusters/homelab/apps/openclaw/retirement-reader.yaml
  - id: openwiki-source-00d374aa17b82a33b8b28024
    resource: repo://clusters/homelab/apps/openclaw/runtime-backup.yaml
  - id: openwiki-source-3cde14b4d4650496e1c0d25d
    resource: repo://clusters/homelab/apps/openclaw/runtime-storage.yaml
  - id: openwiki-source-b26876230e53fd853d7bcbea
    resource: repo://clusters/homelab/apps/openclaw/values.yaml
generated: { by: "codex", at: "2026-10-27T21:30:24.345Z" }
---

# OpenClaw Runtime State

Status: legacy gateway stopped. Its runtime backup CronJob is suspended, and
the retained local/NAS claims are mounted by a read-only retirement reader.
Recovery rehearsal remains separate from this historical runtime design.

Configuration, workspace, archived transcripts and recovery archives use the
retained `openclaw` NFS claim. Global state, agent SQLite databases and native
Codex state use retained local volumes on `zimaboard-1`. Platform storage owns
the StorageClass and PVs; the OpenClaw application owns the namespaced PVCs.
Local WAL state survives Pod replacement, but has no automatic node failover.
The former daily online SQLite backup retained seven snapshots on NFS; its
CronJob is now suspended. Node-disk loss needs
a verified snapshot restore and can lose writes since the last backup.

## Direct Mount Identity

Talos kubelet mount namespaces can expose empty overlay directories through
`subPath` even when a host directory contains valid databases. Direct child PVs
mount the existing host directories without `subPath`; bootstrap requires parent
and child views to identify the same database inodes before starting a CLI.
Missing local databases stop startup and require reviewed restoration. Never
silently refill current state from stale NAS data.

The retained bootstrap source verifies its versioned offline backup, runtime database
integrity and mount identity before applying configuration. Existing archives
remain private recovery data. A shared UID-private Pod-local coordinator volume
keeps identity locks off NFS; single-replica `Recreate` and same-Pod writer
ownership remain required.

On 2026-10-06, cleanup-triggered cold starts passed init, database-integrity
and mount-identity gates, but native model-runtime publication repeatedly hit
its 120-second agent-facts deadline during event-loop stalls. The rollout
investigation recorded about 2 GB read and 897 MB written for roughly 204 MB
of databases, including synchronous SQLite snapshot staging. Image and resource
limits were unchanged, configuration was valid, and removed migration guards
had already completed. A retained Codex migration warning coexisted with the
failure; causality is unproven.

The same investigation verified that `/home/node/.cache/openclaw` readonly-v2
snapshots use container overlay, not NFS. Canonical shared and agent databases
use local XFS on `/dev/mmcblk0p4`; only the `/data` root is NFS. Moving that
snapshot cache to `emptyDir` has no demonstrated NFS benefit; no filesystem
change is proposed on this evidence.

Separately, Kubernetes events record two startup-probe kills; one app attempt
ran from 05:09:10 to 05:15:10 UTC before exit 137. The declared startup budget
is now 900 seconds instead of six minutes; readiness and liveness are unchanged.
This removes that premature termination boundary, not the native timeout.
Any isolated compatible boot still requires actual gateway responsiveness and
Pod readiness before T014 can be accepted.

Source: [OpenClaw runbook](../../clusters/homelab/apps/openclaw/README.md).
See [OpenClaw bootstrap batching](openclaw-bootstrap-batching.md) for startup timing and configuration gates,
[OpenClaw personal assistant](openclaw-personal-assistant.md) for assistant behavior, and
[Storage And State](../architecture/storage-and-state.md) for backup limits.
