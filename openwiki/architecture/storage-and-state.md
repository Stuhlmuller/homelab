---
type: architecture
title: "Storage And State"
description: "Etcd recovery, QNAP NFS and local volumes, workload backup ownership, and unresolved storage and restore gates."
tags: ["architecture", "storage", "stateful"]
sources:
  - id: openwiki-source-7f1128611d8d832ea8e26c38
    resource: repo://.github/workflows/validate.yml
  - id: openwiki-source-3cae87753a0e502a1e05c1f3
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/backup.sh
  - id: openwiki-source-855f2c27f3fa7ed6f006f4be
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/networkpolicy.yaml
  - id: openwiki-source-489371bb6baef577dc131a87
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/postgres-tls.yaml
  - id: openwiki-source-4aa900d84e01409d13d834a6
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/postgres.yaml
  - id: openwiki-source-878d8aa0884abae2a8194701
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/README.md
  - id: openwiki-source-4b551d11e16fb851a8676ce2
    resource: repo://clusters/homelab/apps/openclaw-enterprise-operator/journal.yaml
  - id: openwiki-source-d2d8ff2161af78b658d004f0
    resource: repo://clusters/homelab/apps/openclaw-enterprise-operator/README.md
  - id: openwiki-source-20275bab1ec480742e28a50f
    resource: repo://clusters/homelab/apps/openclaw-enterprise/preflight.mjs
  - id: openwiki-source-8918085c21c3a103803f7fbe
    resource: repo://clusters/homelab/apps/openclaw-enterprise/profile-input.json
  - id: openwiki-source-9268fd97f2c4ec8553f9ecb8
    resource: repo://clusters/homelab/apps/openclaw-enterprise/README.md
  - id: openwiki-source-d65575b694fbbe7e37dd04e6
    resource: repo://clusters/homelab/apps/openclaw/README.md
  - id: openwiki-source-52536621afbfff1f8abeed59
    resource: repo://clusters/homelab/apps/renovate/config.js
  - id: openwiki-source-caf6d77fd092a28e8583a6a2
    resource: repo://clusters/homelab/apps/renovate/pvc.yaml
  - id: openwiki-source-01fc0bedc522f2abd58d6698
    resource: repo://clusters/homelab/apps/renovate/README.md
  - id: openwiki-source-b8e8b7405b7234a1ce62dc56
    resource: repo://clusters/homelab/platform/storage/nfs-subdir-external-provisioner-application.yaml
  - id: openwiki-source-df5b234ace5ca38a67ae3b6b
    resource: repo://docs/evidence/openclaw-enterprise-acceptance.md
  - id: openwiki-source-8f8dab72ff0b7636d31aef4b
    resource: repo://docs/openclaw-enterprise-rollout.md
  - id: openwiki-source-80ce7a2e5d2f59ee74027e0c
    resource: repo://docs/storage-nfs.md
  - id: openwiki-source-249f8996a9ec8263ee227cf0
    resource: repo://IaC/homelab/us-west-2/apps/openclaw-enterprise-foundation/stack.hcl
  - id: openwiki-source-5c8bcbe4b07307d5ad637f1a
    resource: repo://scripts/ci/openclaw-enterprise-backup-transaction-test.py
  - id: openwiki-source-0ec224257fa3d91c69b2b9f1
    resource: repo://scripts/ci/openclaw-enterprise-capture.py
  - id: openwiki-source-d0de55404aabd71445d94e5a
    resource: repo://scripts/ci/openclaw-enterprise-download.py
  - id: openwiki-source-b3bdcadf54edf75020440bdd
    resource: repo://scripts/ci/openclaw-enterprise-operations.sh
  - id: openwiki-source-e9e65f5a163d93923cf250f7
    resource: repo://scripts/ci/openclaw-enterprise-reader-archive.py
  - id: openwiki-source-5e0c81611c85d2d14785a38b
    resource: repo://scripts/ci/openclaw-enterprise-reader-chart-check.py
  - id: openwiki-source-fefbb162e3ea3ac148a6dc9a
    resource: repo://scripts/ci/openclaw-enterprise-reader-pod.py
  - id: openwiki-source-2b592454bee3d706931b5357
    resource: repo://scripts/ci/openclaw-enterprise-reader-policy-test.py
  - id: openwiki-source-91161c3887f6aa107b3c0d6b
    resource: repo://scripts/ci/openclaw-enterprise-recovery-test.py
  - id: openwiki-source-38f54948f5bf90d0cb9bddb7
    resource: repo://scripts/ci/openclaw-enterprise-stage.sh
  - id: openwiki-source-b7865f8f7c461f149710edda
    resource: repo://scripts/ci/renovate-cache-recovery-test.mjs
  - id: openwiki-source-9100b7266ad774f6eeda0265
    resource: repo://scripts/ci/renovate-config-test.js
  - id: openwiki-source-d2206c7f78c1ec59c3551c13
    resource: repo://scripts/config/openclaw-enterprise.json
  - id: openwiki-source-2eea896f325c470e4979019b
    resource: repo://scripts/openclaw-enterprise.py
  - id: openwiki-source-aa83e90c74e65ee6187dbbb5
    resource: repo://specs/003-replace-openclaw-enterprise/research.md
  - id: openwiki-source-2031a4cf1c03de6b7fcceacb
    resource: repo://specs/004-run-renovate-in-cluster/dry-run-parity-receipt.md
  - id: openwiki-source-a44b67b396abfe9ddff04314
    resource: repo://specs/004-run-renovate-in-cluster/tasks.md
generated: { by: "codex", at: "2026-10-27T23:04:53.760Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-27T23:04:53.760Z
---

# Storage And State

Langfuse's October 10 Valkey AOF repair retained a SHA-256-verified original
off-NAS and promoted a native-checker-validated prefix repair, discarding
340,520 bytes of the incremental log (event count unknown). The GitOps recovery
pruned the inspection Pod while all writers remained stopped, then restored
Valkey and Langfuse in a separate revision. Valkey loaded the repaired AOF,
and four fresh attributed generations reached Langfuse. Keep the original
archive and all PVCs; an independent restore drill remains unverified. See the
[Langfuse recovery runbook](../../clusters/homelab/apps/langfuse/README.md#valkey-offline-capture-and-candidate-inspection).

LiteLLM's native UI-key migration added `ai/data-litellm-postgres-0`, a 20 GiB
NFS claim for its dedicated PostgreSQL database. Preserve logical dumps, volume
snapshots and SSM role passwords together. The native cutover transaction stores
four caller key hashes plus the `homelab-native-key-import-v1` marker. Preserve
that marker during restore: it prevents startup from recreating revoked keys.
Live native key listing, revocation and per-key traced gateway generations
passed; browser UI rendering, native caller actions and database restore
remain pending. See the
[LiteLLM runbook](../../clusters/homelab/apps/litellm/README.md).

During the final October 10 check, `zimaboard-2` became unreachable and its
terminating `n8n-postgres-0` left n8n at 0/1 Ready while both Argo Applications
still reported Synced/Healthy. Kubernetes recreated PostgreSQL on
`zimaboard-0` after the node returned; PostgreSQL and n8n recovered to 1/1
without manual mutation. Check database and dependent workload readiness, not
Argo status alone, during release acceptance.

The operator-owned `IaC/homelab/us-west-2/operator/state-bucket-encryption` unit manages only
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
`octelium-metricstore`), Prowlarr, Radarr, Sonarr, LiteLLM, n8n,
and NOFX SQLite state. The stopped legacy OpenClaw keeps configuration and
workspace on its retained NAS claim, while its global state, per-agent SQLite
databases, and native Codex home remain on `openclaw-runtime-local` on
`zimaboard-1`. The platform-storage application owns its StorageClass and PV;
the namespaced OpenClaw application owns its PVC. This permitted local WAL and
native bindings across Pod replacement. The backup CronJob is suspended;
historical SQLite snapshots remain on the NAS. The local hostPath survives Pod replacement
but not node-disk loss; there is no automatic node failover and recovery can lose
writes since the last backup. Native caches are reconstructed on disaster restore.
The post-shutdown inventory, protected off-NAS archive publication and separate
multi-root restore verification passed. [Publication run `39501240221`](https://github.com/Stuhlmuller/homelab/actions/runs/39501240221)
restored the versioned upload before its private final receipt. The separate
[verify run `39910018168`](https://github.com/Stuhlmuller/homelab/actions/runs/39910018168)
succeeded at 2026-10-23 09:52 UTC against publication reference
`9f64b56a15c8a1c1b81606e0fa751157b09f47fb/39501240221`. It fetched the
exact archived versions and rechecked full local/NAS tree content, both SQLite
databases and required historical backups. The new Enterprise recovery set and
compatible legacy boot remain unverified; keep all retained claims. Later
`publish-archive` retries `39700564687` and
`39908653791` used the publication ID as a source worker ID and failed before
upload. They do not invalidate the successful publication.
The declared `prepare-restore` stage rechecks stopped writers, retained volume
and root identities, and private scratch capacity before fetching the
publication's exact versioned archive and receipt. The source-only transfer
repair fetches pinned S3 versions in at most 128 MiB ranges, verifies version,
interval and length metadata, then sends at most 8 MiB SHA-256-checked slices
to the reader. It rolls back interrupted appends and promotes only after a full
size and SHA-256 match. The first [protected run `39942297939`](https://github.com/Stuhlmuller/homelab/actions/runs/39942297939)
left an incomplete, unverified archive in scratch. The [retry
`39951803625`](https://github.com/Stuhlmuller/homelab/actions/runs/39951803625)
failed in fixed `verification-archive-download`; neither reached receipt
download or the restore worker. The next [retry
`39966041305`](https://github.com/Stuhlmuller/homelab/actions/runs/39966041305)
also failed in `verification-archive-download` before receipt download or
restore-worker start. Its protected download helper did not distinguish the
S3 source range from reader transport or finalization, so the cause remains
unclassified. The later [protected copy run
`39988927652`](https://github.com/Stuhlmuller/homelab/actions/runs/39988927652)
downloaded the pinned archive and receipt and started a detached restore
worker, then its six-hour job was cancelled. Its source-bound [resume run
`40050057926`](https://github.com/Stuhlmuller/homelab/actions/runs/40050057926)
passed exact-main and prior-job provenance checks, verified the stable worker
success marker, cached archive and receipt hashes, restored database report,
source identity and zero production writers, and prepared a separate private
NAS scratch recovery tree. This is a partial T014 copy receipt, not an old-image
boot or compatible recovery proof.
The [cache builder](../../scripts/openclaw-discord-offline-cache.py)
produces a public npm content-cache tar, dependency lock, and digest manifest
without legacy state or credentials. Its
[CI proof](../../.github/workflows/openclaw-discord-offline-cache.yml)
deletes those artifacts after a fresh `--network none` install and runtime
inspection. A later recovery operation still needs reviewed private publication,
digest-checked transfer, and a compatible boot from separate writable copies
behind an enforced offline boundary; this cache proof does not accept T014.
The legacy archive retains NAS symlink targets but not data outside its roots.
Nine links leave those roots. Six point into `/app` and resolve to five nonempty
directories in the pinned image baseline without an `/app` volume. The former
gateway had a writable root, so its overlay may have changed those targets;
their original contents remain unclassified until compared with retained
evidence. Three dangling external targets also remain unclassified. T014 still
needs their disposition, a separate writable UID 1000 local-state copy, an
isolated NAS copy and an old-image boot
behind an enforced offline network boundary. Flannel does not enforce the
declared NetworkPolicies, so a deny policy alone cannot qualify the rehearsal.
The latest protected network preflight on 2026-10-27 passed fixed-operation
validation and the exact-current-main guard, then failed the legacy retention
stage in the sanitized `network-access` category. It produced no T014
capability receipt; isolated old-image boot remains unproved.
See the OpenClaw app README and [OpenClaw Runtime State](../operations/openclaw-runtime-state.md).
The dormant [Enterprise foundation](../../clusters/homelab/apps/openclaw-enterprise-foundation/README.md)
declares a cert-manager `occ-postgres-root` CA with Argo `Prune=false` and a
nonrotating private key. Preserve that Secret with any eventual database
recovery set. Its Argo Application is declared with automatic sync disabled but
has not been applied. Its PostgreSQL 18.6
StatefulSet, role bootstrap, 10Gi local claim template and guarded backup and
restore fixtures are source-only; node placement, live role initialization,
complete backup material and isolated restore remain pending. No new Enterprise PVC or live database exists from
this source alone. The [backup script](../../clusters/homelab/apps/openclaw-enterprise-foundation/backup.sh)
now requires exactly one recovery marker object with `writerStopped: true`,
`continuousFenceVerified: true`, and a nonempty `claimUid`. The
[offline fixture](../../scripts/ci/openclaw-enterprise-recovery-test.py)
rejects false, missing, malformed and concatenated markers. The source-only
[reader](../../scripts/ci/openclaw-enterprise-reader-archive.py) validates exact
read-only Pod/PVC identity and full claim mounts in each namespace, while the
[assembler](../../scripts/ci/openclaw-enterprise-capture.py) checks the two
archive manifests and before/after claim, PV and Secret observations. Its
output deliberately sets `continuousFenceVerified:false`: the marker cannot
prove a live UID match or continuous writer exclusion by itself. The packager
uses a local scratch mount and pinned age recipient to publish ciphertext on a
separate backup mount. A pure [reader Pod renderer](../../scripts/ci/openclaw-enterprise-reader-pod.py)
now describes two idle, namespace-local UID 1000 Pods: only exact read-only
journal/bootstrap or dynamic Gateway claim mounts, no service-account token,
host namespaces, environment, probes or extra containers. The renderer binds
the backup ID and a reviewed source SHA to the exact immutable Harbor restore
image reference. Reader and assembler reject a different image digest or a
command that could stream private bytes into Pod logs. The reader executable is
packaged in the unpublished restore image, but the Pods are excluded from
Kustomization and workflows. No coordinator, enforced egress fence, UID 1000
claim-access proof, recipient projection, off-node publication receipt or
independent restore is declared; T051 remains open.
The foundation now includes two source-owned, reader-specific policies with
empty ingress and egress rules. The required protected `validate / repo` job
fetches the pinned stock chart commit and rejects overlapping allows in its
render alongside foundation and chart-adjacent resources. Kubernetes policies
are additive. A future coordinator must inspect every
live policy selecting those labels and prove an enforcing egress canary before
creating either reader Pod.
The dormant reconciler now has a journaled backup stop/resume transaction.
It records stop intent before the native stop request, adopts an exact stopped
outcome after a lost response, and blocks uncertain outcomes without reposting.
Resume requires a future trusted capture-proof callback before a new deployment
revision; it records resume intent first, checks exact revision history and
adopts a lost response without a second POST. A pre-stop guard refuses backup
when the journal's 100-revision limit leaves no resume slot. Ordinary no-change
reconciliation does not redeploy. These helpers have no CLI or workflow entry;
a coordinator must still prove continuous writer exclusion, encrypted off-node
publication, independent restore, and exact-main source/config binding.
The 2026-10-20 13:07–13:15 UTC post-shutdown recheck found
about 3,398 MiB unreserved on the best worker, `zimaboard-1`, below the
4,096 MiB initial Enterprise reservation before transient and host headroom.
Its root filesystem had 9.74 GB free. Talos confirmed each worker's `/var`
resides on eMMC; all have less than the 10.74 GB needed for a new 10 GiB local
claim if T035 uses the existing `/var/lib` pattern. New node paths are not yet
committed. `acer` has only 1,802 MiB unreserved, below the 2,304 MiB database
and gateway minimum. This does not admit local storage or an isolated canary; see the
[acceptance ledger](../../docs/evidence/openclaw-enterprise-acceptance.md).
The 2026-10-23 read-only recheck found only `acer` with room for a new
10 GiB local claim; it has about 1,801 MiB unreserved, 503 MiB below the
database-plus-gateway request. The best worker has 9.00 GiB filesystem free.
Its 38 non-DaemonSet Pods request about 3,342 MiB, exceeding the other nodes'
combined 2,036 MiB headroom, so workload rebalancing cannot clear an isolated
canary. Crossplane source declares two zero-replica controllers, while live
Deployments still request 256 MiB each on `acer`; reconciling that separate
drift would leave only about 9 MiB after the minimum and no isolation.
An 08:18 UTC recheck on `main` `bcc08cb` still found 383.07 GiB filesystem
free on `acer` but only about 1,802 MiB unreserved RAM. The 503 MiB gap is
only the declared database-plus-gateway floor. If the [initial 4,096 MiB
planning reservation](../../specs/003-replace-openclaw-enterprise/research.md)
for API, worker, database, Envoy and gateway is co-located on `acer`, it
exceeds unreserved requests by about 2,295 MiB before startup, backup,
and peak margin. This is a planning scenario, not selected placement. The
[pinned Embedded Gateway source](../../docs/evidence/openclaw-enterprise-acceptance.md)
uses `oce-role: agents`, requests 1,792 MiB in one Pod, and needs its own 10 GiB
local state claim. The configured 768 MiB Harness request applies to Dedicated
mode only; adding it to Embedded capacity was incorrect.
At 09:32 UTC on `main` `111b58f`, `acer` had 1,802 MiB unreserved and 383.01 GiB
filesystem free, while every worker had less than 10 GiB free. Both the 10 GiB
database and Gateway claims therefore need `acer` under the proposed local
storage pattern; their 2,304 MiB request is 502 MiB above its headroom.
Splitting API, worker and the full Envoy planning allowance to `zimaboard-1`
would leave only 122 MiB against its observed memory margin before peaks.
No existing node has an admitted Enterprise storage and isolated-canary
placement.
The later October 25 [capacity ledger](../../docs/evidence/openclaw-enterprise-acceptance.md)
screened reversible Langfuse and Dispatcharr suspension. Their combined
request release could fit a 4 GiB Acer planning budget on paper, but the
Gateway burst and replacement margin remain too small, complete recovery for
both services is unproved, and no isolated canary is admitted. Neither service
has been paused for Enterprise.
At the 2026-10-27 18:47 UTC read-only capacity recheck, `acer` had 2,895 MiB
request headroom, 1,201 MiB short of the 4,096 MiB initial Enterprise budget.
Splitting across the other workers still lacked safe memory and local-claim
disk margin, and `zimaboard-2` was not an isolated canary. A Langfuse and
Dispatcharr pause fit only request arithmetic; complete recovery, measured
peaks and restart overlap remain unproved. No service was paused or moved.
The separate dormant [chart candidate](../../clusters/homelab/apps/openclaw-enterprise/README.md)
names local agent storage and a private bootstrap password claim. Its preflight
requires `occ-bootstrap-admin-password` to be Bound to
`openclaw-enterprise-bootstrap-local` and PostgreSQL to have a ready endpoint
before chart initialization. The foundation declares the dedicated PostgreSQL
Service and 10Gi claim template, but remains unsynced and undeployed. The local
classes, bootstrap and agent claims, live database and restore proof remain
pending; the candidate does not adopt legacy OpenClaw state.
The inactive reconciler needs a private durable journal at
`/private/openclaw-enterprise/journal.json` for pending API intent and resource
IDs across retries. Its journal claim must remain separate from the writable
bootstrap claim. The [staged operator bundle](../../clusters/homelab/apps/openclaw-enterprise-operator/README.md)
declares a retained 1Gi journal PVC and local StorageClass, but no static PV,
node placement or active GitOps registration; the claim is not live or admitted.
The [protected operations workflow](../../.github/workflows/openclaw-enterprise-operations.yml)
wires `full-sync` to the guarded helper, but the committed `unselected`
installation phase blocks it before cluster access. Its `reconcile`, `stop`
and `verification` stages have a one-shot Job dispatcher with exact-main and
PVC/PV identity checks; `journalOperator.enabled: false` blocks all three
before Job creation. `restore` and `acceptance` remain separately blocked.
The hosted runner never mounts the private journal; live reconciliation needs
the admitted local volume and in-cluster Job.
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
The October 10 Valkey capture stage stopped Langfuse web/worker/Valkey, mounted
the queue PVC read-only, and captured its complete files to private off-NAS
storage. Hash-verified originals remain separate from the repaired AOF. At
that stage no live replacement was enabled; the later approved promotion and
restart are recorded above. General backup and independent restore coverage
remain unverified. See the
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
- `IaC/homelab/us-west-2/apps/platform-storage/argocd`

## OpenClaw identity coordinator ownership

The stopped legacy OpenClaw used a shared Pod-local coordinator directory owned by UID/GID `1000`,
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

## Renovate cache

Renovate retains a 20 GiB `nfs-default` PVC in `automation` for datasource,
private-package, and repository caches; its working files stay on ephemeral
storage. The cache includes private package metadata, so restrict access to the
volume and logs. It is replaceable and has no backup requirement. Argo CD does
not prune the PVC. Before requesting a GitHub token, each run flushes a small
write to the claim so a full or unwritable cache fails visibly. The `20Gi`
request neither reserves NAS space nor caps usage: `nfs-default` cannot resize
PVCs or enforce their requested size. A full export needs restored NAS capacity
through a declared path; increasing the PVC request cannot restore writes.
No verified QNAP `/homelab` capacity-restoration operation is declared. An
isolated tmpfs `ENOSPC` drill can test failure visibility and later normal
PVC use, but cannot prove recovery from a full NAS export. T024/T042 and
writer cutover remain blocked on a declared capacity path and direct recovery
evidence. For corruption, suspend the CronJob, clear only cache contents with
a reviewed temporary GitOps Job, then let the next run rebuild them. See [the workload
runbook](../../clusters/homelab/apps/renovate/README.md).
An independently sized 20 GiB `/renovate-cache` QTS volume, static PV and
claim are staged as a candidate. They are outside active Kustomizations;
verify the separate export before a reviewed claim switch.
The pinned Renovate recovery fixture confirms missing or malformed package and
repository cache entries can be rebuilt; the config test confirms a full-claim
probe stops GitHub access. These are local checks. Restricted logs from the
19:00 and 20:00 UTC scheduled Pods showed one exact public canary
datasource-key hit each, on distinct Pod UIDs using the same PVC. These
observations are recorded in the durable
[T022 receipt](../../specs/004-run-renovate-in-cluster/dry-run-parity-receipt.md).
After the protected `v0.0.2` release at 20:20 UTC, the 21:00 scheduled dry run
hit the same key, refreshed its record, and selected the new public canary
branch proposal. T022 is complete. A live cache-failure cycle and next-slot
recovery remain open.

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
