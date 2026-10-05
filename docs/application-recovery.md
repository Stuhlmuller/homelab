# Independent application recovery (HOME-2)

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
| Octelium Redis AOF and Enterprise package storage | Retained PVCs; not included in PostgreSQL dump | No loss accepted / 4h | Inventory runtime PVCs and Redis durability semantics; fence writers, capture AOF and packages, determine whether sessions/queues may be discarded; PostgreSQL coverage is not whole-Octelium coverage |
| Media PostgreSQL (`apps/media-postgres`) | Six nightly DB dumps + globals to QNAP; active data on Acer | 24h / 8h | All six are required by publisher; separate `pg_dump` snapshots do not establish cross-database atomicity. Fence all media writers for coordinated app/config recovery |
| AFFiNE (`apps/affine`) | NFS PostgreSQL 16/pgvector, blobs and config; source says suspended; no independent paired capture | 24h / 8h | Paired publication adapter accepts `globals.sql`, `affine.dump`, `blobs.tar`, `config.tar`, `capture.json`; prove suspension live, fence all writers, capture one window; preserve ECDSA signing key and extensions. Ephemeral Redis/queued work loss needs approval |
| Multica backend (`apps/multica`) | NFS pgvector PostgreSQL and uploads, no automatic independent capture | 24h / 8h | Paired adapter requires `globals.sql`, `multica.dump`, `uploads.tar`, `capture.json`; fence API/workers, retain JWT/DB secret dependencies; prove records refer to recovered uploads |
| Multica runtime (`apps/multica`, runtime manifests) | Node-local runtime PVC, PAT and native OAuth/session material | No loss accepted / 8h | Stop runtime before capture; separately approve recovery or re-enrollment of credentials; never export OAuth to SSM to make backup easier |
| n8n (`apps/n8n`, `apps/n8n-postgres`) | NFS DB, config and file-backed state; no independent scheduled set | 24h / 8h | Quiesce workflows/webhook writers, pair dump and files, retain the exact credential encryption key; disable outbound workflows during drill |
| Harbor (`apps/harbor`) | Local DB with logical backups to QNAP, NFS registry blobs | 24h / 8h | Fence pushes/GC and pair DB/blobs; restore encryption key and signing Secret separately; retain public verification key. DB dump excludes private signing key |
| Langfuse (`apps/langfuse`) | NFS PostgreSQL/ClickHouse/Valkey; S3 raw events expire after 30d; no logical backup pipeline | 24h / 8h | Coordinate relational, ClickHouse and raw-object versions; recover application encryption/salt secrets; decide queue losses. A lifecycle-managed raw-event bucket is not a backup |
| Dispatcharr (`apps/dispatcharr`) | NFS PostgreSQL and runtime files | 24h / 8h | Paired stopped-writer dump/files, private provider credentials; no adapter scheduled |
| OpenClaw, NOFX, OctoBot (`apps/openclaw`, `apps/nofx`, `apps/octobot`) | Runtime/config PVCs; NOFX SQLite and simulation state; sensitive tokens/API keys | 24h / 8h | Stop writers or use SQLite online backup API; preserve DB/WAL consistency. Disable agents, trading and callbacks before a drill; no raw live-PVC tar advertised as consistent |

<!-- markdownlint-enable MD013 -->
| Sonarr/Radarr/Prowlarr/Deluge config, downloads and media | Some nightly config archives on same QNAP; media on QNAP `/media` | Config 24h / 8h; bulk-media loss undecided | Pair config with media DB window. Owner must identify irreplaceable uploads/media vs reproducible downloads; do not silently exclude bulk media |
| Grafana, LiteLLM and other app-owned DB/config | NFS or chart-configured state; Git captures only declarative config | 24h / 8h | Verify actual PVC inventory and SQLite/DB engines; capture non-Git dashboards/config and private keys consistently |
| Prometheus / Alertmanager (`apps/prometheus`) | NFS, source-declared monitoring data; HOME-4 owns migration | History-loss budget undecided / alerting 1h proposed | HOME-4 must use native TSDB snapshot or stopped-writer copy and stopped Alertmanager data copy, verified independently before cutover; preserve old claims; this publisher's DB adapters do not cover monitoring |
| Talos etcd, IaC state, SSM and bootstrap identities | Existing etcd S3 tooling, encrypted IaC state, SSM declarations | Confirm existing targets | Maintain private recovery material and independent AWS/operator access; test credentials without exposing them; do not assume repository declarations contain secret values |

Paths abbreviated `apps/…` above mean `clusters/homelab/apps/…`. See
[storage coverage](storage-nfs.md), the workload READMEs and
[knowledge-base inventory](knowledge-base/workloads/inventory.md) for source
ownership. Automatic **capture** beyond existing Octelium/media jobs remains a
gap. The paired adapters provide publication, not an approved writer-fencing or
capture workflow. Do not enable them until that capture change is reviewed.

## Publication and retention design

`scripts/application-backup.py` reads only allowlisted, checksummed members from a
complete UTC-named directory (`YYYYMMDDTHHMMSSZ`). It refuses partial directories,
symlinks, missing files, malformed manifests, future/stale captures and sets above
5 GiB. Media sets require all six dumps. PostgreSQL dumps originate from the
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
incomplete multipart uploads. The publisher policy explicitly denies deletion
and lifecycle/versioning changes. `retention-plan` merely suggests complete sets
older than 30 days while protecting the newest seven. It never issues deletion;
that list is not sufficient authority to prune. Before any future pruning,
retrieve the protected sets, prove a restore, review full version inventory and
legal/owner retention requirements, then approve a separate exact change.
Partial uploads and failed local scratch are also retained. No automatic local
pruning is implemented: provision capacity, monitor it, and arrange reviewed
cleanup of disposable verification copies. The hourly runner refuses to start
below 20 GiB free. Large datasets need a reviewed streaming/multipart design.

## Exact proposed resources and authorization gates

1. First obtain operator confirmation of existing independent copies and a
   private recovery-secret inventory. An existing suitable destination may avoid
   a new bucket; change the committed destination and validations in review if
   selected. No speculative credential discovery is required.
2. Proposed new bucket: `homelab-application-backups-716182248480-us-east-1`,
   account `716182248480`, `us-east-1`, AWS-managed `alias/aws/s3`, versioned,
   no completed-object expiry. Reuse `IaC/modules/aws-backup-bucket`; the staged
   catalog unit is `IaC/.catalog/units/operator/application-backup-storage`.
   It is deliberately **absent** from `IaC/terragrunt.stack.hcl`, so routine
   stack generation/apply does not create it. Approve storage, request and KMS
   costs only after measuring dump sizes. For daily compressed input D GiB,
   retained storage grows roughly D GiB/day plus failed objects; hourly
   full-byte checks read roughly 24D GiB/day. No dollar quote or budget approval
   is inferred.
3. Approve a named existing off-cluster Linux operator host, private local
   scratch, and read-only access to completed backup directories only. Proposed
   repository location `/opt/homelab`, user/profile `application-backup`, and
   mount targets are in `recovery/application-backups/schedule.json`. Actual
   QNAP per-PVC directory names and mount configuration must be verified and
   committed through the operator host's configuration before activation; do
   not mount the full production export to make the example work.
4. Review `publisher-policy.json` for attachment to one dedicated identity with
   no broader inherited AWS rights. No identity or attachment is created here.
   `reader-policy.json` is the separate read-only checker proposal. Restrict
   initial grants to Octelium/media. AFFiNE/Multica publication requires a later
   reviewed prefix grant and capture pipeline. File-backed credentials must be
   available outside the NAS/cluster and recoverable without Octelium. AWS
   managed S3 key use is same-account and bucket-key scoped; validate the IAM
   conditions with real read-only checks and synthetic objects before rollout.
5. HOME-3 owns enforced real-data containment. Required contract: a disposable
   VM or proven network namespace with **no external network**, independent
   scratch, no production PVCs, no AWS/Kubernetes credentials, no host or shared
   PID namespace, no inherited public log descriptors, no writable termination
   log, and bounded CPU/memory/disk. Downloader runs outside this boundary;
   transfer only the verified selected set into it, then disconnect it. An
   unenforced NetworkPolicy is insufficient. Restore SQL can execute programs;
   never run real archives on the publisher host. This gate is unresolved here.
6. HOME-4 owns scraper/alert delivery and the independent dead-man receiver.
   Candidate `prometheusrule.yaml` consumes the three textfile metrics. Enable
   an authenticated scrape of the operator checker and validate receiver
   delivery. Metrics files are mode 0600; use a same-user exporter or approve a
   narrowly scoped access contract. A missing metric, failed check, source
   older than 30h, or checker older than 2h alerts after 15m. The independent
   receiver must detect total host/cluster/NAS loss; in-cluster rules cannot.

## Rollout after approval of the concrete changes

Keep changes in reviewed commits; no commands in this section were executed
against live resources. Do not approve a blanket apply based on this runbook.

After approving the bucket plan, add this explicit stack unit in a follow-up PR:

```hcl
unit "operator_application_backup_storage" {
  source                  = "./.catalog/units/operator/application-backup-storage"
  path                    = "operator/application-backup-storage"
  no_dot_terragrunt_stack = true
}
```

From `IaC`, generate the stack and plan only the new unit through the repository's
normal Terragrunt path; review the exact saved plan before authorizing apply.

```sh
terragrunt stack generate
terragrunt --working-dir operator/application-backup-storage init -backend=false
terragrunt --working-dir operator/application-backup-storage validate
# Initialize the normal backend before the real plan under existing access.
terragrunt --working-dir operator/application-backup-storage init
terragrunt --working-dir operator/application-backup-storage plan
# Apply only after separate approval of that exact plan:
terragrunt --working-dir operator/application-backup-storage apply
```

Apply the exact reviewed IAM attachment and host mount/user/service declarations
through their repository-owned configuration path. Those host/identity mappings
are still required integration work; these templates alone cannot safely install
a service on an unidentified machine. Leave the timer disabled initially.
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

Before enabling the hourly candidate systemd timer, validate one manual service
execution on the approved host, disk capacity, file permissions, read-only
mounts, AWS expiry/re-auth behavior, metrics scrape, and alert delivery. Systemd
prevents overlapping runs of the same service; do not run the CLI concurrently
against that workspace. Retries occur on the next hourly tick, with no destructive
cleanup or unbounded in-process retry. Enable through the reviewed host
configuration. A host reboot requires durable mounts/scheduling/profile access;
these are explicit operational gates, not assumed from a unit file.

## Isolated restore and acceptance record

Run only authored synthetic fixtures first:

```sh
python3 -I scripts/ci/application-backup-test.py
python3 -I scripts/ci/application-backup-restore-test.py
python3 -I scripts/ci/application-backup-rules-test.py
# If PostgreSQL binaries are outside PATH:
python3 -I scripts/ci/application-backup-restore-test.py --pg-bin /absolute/postgres/bin
```

The restore fixture creates socket-only disposable PostgreSQL clusters, dumps
synthetic records and key bytes, traverses the real preparation/publication/
retrieval logic with mocked S3, then restores records and checks a paired upload
against its database hash. It takes no production input, mounts or credentials.
The synthetic test is not a containment launcher for real archives. It validates
the data path, not an Octelium server or Multica application startup.

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
Talos, DNS and identity access with the cluster/NAS unavailable. Exporting real
secret material or production archives requires the concrete approval above.

## Rollback

Disable future timer executions via the approved host configuration and revert
only the new scrape/rule references if needed. An active service may finish up
to its 50-minute deadline. Keep local partials, completed S3 versions, the new
bucket and old NFS jobs/claims. Do not remove a generated IaC unit from state or
attempt bucket destruction. Restore the prior scheduler/config commit only;
publication does not alter production DBs, PVCs or applications. Any eventual
production cutover has a separate fenced rollback plan; this PR authorizes none.

## Evidence and remaining work

Offline fault injection covers incomplete source/upload/marker, lost PUT
response, corrupted download, wrong version, checksum/path rejection, stale and
future capture, all-six-media requirements, paired fence attestation, failure
metrics and non-destructive retention. The synthetic DB/blob round trip passed
locally on PostgreSQL 15.19 (test tooling only); production PostgreSQL 14 and
application startup remain untested. Existing etcd publication tests still pass.
Five freshness alert scenarios passed with Prometheus 2.42.0 test tooling
(absent, healthy, failed, stale capture and stopped checker). JSON/YAML/HCL
syntax checks passed. Full Nix checks, Terragrunt/OpenTofu validation/plan,
real AWS checks and Kubernetes render/live checks are unavailable in this runtime.
Run those gates before approving activation. Source checks cannot confirm live
operator backups or recoverability. Keep HOME-2 in review until the operational
acceptance record exists; merging a PR does not close the finding.
