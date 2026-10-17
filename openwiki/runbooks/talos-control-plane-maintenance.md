---
type: runbook
title: "Talos Control-Plane Maintenance"
description: "Authenticated Talos maintenance, etcd snapshot integrity, macOS backup scheduling, retention, offsite publication, and recovery limits."
tags: ["runbook", "talos", "maintenance"]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-11T00:16:41.141Z
sources:
  - id: openwiki-source-827cecf9eca9139ac8e7367a
    resource: repo://clusters/homelab/apps/langfuse/values.yaml
  - id: openwiki-source-2d8396976c82220440798f1a
    resource: repo://clusters/homelab/apps/n8n/README.md
  - id: openwiki-source-5eb041b69ecfffa36cf7ffbb
    resource: repo://clusters/homelab/apps/n8n/values.yaml
  - id: openwiki-source-e84e79af70aa76ff1e5928ad
    resource: repo://docs/argocd-node-pressure-2026-10-10.md
  - id: openwiki-source-b1ffa4114052aa5dfacab93d
    resource: repo://docs/talos-control-plane-maintenance.md
  - id: openwiki-source-f585f8850806deb1619ec0c5
    resource: repo://IaC/.catalog/units/bootstrap/argocd/terragrunt.hcl
generated: { by: "codex", at: "2026-10-11T00:16:41.141Z" }
---

# Talos Control-Plane Maintenance

Canonical runbook: [`docs/talos-control-plane-maintenance.md`](../../docs/talos-control-plane-maintenance.md)

The [routine etcd backup runbook](../../docs/talos-etcd-backup.md) owns
`scripts/talos-etcd-backup.py`: authenticated snapshot download to a private
off-node directory, Talos metadata validation, embedded SHA-256 verification,
and an offline manifest check. It preserves existing backups and contains no
restore or cluster mutation path. Success requires file and directory syncs;
the homelab invocation explicitly selects Homebrew Talos `v1.11.3` because the
Nix shell currently supplies `v1.13.2`. The CLI requires an absolute executable
client path and rejects missing or invalid clients before Talos access.
The [macOS schedule](../../docs/talos-etcd-schedule.md) declares hourly calendar
checks plus load/wake catchup, a 24-hour verified-success gate, a 36-hour offline
freshness threshold and 28-day retention with at least seven valid scheduled
copies. Its installer copies exact reviewed main code to a private durable
operator runtime; a separate `scheduled` child protects all manual backups.
Service updates preserve prior files and loaded state for rollback. The launchd
child waits up to 60 seconds for handoff; an active backup blocks reconfiguration.
Changing the committed launchd label requires uninstall and a fresh runtime;
updates reject renames before touching the old service or installed release.
Pruning starts only after a new verified durable backup and success receipt,
and all candidates pass verification. Installation on 2026-09-07 matched the
merged source and loaded plist; the first automatic `RunAtLoad` snapshot
completed at `17:17:10 UTC`, passed offline checks and reported `fresh` with
launchd exit zero. All four manual backups remained unchanged and reverified;
no copies were pruned. Read-only follow-up on 2026-09-12 found five scheduled
successes dated September 7–11, with the latest snapshot `fresh` and the agent
loaded. The longest observed interval was 26 hours 54 minutes; two logged
failures recovered automatically. Exact causes and wake behavior remain
unverified; see the schedule runbook for the bounded recurrence evidence.
The Mac must be available and its user logged in; unattended offsite
publication, remote age-alert delivery and an isolated control-plane recovery
drill remain open work.

Live validation on 2026-09-07 UTC saved private off-node snapshots with Talos
`v1.11.3`; embedded and full-file checksum checks passed. The separately
[validated offline restore](../operations/etcd-offline-restore-validation.md)
preserved one post-upgrade snapshot's revision and MVCC key count. That
database check did not start a control plane or verify an offsite copy.
The first scheduled snapshot separately passed
[manual S3 publication and retrieval](../operations/etcd-offsite-publication.md)
of exact versions with independent checksum checks. That downloaded copy has
not undergone a database restore.

Render and validate Talos configuration before applying it. Use
`talosctl validate --mode metal --strict`, authenticated access after bootstrap,
and repository-owned patches for control-plane changes.
Emergency recovery does not permit live machineconfig edits followed by
backfilling; use the validated patch workflow first.
Remote `talosctl` will use owner-only Octelium TCP Service
`talos-api.homelab` after the control-plane `machine.certSANs` patch is applied
and the off-LAN check passes. Talos mutual TLS remains required. Until then,
direct-IP operations require the LAN or temporary Tailscale subnet route;
direct IP remains the LAN recovery path after cutover.

For remote ZimaBoard recovery, the canonical runbook maps each worker to its
Talos address and uses authenticated `talosctl reboot`; reboot one worker at a
time only from a healthy cluster, verify node and cluster-wide workload
readiness, and never fall back to `--insecure`.
The control-plane issuer cutover also requires an explicit all-node Ready wait
before rebooting the sole control-plane node.
After Acer returns, defer the global Pod gate only for verified old-issuer CNI
failures: reboot `zimaboard-2`, `zimaboard-1`, then `zimaboard-0`, require
target-local Pod readiness after each, and restore the global gate after the
last worker. Before each reboot, require the full node/Talos/etcd preflight and
allowlist every unready Pod only after its failure is positively traced to an
old-issuer CNI authorization error on an unrebooted worker. Rebuild the
UID-and-node-bound exact allowlist at every step; any missing, stale,
duplicate, or unlisted entry stops the sequence. A fixed worker-name mapping
and fail-closed checks require every non-dashboard Talos service to report
running and healthy before reboot. This exception does not apply to unrelated
degraded workloads.

The 2026-09-02 issuer incident has a narrower stalled-worker recovery. Stale
CNI authentication caused Pod churn, then memory, eMMC, and NFS pressure wedged
the `zimaboard-1` kubelet. `zimaboard-2` showed severe pressure and a concurrent
kubelet stall, but its exact cause is unverified. Acer and `zimaboard-0` stayed
healthy. Because API-deleted NFS Pods may still execute, the worker reboot is
writer fencing. After validating the healthy cluster, preserve but stop the
known Cordium Workspace `v64` through its native lifecycle API; `ws-v64` is its
generated Kubernetes name. Reject an ephemeral Workspace, prove the exact PVC
remains bound, require its ConfigMap, Service, and Deployment to disappear,
and allow only zero-replica controller remnants or deleting Pods. Then recover
`zimaboard-1` once and require a new boot ID, fresh lease, healthy services and
Pods, no fresh issuer errors, and 31 clean one-minute pressure samples before
recovering `zimaboard-2`. A timeout permits physical power only
after the same boot ID and healthy remainder of the cluster are revalidated;
never submit a second remote reboot. Keep `zimaboard-0` running when healthy.
The required 30-minute soak checks each minute for over 20% available memory,
no blocked processes, less than 1% full memory or I/O stall time over avg60,
no Pod replacement, container-set change, restart or OOM growth, and no active
Cordium workspace on `zimaboard-1`. This duration covers the incident's
observed 18–30 minute failure lag.

On 2026-10-10, `zimaboard-2` twice lost kubelet heartbeats under memory and
I/O pressure. During the first stall an Argo CD application controller used
about 658 MiB and NFS-backed n8n PostgreSQL and NOFX Pods were still bound to
the node, so the no-PVC remote-reboot exception below did not apply. Talos
became unreachable; a physical power-cycle of that exact worker restored it.
The second stall followed a Langfuse worker of about 495 MiB landing beside a
634 MiB Argo controller. Kubernetes later moved the heavy Pods and kubelet
recovered without another manual mutation. The repository excludes this
undersized worker from Argo CD components and the Langfuse worker through
required node affinity. Verify the deployed Helm release, Argo Application,
Pod nodes and node pressure before treating that mitigation as live. The
[Argo reconciliation incident](../../docs/argocd-node-pressure-2026-10-10.md)
records the second stall's exact timeline.

One capacity risk remains outside this placement change: the
[`n8n` controller](../../clusters/homelab/apps/n8n/values.yaml) has no node
affinity, requests 512 MiB, and permits 2 GiB on a worker with 1.28 GiB
allocatable. After the webhook migration, measure its steady and peak use and
review placement or its memory budget through GitOps. Its `Recreate` rollout
can register active hooks at startup, so verify the
[callback route](../../clusters/homelab/apps/n8n/README.md) before restarting it.

Other capacity follow-up remains after recovery. `zimaboard-1` scheduled requests
were 82% of allocatable memory but limits were 627%; OpenClaw and the active
Cordium workspace alone could exceed node capacity, while Octelium Enterprise
used several 5 MiB or empty requests. Historically, `zimaboard-2` ran
BestEffort Prometheus and Argo CD components on 1.28 GiB allocatable memory.
Measure recovered usage, then correct requests, limits, or capacity in
[`openclaw/values.yaml`](../../clusters/homelab/apps/openclaw/values.yaml),
[`octelium-enterprise/resources.yaml`](../../clusters/homelab/apps/octelium-enterprise/resources.yaml),
and [`prometheus/values.yaml`](../../clusters/homelab/apps/prometheus/values.yaml).
Do not invent limits while metrics are unavailable.

The canonical runbook also owns the dated 2026-08-25 corrupt-object recovery.
That recovery is exact-key and snapshot-first, with a Talos snapshot-restore
rollback; do not generalize it into a routine etcd mutation path.

See [Cluster Topology](../architecture/cluster-topology.md) and [Validation](validation.md).
