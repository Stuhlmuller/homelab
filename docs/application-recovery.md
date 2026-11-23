# Independent application recovery (HOME-2)

## Image automation pause and recovery controls

Image updates are journaled with `auto_merge: false` and `auto_inactive: false`.
An unresolved deployment blocks routine updates. A rollback may use only the
same application's retained known-good deployment after a fresh `safe`
current-data result; `unsafe` and `unknown` results pause and alert without
restoring data. `pause-reject` is control-only and records the failed digest.
The journal persists one recovery attempt before any ref movement, so restart
cannot create a second revert. Resume requires reviewed resolution and a new
healthy baseline.

The offline contract can be exercised with:

```sh
python3 -I scripts/ci/image-automation.py gate \\
  --application exporter --operation update
python3 -I scripts/ci/image-automation.py recover \\
  --application exporter --data-safety safe
```

This is a **staged implementation, not operational recovery proof**. Source was
revalidated at `32dc911c8f86638ae2e2012afbe7f80c4d3f17b3` on 2026-09-29.
No live cluster, S3 bucket, operator-managed backup, or recovery secret was
inspected. Whether Rodman already maintains an independent backup is **unknown**;
confirm its destination, credential custody, last retrieved version and restore
record before creating another destination. No spending or permission change is
approved by this document.

## Inventory and recovery contracts

Targets below are proposals, not achieved service levels or accepted data loss.
RPO is measured from the recovered source capture time, never the upload time.
RTO begins at disaster declaration and includes infrastructure, secrets and app
startup, not merely `pg_restore`. Owner approval of each loss budget is pending.
For all rows, AWS SSM/etcd/identity recovery must be available independently of
Octelium and the NAS. Etcd snapshots do not contain PVC contents.

<!-- markdownlint-disable MD013 -->

| State and source | Current source-declared coverage | Proposed RPO / RTO | Remaining recovery requirement |
| --- | --- | --- | --- |
| Octelium PostgreSQL (`apps/octelium-storage`) | Daily consistent custom dump + password-free globals, 14 days on same QNAP; this PR can publish those complete sets independently | 24h / 4h | Retrieve a named S3 set; PostgreSQL 14 restore and Octelium startup/resource/decryption checks; recover DB auth, external root/encryption keys and identity bootstrap privately |
| Octelium Redis AOF and Enterprise package storage | Retained PVCs; dormant rscstore whole-PVC S3 capture candidate, not yet activated; neither is included in the PostgreSQL dump | No loss accepted / 4h | Inventory runtime PVCs and Redis durability semantics; fence writers, capture AOF and packages, determine whether sessions/queues may be discarded; PostgreSQL coverage is not whole-Octelium coverage |
| Media PostgreSQL (`apps/media-postgres`) | Six nightly DB dumps + globals to QNAP; active data on Acer | 24h / 8h | All six are required by publisher; separate `pg_dump` snapshots do not establish cross-database atomicity. Fence all media writers for coordinated app/config recovery |
| AFFiNE (`apps/affine`) | NFS PostgreSQL 16/pgvector, blobs and config; one replica each for the server and datastores; no independent paired capture | 24h / 8h | Paired publication adapter accepts `globals.sql`, `affine.dump`, `blobs.tar`, `config.tar`, `capture.json`; prove suspension live, fence all writers, capture one window; preserve ECDSA signing key and extensions. Ephemeral Redis/queued work loss needs approval |
| Multica backend (`apps/multica`) | NFS pgvector PostgreSQL and uploads, no automatic independent capture | 24h / 8h | Paired adapter requires `globals.sql`, `multica.dump`, `uploads.tar`, `capture.json`; fence API/workers, retain JWT/DB secret dependencies; prove records refer to recovered uploads |
| Multica runtime (`apps/multica`, runtime manifests) | Node-local runtime PVC, PAT and native OAuth/session material | No loss accepted / 8h | Stop runtime before capture; separately approve recovery or re-enrollment of credentials; never export OAuth to SSM to make backup easier |
| n8n (`apps/n8n`, `apps/n8n-postgres`) | NFS DB, config and file-backed state; no independent scheduled set | 24h / 8h | Quiesce workflows/webhook writers, pair dump and files, retain the exact credential encryption key; disable outbound workflows during drill |
| Harbor (`apps/harbor`) | Local DB with logical backups to QNAP, NFS registry blobs | 24h / 8h | Fence pushes/GC and pair DB/blobs; restore encryption key and signing Secret separately; retain public verification key. DB dump excludes private signing key |
| Langfuse (`apps/langfuse`) | NFS PostgreSQL/ClickHouse/Valkey; S3 raw events expire after 30d; protected one-shot PostgreSQL checkpoint and isolated restore [passed on October 25, 2026](https://github.com/Stuhlmuller/homelab/actions/runs/40178714316) | 24h / 8h | Before a move or retirement, coordinate fresh stopped-writer PostgreSQL, ClickHouse, Valkey and raw-object-version captures; independently restore them with the application encryption/salt secrets and verify startup/ingestion. Decide queue losses. The PostgreSQL-only receipt and lifecycle-managed raw-event bucket do not establish whole-service recovery |
| Dispatcharr (`apps/dispatcharr`) | NFS PostgreSQL and runtime files; paired publication contract is dormant | 24h / 8h | Capture `globals.sql`, `dispatcharr.dump`, `data.tar` and a reviewed writer-fence attestation from one stopped state; independently restore with private provider credentials. No producer, offsite receipt or restore drill exists |
| OpenClaw, NOFX (`apps/openclaw`, `apps/nofx`) | Runtime/config PVCs; NOFX SQLite and simulation state; sensitive tokens/API keys | 24h / 8h | Stop writers or use SQLite online backup API; preserve DB/WAL consistency. Disable agents, trading and callbacks before a drill; no raw live-PVC tar advertised as consistent |

<!-- markdownlint-enable MD013 -->
| Sonarr/Radarr/Prowlarr/Deluge config, downloads and media | Some nightly config archives on same QNAP; media on QNAP `/media` | Config 24h / 8h; bulk-media loss undecided | Pair config with media DB window. Owner must identify irreplaceable uploads/media vs reproducible downloads; do not silently exclude bulk media |
| Grafana, LiteLLM and other app-owned DB/config | NFS or chart-configured state; Git captures only declarative config | 24h / 8h | Verify actual PVC inventory and SQLite/DB engines; capture non-Git dashboards/config and private keys consistently |
| Prometheus / Alertmanager (`apps/prometheus`) | NFS, source-declared monitoring data; HOME-4 owns migration | History-loss budget undecided / alerting 1h proposed | HOME-4 must use native TSDB snapshot or stopped-writer copy and stopped Alertmanager data copy, verified independently before cutover; preserve old claims; this publisher's DB adapters do not cover monitoring |
| Talos etcd, IaC state, SSM and bootstrap identities | Existing etcd S3 tooling, encrypted IaC state, SSM declarations | Confirm existing targets | Maintain private recovery material and independent AWS/operator access; test credentials without exposing them; do not assume repository declarations contain secret values |

Paths abbreviated `apps/…` above mean `clusters/homelab/apps/…`. See
[storage coverage](storage-nfs.md), the workload READMEs and
[knowledge-base inventory](../openwiki/workloads/inventory.md) for source
ownership. Automatic **capture** beyond existing Octelium/media jobs remains a
gap. The paired adapters provide publication, not an approved writer-fencing or
capture workflow. Do not enable them until that capture change is reviewed.

The dormant [rscstore capture stage](https://github.com/Stuhlmuller/homelab/blob/3b2256219bcc0cb70596a94fc17e66491e284a9f/clusters/homelab/apps/octelium-enterprise/README.md#dormant-resource-store-capture-stage)
adds a source-owned stopped-writer whole-PVC path to the existing versioned
application backup bucket. It needs separate inspector and fence activation,
exact-version readback, and isolated file extraction before an off-NAS archive
can be claimed. It does not reopen DuckDB or repair the WAL.

## Publication and retention design

`scripts/application-backup.py` reads only allowlisted, checksummed members
from a complete UTC-named directory (`YYYYMMDDTHHMMSSZ`). It refuses partial
directories, symlinks, missing files, malformed manifests, and future/stale
captures. Most sets are capped at 5 GiB; the two-part rscstore archive is
bounded at 10 GiB plus its receipt, with each S3 object at most 5 GiB. Media
sets require all six dumps. PostgreSQL dumps originate from the
existing `pg_dump` jobs; that gives each individual DB a consistent snapshot.
The publisher does not execute SQL, `pg_restore`, or tar extraction.

For paired captures, keep application writers fenced across **both** DB dump and
blob/config copy, including workers, webhooks, cron tasks and registry GC. Write
`capture.json` while fenced, include it in `SHA256SUMS`, then atomically rename
the completed directory. Its exact shape is:

```json
{
  "captured_at": "20260929T030000Z",
  "writers_fenced": true,
  "approved_fence_reference": "reviewed capture change and private execution record"
}
```

This is an operator attestation, not proof that a workload is actually stopped.
A successful upload cannot convert inconsistent input into a consistent backup.
Blobs are opaque objects here; real extraction requires the containment gate.

A content-derived ID prevents retries from creating new object names. The code
uses the existing etcd AWS adapter: fixed regional endpoints, expected owner,
versioning check, file-backed profile, bounded CLI timeouts and sanitized AWS
selector environment. Each object is conditionally created with SHA-256 and
SSE-KMS, then downloaded by exact version and hashed. Only after **all** members
pass does `complete.json` become the remote completion marker. It records each
immutable data version. Retrieval needs only app + ID, not a surviving local
receipt. Failed publication retains private scratch and cannot advance freshness;
a lost upload response is recovered by checking existing object metadata.
A failed final marker download may leave a valid remote completion marker; a
subsequent check must still retrieve and verify it.

AWS conditional-create semantics are documented in
[conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).
PostgreSQL explains per-database snapshot consistency in
[pg_dump](https://www.postgresql.org/docs/14/app-pgdump.html).
Versioning and conditional writes are not Object Lock or protection against an
AWS administrator. S3 is independent of QNAP hardware, but this proposal shares
the existing AWS account; a second account/region is a separate owner decision.

**Actual retention is indefinite.** The reused bucket module never expires
completed objects, has versioning/public-access blocking/TLS enforcement,
`prevent_destroy`, and `force_destroy=false`; its only lifecycle cleanup aborts
incomplete multipart uploads. The manual publisher has no deletion operation.
`retention-plan` lists candidates older than 30 days while protecting the newest
seven sets. It does not prune. Manage disposable local verification copies
separately from retained S3 versions.

## Manual publication and retrieval

The shared S3 destination is defined in the
[operator stack configuration](../IaC/homelab/us-west-2/operator/application-backup-storage.hcl).
Use a scoped file-backed AWS profile and read-only access to completed dumps.
For Octelium resource-store captures, follow the
[resource-store capture runbook](https://github.com/Stuhlmuller/homelab/blob/3b2256219bcc0cb70596a94fc17e66491e284a9f/clusters/homelab/apps/octelium-enterprise/README.md#dormant-resource-store-capture-stage)
and verify that the operator profiles cover the resource-store S3 prefix.

Prepare one newly completed source with private scratch directories pre-created
mode 0700 and the selected read-only source mounted:

```sh
python3 -I scripts/application-backup.py prepare --app octelium \
  --source /srv/application-backup-sources/octelium/logical-backups/20260929T023000Z \
  --workspace /var/lib/application-backups/octelium
# Use the actual ID printed by prepare, not the placeholder below.
python3 -I scripts/application-backup.py publish --app octelium \
  --workspace /var/lib/application-backups/octelium --id CAPTURE-CONTENT-ID \
  --aws-cli /usr/local/bin/aws --profile application-backup
python3 -I scripts/application-backup.py check --app octelium \
  --workspace /var/lib/application-backups/octelium \
  --aws-cli /usr/local/bin/aws --profile application-backup-reader \
  --metrics /var/lib/application-backups/metrics/octelium.prom
python3 -I scripts/application-backup.py retrieve --app octelium \
  --workspace /var/lib/application-backups/octelium --id CAPTURE-CONTENT-ID \
  --aws-cli /usr/local/bin/aws --profile application-backup-reader
```

The historical timestamp above illustrates shape only: use a current set or the
freshness gate correctly refuses publication. Repeat for `media-postgres`.
Expected: only a fully verified set has `complete.json`; `check` exits zero and
reports the capture timestamp, not now. Keep IDs/version metadata in a private
recovery index outside the NAS. A `retention-plan` command is advisory only.

## Isolated restore and acceptance record

Run only authored synthetic fixtures first:

```sh
python3 -I scripts/ci/application-backup-test.py
python3 -I scripts/ci/application-backup-restore-test.py
# If PostgreSQL binaries are outside PATH:
python3 -I scripts/ci/application-backup-restore-test.py --pg-bin /absolute/postgres/bin
```

The restore fixture creates socket-only disposable PostgreSQL clusters, dumps
synthetic records and key bytes, traverses the real preparation/publication/
retrieval logic with mocked S3, then restores records and checks a paired upload
against its database hash. It takes no production input, mounts or credentials.
The synthetic test is not a containment launcher for real archives. It validates
the data path, not an Octelium server or Multica application startup.

Use a disposable VM or proven network namespace for real archives. Restore SQL
can execute programs. Give the isolated restore private scratch and bounded
CPU, memory, and disk. Exclude external network access, production PVCs, AWS
and Kubernetes credentials, host or shared PID namespaces, public log
descriptors, and writable termination logs. Run the downloader outside that
boundary and transfer only the verified selected set.

After HOME-3 containment proof and explicit real-data approval, retrieve a
**specific** independently stored ID on the downloader, verify all versions and
checksums, transfer it into the isolated boundary, and invoke the reviewed
application-specific restore entry point. Reuse the existing Octelium candidate
SQL invariants, adapted to accept only that selected set; do not mount its normal
production backup PVC into the drill. Match PostgreSQL 14 and required extensions
for Octelium; AFFiNE/Multica require their chart versions and pgvector.

A private acceptance record must include capture UTC, object IDs/versions,
retrieval UTC, hashes, containment proof, database version, record/key/blob
invariants, application startup and representative behavior, no production PVC
access, restore start/end, and measured RPO/RTO. For Octelium include encrypted
resource decryption, auth/identity dependencies, Redis and packages or explicit
owner-approved losses. Keep records/secrets private; public evidence is only
pass/fail and timing. A remote checksum success is not application recovery.

Private secret procedure: enumerate each app's ExternalSecret/SSM references,
non-SSM signing/encryption keys and bootstrap credentials from the matching
README. Record versions and custody in the existing private recovery vault;
verify authorized recovery access without copying values to git, CI output or
issue comments. Preserve encryption keys rather than rotating them during a
restore. Role globals intentionally omit password hashes; provision database
roles from recovered private material before enabling clients. Test AWS/SSM,
Talos, DNS and identity access with the cluster/NAS unavailable. The publisher
checks its committed S3 destination and uses KMS encryption for production
archives; private credential material stays out of public logs.

## AdGuard configuration reconstruction

AdGuard's recovery authority is its Git configuration and the protected AWS SSM
`/homelab/adguard/admin-password` value, with independent administrator access to
AWS/encrypted IaC state. Its retained NFS work claim holds rebuildable filter
cache; neither a PVC nor a backup declaration proves a successful restore.
The [AdGuard recovery command](https://github.com/Stuhlmuller/homelab/blob/3b2256219bcc0cb70596a94fc17e66491e284a9f/clusters/homelab/apps/adguard/README.md#isolated-recovery-verification)
reconstructs those sources in disposable local containers and records exact source
and credential versions privately. It tests replacement and fresh-cache restore
without production mounts. Live private routing and client DNS require separate
acceptance. The same runbook's rollback command can restore the previous tailnet
DNS policy without requiring the failed AdGuard instance to answer.
