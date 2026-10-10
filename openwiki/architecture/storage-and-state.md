---
type: architecture
title: "Storage And State"
description: "Etcd recovery, QNAP NFS and local volumes, workload backup ownership, and unresolved storage and restore gates."
tags: ["architecture", "storage", "stateful"]
---

# Storage And State

LiteLLM's prepared UI-key migration adds `ai/data-litellm-postgres-0`, a 20 GiB
NFS claim for its dedicated PostgreSQL database. Preserve logical dumps, volume
snapshots and SSM role passwords together. Key import and native-auth cutover
remain separate acceptance gates; see the
[LiteLLM runbook](../../clusters/homelab/apps/litellm/README.md).

The operator-owned `IaC/operator/state-bucket-encryption` unit manages only
the existing S3 state bucket's encryption configuration, enabling S3 Bucket
Keys while preserving both SSE-KMS and OpenTofu client-side encryption. See
[State Encryption](../operations/state-encryption.md) for configuration, recovery, and rollback.

The same bucket holds confidential AWS-managed-encryption recovery archives
for 128 SSM versions and 60 old homelab state versions under
`IaC/homelab/migrations/`. Preserve these recovery copies. Archive
objects contain secret material and must never be copied into this public repo.

## Control-Plane Recovery State

The single control-plane node `acer` owns the Kubernetes etcd database.
The [routine backup command](../../docs/talos-etcd-backup.md) saves a new private
off-node snapshot and verifies metadata, the embedded SHA-256 checksum, and a
full-file manifest digest. Operators choose an existing durable mode-0700
directory outside Git; the command retains every completed backup.
The separate [macOS scheduler](../../docs/talos-etcd-schedule.md) declares roughly
daily snapshots, hourly retries/load/wake catchup, offline 36-hour freshness
checks and 28-day retention with a seven-valid-copy minimum. It reserves a
private `scheduled` child, preserving all manual siblings; failed backup or
verification prevents pruning. Exact reviewed code is installed to a durable
operator runtime. On 2026-09-07, installed sources and the loaded plist matched
the merged revision, and the first automatic `RunAtLoad` snapshot passed
offline checksum/freshness checks. All four manual backups were preserved and
reverified; no copies were pruned. A 2026-09-12 read-only follow-up found five
scheduled successes dated September 7–11, with the latest snapshot `fresh` and
the LaunchAgent loaded. The longest success interval was 26 hours 54 minutes;
two logged failures recovered on later scheduled attempts. See the schedule
runbook for this scoped recurrence evidence and its remaining wake/availability
limits. Private receipts retain both observations.
The Mac's availability, unattended offsite freshness, remote alert delivery,
an isolated control-plane recovery drill and control-plane redundancy remain
gaps. PVC data and private Talos recovery material need separate backups; an
etcd snapshot alone cannot recover either.

The 2026-09-07 [maintenance](../operations/kubernetes-patch-maintenance-2026-09.md)
used a fresh verified off-node snapshot after the DNS handoff. All five
scheduled media/Octelium backups had completed their latest due run, and their
published artifacts remained present on retained NFS claims. Publisher-time
validation plus current file metadata does not constitute a fresh rehash or
restore drill.

After Kubernetes `1.34.11`, direct kubelet and Prometheus checks covered all 28
expected mounted node/PVC pairs across 30 Pod bindings; all 50 claims were Bound.
Unmounted claims are outside that metric inventory. Grafana's current PVC rule
state remains unverified because its admin API returned HTTP 401, although the
unchanged alert query returned real data below its threshold.

The dedicated [etcd offsite storage](../operations/etcd-offsite-storage.md) operator
unit declares a private, versioned S3 bucket with independently owned retention.
Its reviewed saved plan applied on 2026-09-07 with seven additions and no
changes or destruction; bucket metadata checks and provider refresh/no-drift
validation passed. The separate
[manual publisher](../operations/etcd-offsite-publication.md) then copied the first
scheduled snapshot and retrieved its exact S3 versions; independent remote
metadata and local checksum checks passed with the source preserved. One
earlier manual post-upgrade snapshot passed
[offline database restoration](../operations/etcd-offline-restore-validation.md).
These are distinct snapshots and checks; neither proves control-plane or PVC
recovery. The separate [offsite attempt scheduler](../../docs/etcd-offsite-schedule.md)
now has a reviewed-code installation path, private resumable attempts and
source-age status, but no installed schedule or real recurring execution has
been verified. It uses existing expiring AWS SSO sessions; remote alerting and
indefinite unattended identity remain unresolved.

## Durable Storage

Fleet keeps dedicated MySQL and Redis state on retained `nfs-default` claims.
A separate retained NFS claim receives nightly transaction-consistent MySQL
dumps with 14-day retention. A PostSync Job verifies the first backup after
bootstrap. Both paths atomically publish a timestamped directory containing
`fleet.sql` and its verified checksum; failed attempts never prune prior sets.
The server and dump client both allow 512 MiB packets for MDM package data.
Database restore also needs the stable Fleet server
key and enrolled platform identities. These copies share the QNAP failure domain;
offsite coverage and an isolated restore drill remain unverified. See the
[Fleet backup and restore contract](../../clusters/homelab/apps/fleet/README.md#secrets-and-storage).
When the [AirVPN operator](../../clusters/homelab/apps/fleet/WIREGUARD-AIRVPN.md)
is used, Fleet command data and backups can also contain client VPN keys.
Removing a device profile does not erase historical backups or revoke the
AirVPN key; protect those backups as credential-bearing data.

Kubernetes persistent storage is backed by a QNAP NFS export.

| Setting        | Value                  |
| -------------- | ---------------------- |
| NAS address    | `10.1.0.2`             |
| Export         | `/homelab`             |
| StorageClass   | `nfs-default`          |
| Provisioner    | `k8s-sigs.io/qnap-nfs` |
| Reclaim policy | `Retain`               |
| Mount option   | `nfsvers=3`            |

`platform-storage` owns the parent Argo CD Application, and the child
`nfs-subdir-external-provisioner` Application owns the StorageClass.

Cordium Workspaces are the deliberate exception to the NFS default. The
`cordium-local` StorageClass dynamically provisions disposable `hostPath`
volumes under `/var/lib/cordium-workspaces` on `zimaboard-1`. Rootless Podman
requires private ownership and mode bits for its runtime directory, which the
QNAP NFSv3 export does not preserve. These volumes use a `Delete` reclaim
policy and have no replication or backup; they are development scratch space,
not durable workload storage. The provisioner and its `hostPath` helper Pods
run in the dedicated privileged `cordium-storage` namespace so the broader
`storage` namespace can keep baseline Pod Security enforcement.
The Cordium worker patch also sets `user.max_user_namespaces=28633` only on
`zimaboard-1`, because each Workspace starts a rootless Podman container and
Talos otherwise disables the required user namespaces. The Cordium Application
also owns a node-pinned DaemonSet whose root init container can write only that
host sysctl file whenever GitOps or a node reboot recreates the Pod. The init
container is privileged because Talos protects host sysctls even from UID 0;
the steady-state container is unprivileged and exposes readiness from the live
value.

`media-postgres` is an explicit exception. Its active 20 Gi volume is a
retained static `hostPath` PV at `/var/lib/media-postgres`, pinned to `acer`;
the former NFS data claim remains retained for verified nightly logical backups
at 03:00 `America/Los_Angeles` with 14-day retention. The local volume removes
QNAP latency from the live database but couples recovery to the single
control-plane node and its system disk. GitOps explicitly declares the retained
`data-media-postgres-0` claim with `Prune=false,Delete=false`, so clean bootstrap
creates the backup target independently of the active StatefulSet.

Media-library paths are intentionally separate from app state. Deluge, Radarr,
and Sonarr keep active app config on retained local volumes pinned to
`zimaboard-0`, while using retained NFS claims as nightly archive targets. Their media paths still use static PV/PVC pairs against the
QNAP `/media` export for downloads, movies, and TV library data. Read-only
`showmount -e 10.1.0.2` verified `/media` and `/homelab` on 2026-05-26.

Bazarr follows the media config pattern: retained local config/SQLite state on
`zimaboard-0`, a separate retained NFS backup claim, and existing `media-tv` and
`media-movies` claims mounted at `/tv` and `/movies`. Subtitle files are written
beside the media files and belong to the NAS media backup scope; config/database
archives alone do not protect captions. The init container reads Sonarr/Radarr
local config claims read-only to obtain their API keys; the runtime container
does not mount those claims. See the
[Bazarr runbook](../../clusters/homelab/apps/bazarr/README.md) for backup,
recovery, and live acceptance gates.

Read-only inspection during Bazarr onboarding on 2026-10-04 found registered
media hidden from Sonarr by owner-1000 directories with mode `0770`. The QNAP
export squashes every NFS client to guest, so container groups cannot repair
this. The preview-first `scripts/nas-media-permissions.py` helper limits owner-side
permission repair to registered Arr paths, requires reviewed current `main` and
a private original-mode journal, and can queue Arr rescans afterward. Follow the
[NAS access procedure](../../clusters/homelab/apps/bazarr/README.md#nas-media-access)
and verify the imported library afterward. Future owner-side media copies must
preserve guest traversal/read access and directory write access for sidecars.

## Stateful Workload Gate

The existing QNAP is also an unproven iSCSI block-storage candidate for
monitoring. See [QNAP Block Storage Candidate For Monitoring](../operations/qnap-monitoring-block-storage-research-2026-09-12.md)
for pinned driver compatibility, missing Talos/NAS prerequisites, and retained
restore/fencing gates. No storage class or active workload has changed.

Stateful workloads can be registered before they are considered operationally
ready, but they must not be treated as production-ready until:

1. `platform-storage` is synced and healthy.
2. `nfs-default` exists and provisions PVCs correctly.
3. A PVC write, delete, and recreate smoke test has passed or an exception is
   recorded.
4. Backup and restore expectations are documented in `docs/storage-nfs.md`.

## Open Audit Findings

- **Status:** open
- **Area:** storage / backup and retained data
- **Evidence:** Read-only inspection on 2026-08-27 found Prometheus and
  Alertmanager on `nfs-default`; Prometheus warns that `NFS_SUPER_MAGIC` is
  unsupported and can cause data corruption or loss. All 37 `nfs-default`
  PVCs, three `media-qnap-static` claims, and the provisioner's NFS claim are
  bound, but the repository proves neither an independent off-NAS backup nor a
  tested restore. Eight `Released` PVs retain old data, and the QNAP still
  advertises NFSv2 even though Kubernetes mounts NFSv3.
- **Risk:** Monitoring data can corrupt, a NAS failure can remove every copy,
  and blind retained-volume cleanup can destroy unrecovered data.
- **Next step:** Choose an independent backup target and prove restores. Move
  Prometheus and Alertmanager through a backed-up, fenced migration to
  supported repo-owned block or local storage. Map each retained PV before
  owner-approved cleanup. Add a declared QNAP management path before disabling
  NFSv2, and first confirm no other client needs it.

## Stateful Apps

AFFiNE remains suspended for memory capacity, including its PostgreSQL and Redis
workloads; its four PVCs remain retained. Dispatcharr now declares one app and
one dedicated PostgreSQL replica for IPTV-org USA setup, reusing its two retained
PVCs. No durable data is removed. See [Monitoring Resource Requests](../operations/monitoring-resource-requests.md)
and the app READMEs for capacity, suspension and resume checks.

The current stateful set includes AFFiNE with PostgreSQL/pgvector, ephemeral
Redis, blob storage, and config state; Prometheus, Grafana, Deluge, Dispatcharr
with dedicated PostgreSQL, media-postgres, Multica with pgvector PostgreSQL and
backend upload PVCs, n8n-postgres, octelium-storage PostgreSQL/Redis, Octelium
Enterprise package stores (`octelium-rscstore`, `octelium-logstore`,
`octelium-metricstore`), Prowlarr, Radarr, Sonarr, LiteLLM, OpenClaw, n8n,
NOFX SQLite state, and OctoBot. OpenClaw keeps configuration and workspace on
its retained NAS claim, but its global state, per-agent SQLite databases, and
native Codex home use `openclaw-runtime-local` on `zimaboard-1`. The
platform-storage application owns its StorageClass and PV;
the namespaced OpenClaw application owns its PVC. This permits
local WAL and preserves native bindings across Pod replacement. Daily SQLite
online backups keep
seven database snapshots on the NAS. The local hostPath survives Pod replacement
but not node-disk loss; there is no automatic node failover and recovery can lose
writes since the last backup. Native caches are reconstructed on disaster restore.
See the OpenClaw app README and [OpenClaw Runtime State](../operations/openclaw-runtime-state.md).
Langfuse runs chart `2.1.1` in its own `langfuse` namespace for traces, token
usage, and prompt logs. The overlay directly runs single-replica PostgreSQL
(`20Gi`), Valkey (`8Gi`), and ClickHouse (`100Gi`) on retained `nfs-default`
PVCs; it does not install a database operator. A dedicated S3 bucket shared by
raw events, uploaded media and batch exports expires all objects after 30 days
(noncurrent versions after 7 days), including media links and export downloads.
Neither that lifecycle policy nor the retained
PVCs is an independent backup: no automatic logical backup is configured, and
restore coverage remains unverified.
The October 5 ClickHouse quarantine disables six corrupt diagnostic log tables
and permanently detaches them without deleting their files. Repeated merge
failures caused shared-NAS metadata pressure; application tables remain attached.
See [QNAP Plex Recovery](../operations/plex-recovery-2026-10-05.md) and the Langfuse README for rollout
acceptance and the separate repair required before reattachment.
The retained 1Gi `langfuse-migration-recovery` claim holds private recovery
artifacts. Keep it independently of application rollout; it is not an automatic
backup or an independently verified restore.
The October 10 Valkey capture stage stops Langfuse web/worker/Valkey, mounts
the queue PVC read-only, and captures its complete files to private off-NAS
storage. Hash-verified originals remain separate from candidate AOF repair.
No live queue replacement or general backup coverage is enabled; measured loss
and explicit approval are required before restoration. See the
[capture runbook](../../clusters/homelab/apps/langfuse/README.md#valkey-offline-capture-and-candidate-inspection).
The Octelium Enterprise package stores are DuckDB-backed single-writer stores,
so their Deployments must use `Recreate` rather than rolling updates.
The resource-store manifest in `clusters/homelab/apps/octelium-enterprise`
also declares `initContainers: []` and scoped
`Replace=true,ServerSideApply=false`. Live inspection
on 2026-10-06 found an obsolete init container retained under an earlier field
manager despite Argo CD reporting Synced. Server-side dry runs with an empty
list retained that container; a replacement dry run omitted it while preserving
`Recreate` and the existing `octelium-rscstore` claim. The explicit apply-mode
override also creates a desired-state difference when the old live resource
already has `Replace=true`; an empty init list alone was reported Synced and
did not trigger replacement.
Multica PostgreSQL now follows the recovered NFS database probe pattern:
30-minute startup and liveness windows, SQL-query readiness, and 120-second
shutdown grace. Its image, credentials, scheduling, and PVC are unchanged.
This prevents short liveness windows from interrupting recovery; it does not
resolve the underlying NFS reliability or backup risks.

The Multica runtime declares an independent 10 Gi retained static volume at
`/var/lib/multica-runtime` on `acer` for CLI identity, agent state, and workspaces.
`clusters/homelab/platform/storage/multica-runtime.yaml` owns its StorageClass
and PV; `clusters/homelab/apps/multica/runtime-storage.yaml` owns the
`ai/multica-runtime-local` claim. Local storage preserves private file ownership
and locking without sharing OpenClaw state. `Retain` and Argo CD
`Prune=false,Delete=false` preserve the claim and data through application
removal, but provide neither off-node backup nor automatic failover. The 10 Gi
capacity is a scheduling declaration, not a filesystem quota. Back up the
runtime independently before relying on recovery from node or disk failure.

The latest rscstore recovery preserves the unreplayable 2026-08-26 DuckDB WAL
by renaming it on the retained PVC before starting from the last valid
checkpoint. A new completion marker leaves the earlier 2026-08-21 recovery
artifacts untouched and makes retries read-only; quarantined WALs are not
deleted automatically. Recovery fails closed rather than overwrite a dated
quarantine if its completion marker is missing.

AFFiNE Redis deliberately disables AOF and RDB persistence and uses node-local
`emptyDir` storage, matching the upstream deployment's ephemeral Redis model.
This prevents per-second AOF `fsync` calls and snapshot/AOF rewrite bursts from
reaching the QNAP. PostgreSQL remains durable on NFS with WAL compression and
checkpoint pacing; synchronous commit remains enabled. The former Redis AOF
claim remains retained for rollback but is no longer mounted by Redis.

`affine-postgres` was fenced at zero replicas during the first phase of the
2026-07-20 stale-lock recovery; live validation confirmed the pod was absent
and its retained PVC stayed bound. The second phase declares that claim as an
early Argo CD resource and used the idempotent
`affine-postgres-stale-lock-recovery-20260720` Sync hook to remove only
`postmaster.pid` before Argo CD restored one replica. The hook wrote a durable
completion marker on the PVC, PostgreSQL completed crash recovery, and live
validation passed with zero pod restarts. The incident-only hook is now removed
from desired state, while the explicit retained claim, 30-minute startup and
liveness windows, and 120-second termination grace remain.

`n8n-postgres` completed its fenced 2026-08-03 stale-lock recovery. The
incident hook removed only `postmaster.pid`, wrote a durable marker, and
restored one replica with zero PostgreSQL restarts. Live checks passed for SQL,
n8n readiness, and the public callback. The hook is now removed; the explicit
retained claim, 30-minute startup and liveness windows, and 120-second
termination grace remain.

### Pending n8n PostgreSQL upgrade

On 2026-10-05 PDT, `n8n-postgres` was still pinned to PostgreSQL 14.23 while
n8n reported PostgreSQL 14 as unsupported (17+ supported; 16 compatibility
only). Availability recovered, but schedule a reviewed major-version migration:
take a logical database dump and n8n PVC backup, restore into PostgreSQL 17+
instead of changing the major image in place, then verify SQL, n8n readiness,
and the public webhook before retiring the old PVC.

`media-postgres` uses 30-minute startup and runtime liveness windows plus a
120-second termination grace period. Its readiness and liveness probes execute
`SELECT 1` instead of treating socket acceptance as usable database service.
The active `media-postgres-local` StatefulSet mounts only local storage. The
`media-postgres-recovery` overlay fences the writer and backup schedule before
a logical restore. See `clusters/homelab/apps/media-postgres/README.md` for the
failure mode and operator response.

`octelium-postgres` keeps the 30-minute startup window but uses a 90-second
runtime liveness window. Its readiness and liveness checks execute `SELECT 1`,
preventing a server that accepts connections but cannot execute queries from
remaining falsely healthy. It is pinned to `zimaboard-1` to avoid the worst
observed NFS client path, but QNAP NFS remains a database availability risk.
Its availability is required for Octelium service publication, including the
CI Kubernetes API tunnel. A daily CronJob writes PostgreSQL globals without
password hashes, a custom-format database dump, and checksums to the separate
retained `octelium-postgres-backup` NFS claim. It verifies the dump before
atomic publication and retains 14 days. This is a logical recovery checkpoint,
not an off-NAS backup. The proposed restore drill lives in
the separate `octelium-storage/restore-drill-candidate/` kustomization, excluded
from the live application and additionally suspended. It declares
a daily 04:45 UTC schedule after the backup's full late-start/runtime window and
requires the newest complete PostgreSQL set to be from the current UTC day. It restores
into disposable local scratch using the custom archive's database creation
metadata, preserving encoding, collation, character classification, and owner;
the bootstrap cluster's C locale does not replace the source locale. It
checks resource identities, encrypted-resource key references, and index validity.
It mounts only the backup claim read-only, injects no production credentials or
live Kubernetes Secrets, and has a 30-minute deadline. The backup itself contains
sensitive material. Restore processes discard the original container log handles
before archive processing; exit status reports completion, while stage and
database diagnostics stay in disposable scratch. The direct entry point and
private PID namespace must not acquire a console-bearing wrapper or peer that
archive-triggered programs could reach through `/proc`.
A Unix-only PostgreSQL listener does not block outbound
traffic or other processes, and the current Flannel deployment does not enforce
the declared NetworkPolicies; see [Runtime Isolation](../runbooks/runtime-isolation.md). **Activation
requires a reviewed, enforced no-network boundary for all restore processes and
children, with negative tests under the exact runtime profile before real backup
material is loaded.** The application README defines that gate; manifest checks
prove declarations only. Scheduled live success and production application
recovery remain additional acceptance gates; Redis and Enterprise package-store
recovery are outside this PostgreSQL drill.
Grafana's shared backup-staleness rule includes this CronJob alongside the four
media backup jobs and the isolated PostgreSQL restore drill: warn after 30 hours
without success, including an established job that has never succeeded. The legacy rule UID is preserved during expansion.

Multica uses the standard `nfs-default` class for its dedicated pgvector
PostgreSQL data and backend uploads. Treat those claims as a matched recovery
set: restore the database and upload PVCs from the same backup point before
resuming app sync, and preserve both PVCs during rollback unless intentionally
rebuilding the Multica instance. The first rollout is registered as stateful but
should stay in the stateful workload gate until backup and restore validation is
completed in `docs/storage-nfs.md`.

NOFX uses a single retained `nfs-default` claim for backend SQLite data and log
state at `/app/data`. Its backend working directory is also `/app/data`, so
upstream's relative backtest writes persist at `/app/data/backtests` and new
logs at `/app/data/data`; the absolute SQLite path remains `/app/data/data.db`.
Back up the whole claim, including simulation traces and caches, as one private
recovery set. Cash-spot allocations, order intents, and append-only fills share
that database; retain them during rollback and keep OKX traders stopped on
earlier images that cannot reconcile owned spot state. The root filesystem
remains read-only. See [NOFX](../apps/nofx.md).
The first rollout is registered as stateful but should
stay in the stateful workload gate until PVC smoke testing and backup/restore
expectations are recorded in `docs/storage-nfs.md`.

Deluge's active 5 Gi config volume is a retained static `hostPath` PV at
`/var/lib/deluge`, pinned to `zimaboard-0`. The initial guarded cold copy took
4 minutes 6 seconds for roughly 5.2 MB, demonstrating the QNAP stall on the old
startup path. The steady-state pod mounts only local config and shared
downloads; the old `deluge-config` claim receives verified nightly archives
with 14-day retention. This removes catalog, fast-resume, authentication, and
health-command reads from the QNAP path after read-only inspection on
2026-07-30 found the VPN healthy while the previous pod reported failed daemon
RPC health for roughly 17 hours. Its clean replacement loaded all 17 torrents
with no error-state entries and zero container restarts. An ordinary
`deluge-console status` still took 13 seconds on local config, so the existing
bounded health timeout remains necessary even though NFS is no longer in that
path.
The first scheduled NFS archive, `20260731T103003Z.tar.gz`, completed and passed
the CronJob's archive listing validation.

Radarr and Sonarr use retained static 10 Gi `hostPath` config volumes at
`/var/lib/radarr` and `/var/lib/sonarr`, pinned to `zimaboard-0`. Their guarded
`Recreate` cutovers copied the retained NFS config trees and recovered invalid
configuration before PostgreSQL/auth normalization. Migration markers make the
copies idempotent, while the old NFS claims remain archive and rollback targets.
The 04:00 and 04:15 Pacific CronJobs write verified archives with 14-day
retention. Read-only inspection on 2026-08-27 found both Applications `Synced`,
both local claims `Bound`, and successful backup Jobs through 2026-08-25. The
steady app pods no longer mount the legacy NFS claims; only the backup CronJobs
mount them as archive and rollback targets.

Deluge keeps 30-minute startup and runtime liveness windows so guarded
libtorrent recovery is not interrupted. The metrics sidecar refreshes cached
health every 60 seconds with a 20-second RPC cap; Prometheus scrapes that cache
every 45 seconds with a 30-second deadline. When stale resume data points
complete downloads at the incomplete root, the documented operator script
selects only exact-size target files, adopts them with libtorrent's
`dont_replace` move, and requires a full piece-hash recheck before completion is
trusted. The command resumes hash-valid entries for seeding and pauses hash
failures so stale catalog state cannot trigger a silent redownload.

## Source Files

- `docs/storage-nfs.md`
- `clusters/homelab/platform/storage`
- `clusters/homelab/apps/cordium-bootstrap/cluster-config.yaml`
- `clusters/homelab/apps/multica`
- `.talos/patches/worker-zimaboard-1.yaml`
- `.talos/patches/worker-cordium-user-namespaces.yaml`
- `.talos/patches/worker-cordium-user-namespaces-rollback.yaml`
- `clusters/homelab/apps/deluge/media-storage.yaml`
- `clusters/homelab/apps/deluge/local-storage.yaml`
- `clusters/homelab/apps/radarr/local-storage.yaml`
- `clusters/homelab/apps/sonarr/local-storage.yaml`
- `clusters/homelab/apps/media-postgres`
- `clusters/homelab/apps/media-postgres-recovery`
- `clusters/homelab/apps/octelium-storage`
- `clusters/homelab/apps/radarr/media-storage.yaml`
- `clusters/homelab/apps/sonarr/media-storage.yaml`
- `IaC/live/argocd-apps/platform-storage`

## OpenClaw identity coordinator ownership

OpenClaw uses a shared Pod-local coordinator directory owned by UID/GID `1000`,
mode `0700`, because the NFS export reports anonymous ownership. Persistent
state and recovery limits are documented in [OpenClaw Runtime State](../operations/openclaw-runtime-state.md).
Keep the single-replica `Recreate` strategy and same-Pod writer boundary.

The inactive Octelium restore candidate places its kubelet termination message
under the image's root-only `/root` directory and refuses backup reads if that
parent is searchable or the message writable by the restore UID. The root
filesystem is read-only and all capabilities remain dropped. Kubernetes mounts
termination messages writable even with a read-only root filesystem; changing
the message filename alone does not close that output channel. Synthetic Talos
activation proof must verify the inaccessible parent and an empty terminated
message under the exact published image. See the [kubelet mount implementation](https://github.com/kubernetes/kubernetes/blob/v1.34.1/pkg/kubelet/kuberuntime/kuberuntime_container.go#L454-L483).

### Monitoring storage recovery gap

Prometheus and Alertmanager remain on NFS without a completed restore proof.
A replacement storage target still needs healthy hardware, measured capacity,
verified backups, and an isolated restore before any reviewed rollout. Do not
use Acer's unverified storage or reduce retention to bypass those requirements.


## Harbor registry state

[Harbor](../operations/harbor-oci.md) uses a retained local PostgreSQL volume on
`acer`, retained NFS registry blobs and retained NFS logical database backups.
Recover the database and corresponding blobs together, retaining the SSM
encryption key and signing certificate. NFS copies share the QNAP failure
domain; off-NAS registry backup and an isolated restore drill remain open.
See `clusters/homelab/apps/harbor/README.md` for the concrete restore contract.

Harbor image signing adds the `harbor-image-signing` Kubernetes Secret to the
etcd recovery set. Its private key is absent from Harbor PostgreSQL dumps and
registry storage. Preserve a fresh encrypted off-node etcd backup after key
creation and restore that Secret before cert-manager can regenerate it. Keep
the public key independently for historical signature verification. See
[Harbor Private OCI Registry](../operations/harbor-oci.md) for the pending signing acceptance gates.

## Staged independent application recovery (HOME-2)

[Application recovery](../../docs/application-recovery.md) owns the source inventory,
proposed RPO/RTO, private secret dependencies, version-specific S3 publication,
paired capture contract, synthetic fixtures, retention and rollout/rollback.
Octelium/media source dumps remain on QNAP; the new dedicated application bucket,
IAM profiles, operator schedule and freshness rules are candidates only. The
publisher never expires retained data. AFFiNE/Multica adapters require a reviewed
writer fence; they do not automate capture. Other workload gaps remain explicit.
Operator-managed independent backups are unverified. Real-data drills require
HOME-3 containment and separate approval; HOME-4 owns independent alert delivery.
No operational RPO/RTO or application recovery is proven by synthetic tests.
