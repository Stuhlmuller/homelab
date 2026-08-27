# Media PostgreSQL

`media-postgres` is the shared PostgreSQL 14 instance for Sonarr, Radarr, and
Prowlarr. The writable `media-postgres-local` StatefulSet runs in the `media`
namespace on a static local volume pinned to `acer` and is exposed only through
`media-postgres.media.svc.cluster.local:5432`. The legacy NFS-backed
`media-postgres` StatefulSet remains declared at zero replicas.

## Secret Contract

The database password lives in AWS SSM Parameter Store at
`/homelab/media-postgres/app-password`. The `media-postgres-auth`
ExternalSecret creates the credentials consumed by the StatefulSet, and the
`media-postgres-arr-env` ExternalSecret creates the PostgreSQL settings used by
the `configure-postgres` init containers for Sonarr, Radarr, and Prowlarr.

Terragrunt generates this value and writes it to SSM. The pod includes a
`require-real-password` init container that fails when `POSTGRES_PASSWORD` is
empty or still set to `REPLACE_ME`, which catches incomplete bootstrap runs.

The Docker official PostgreSQL image creates `POSTGRES_USER` as a superuser on
first initialization. This is intentional here because the Servarr Prowlarr
PostgreSQL guide states that Prowlarr housekeeping needs a superuser for vacuum
work. Revisit this before adding unrelated apps to this database instance.

`PGDATA` points at a `pgdata` subdirectory inside the PVC. PostgreSQL runs as
UID/GID 65534, matching the ownership preserved by the staged NFS copy.

## Local Storage Cutover

Repeated QNAP NFSv3 stalls made PostgreSQL accept connections while ordinary
queries took tens of seconds or failed. The active database therefore uses a
20 Gi static volume backed by `/var/lib/media-postgres` on `acer`'s Talos
`EPHEMERAL` filesystem. The Kubernetes PV has `Retain` policy and hostname node
affinity. The requested 20 Gi capacity is descriptive because `hostPath` does
not enforce a quota; verify `acer` filesystem capacity during rollout and
monitor it directly in steady state.

The staged rollout first cold-copied the stopped NFS `pgdata` directory into an
atomic local staging directory, verified PostgreSQL 14, removed only the copied
stale `postmaster.pid`, and started the legacy StatefulSet locally with TCP
disabled and transactions forced read-only. A one-shot Job then wrote verified
logical dumps to the retained NFS claim.

The staging and writable states must reach `main` as two separately observed
revisions. Do not squash them into one PR or merge the writable revision until
Argo CD has synced the staging revision, the migration marker exists, and
`media-postgres-cutover-backup` is complete. If Argo CD jumps directly to the
writable state, the replacement intentionally fails closed because no verified
local data exists.

The final `media-postgres-local` StatefulSet mounts only the local claim and
does not contain the old NFS claim template or migration init container. Before
its first start, `require-local-data` verifies the copy/restore marker and
refuses to proceed while the legacy writer's `postmaster.pid` or shared Unix
socket exists. It then writes `.local-cutover-fenced`; this closes the Argo CD
zero-replica health race without blocking ordinary later restarts.

This local volume survives ordinary Talos reboots and upgrades because `/var`
is the Talos `EPHEMERAL` system volume, but it is node-bound and is lost if
`acer` is reset or its system disk fails. Move it to a dedicated Talos
UserVolume if the database grows materially or node-local recovery becomes
unacceptable.

## Recovery Probes

The startup probe allows PostgreSQL up to 30 minutes to finish crash recovery
before Kubernetes enables its liveness and readiness probes. Readiness and
liveness execute `SELECT 1`, so a process that merely accepts a socket while
database work is stalled does not count as healthy. Readiness removes it from
the Service quickly; liveness requires 30 minutes of continuous query failures
before restarting PostgreSQL.

The pod also has a 120-second termination grace period so PostgreSQL has more
time to finish a fast shutdown without being forcibly killed. If startup
recovery or a runtime liveness failure reaches the 30-minute limit, inspect the
`acer` local filesystem and PostgreSQL logs before changing probe thresholds or
rolling dependent applications. QNAP health affects backups and the apps'
remaining NFS-backed config, but not the active database files.

## Databases

The init script creates the logical databases that Servarr expects:

| App | Main database | Log database |
| --- | --- | --- |
| Sonarr | `sonarr-main` | `sonarr-log` |
| Radarr | `radarr-main` | `radarr-log` |
| Prowlarr | `prowlarr-main` | `prowlarr-log` |

The init script runs only when PostgreSQL initializes an empty data directory.
Changing database names after first boot requires an explicit migration plan.

Sonarr, Radarr, and Prowlarr follow the official Servarr PostgreSQL runbooks by
using PostgreSQL 14, pre-created main and log databases, and persistent
`config.xml` entries for `PostgresUser`, `PostgresPassword`, `PostgresPort`,
`PostgresHost`, `PostgresMainDb`, and `PostgresLogDb`.

## Existing SQLite Data

This desired state points the apps at PostgreSQL. It does not migrate existing
SQLite data from the `/config` PVCs. To preserve existing Sonarr, Radarr, or
Prowlarr data, take app backups first and follow the Servarr PostgreSQL
migration runbooks before treating the rollout as complete. A fresh rollout
without migration will start each app against empty PostgreSQL databases while
leaving the old SQLite files on the config PVCs.

Upstream migration references:

- Sonarr: <https://wiki.servarr.com/sonarr/postgres-setup>
- Radarr: <https://wiki.servarr.com/radarr/postgres-setup>
- Prowlarr: <https://wiki.servarr.com/prowlarr/postgres-setup>

## Validation

### Read-only staging revision

Before merging the writable revision, capture all of this phase-one evidence:

```sh
kubectl -n media get pod media-postgres-0 -o wide
kubectl -n media exec statefulset/media-postgres -- \
  test -f /var/lib/postgresql/data/pgdata/.nfs-migration-complete
kubectl -n media exec statefulset/media-postgres -- \
  psql -U media_apps -d media_apps -c '\l'
kubectl -n media exec statefulset/media-postgres -- \
  psql -U media_apps -d media_apps -Atqc 'SHOW default_transaction_read_only'
kubectl -n media exec statefulset/media-postgres -- \
  psql -U media_apps -d media_apps -Atqc 'SHOW listen_addresses'
kubectl -n media get job media-postgres-cutover-backup
kubectl -n media logs job/media-postgres-cutover-backup
```

The pod must run on `acer`; the migration marker and all six application
databases must exist; `default_transaction_read_only` must report `on`; and
`listen_addresses` must be empty. The Job must be `Complete`, and its log must
record the verified UTC `BACKUP_ID`. This evidence is the merge gate for the
writable revision.

### Writable revision

After Argo CD syncs the writable replacement, verify the secret, local volume,
legacy fence, Service endpoint, database list, query latency, and backup
schedule:

```sh
kubectl -n media get externalsecret media-postgres-auth media-postgres-arr-env
kubectl -n media get secret media-postgres-auth media-postgres-arr-env
kubectl get storageclass,persistentvolume media-postgres-local
kubectl -n media get statefulset media-postgres media-postgres-local
kubectl -n media get pod media-postgres-local-0 -o wide
kubectl -n media get pvc media-postgres-local data-media-postgres-0
kubectl -n media get statefulset media-postgres-local \
  -o jsonpath='{.spec.template.spec.volumes[*].persistentVolumeClaim.claimName}{"\n"}'
kubectl -n media get endpointslice \
  -l kubernetes.io/service-name=media-postgres \
  -o jsonpath='{range .items[*].endpoints[*]}{.targetRef.name}{"\t"}{.conditions.ready}{"\n"}{end}'
kubectl -n media exec statefulset/media-postgres-local -- \
  test -f /var/lib/postgresql/data/.local-cutover-fenced
kubectl -n media exec statefulset/media-postgres-local -- \
  psql -U media_apps -d media_apps -c '\l'
kubectl -n media exec statefulset/media-postgres-local -- \
  psql -U media_apps -d media_apps -Atqc 'SHOW default_transaction_read_only'
kubectl -n media exec statefulset/media-postgres-local -- \
  psql -U media_apps -d media_apps -Atqc 'SHOW listen_addresses'
for attempt in $(seq 1 20); do
  kubectl -n media exec statefulset/media-postgres-local -- \
    psql -U media_apps -d media_apps -Atqc 'SELECT 1' >/dev/null || exit 1
done
kubectl -n media get cronjob media-postgres-backup
kubectl -n media get cronjob media-postgres-backup \
  -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'
kubectl -n media get job -l app.kubernetes.io/name=media-postgres-backup
```

The database list should include `sonarr-main`, `sonarr-log`, `radarr-main`,
`radarr-log`, `prowlarr-main`, and `prowlarr-log`. The pod must run on `acer`,
the legacy StatefulSet must remain at zero replicas, the new StatefulSet must
list only `media-postgres-local`, and the EndpointSlice must list only
`media-postgres-local-0` as ready. The read-only setting must report `off`, and
`listen_addresses` must report `*`. All repeated queries must complete without
the NFS-correlated stalls. Test an indexer search in Prowlarr and then from both
Sonarr and Radarr before closing the incident.

## Backup And Restore

`media-postgres-backup` runs at 03:00 `America/Los_Angeles` each day. It writes
one recovery set under `logical-backups/<UTC timestamp>/` on the retained NFS
claim: custom-format dumps for all six databases, role globals without password
hashes, and SHA-256 checksums. It validates every archive before publishing the
directory and retains 14 days of completed backups. Each database dump is
internally consistent, but the six dumps do not share one cross-database
snapshot. Checksums detect corruption, not malicious modification, so treat
the NFS backup as trusted input.

The nominal RPO is 24 hours, but the actual RPO is the age of the newest
verified recovery set and can exceed 24 hours. Grafana warns after 30 hours
without a recorded success and also catches an established backup CronJob that
has never succeeded. Inspect the latest Job after each storage incident and
retain the verified cutover set until the first scheduled recovery set
succeeds; the normal 14-day retention policy applies afterward.

```sh
kubectl -n media get cronjob media-postgres-backup
kubectl -n media get cronjob media-postgres-backup \
  -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'
kubectl -n media get job -l app.kubernetes.io/name=media-postgres-backup
kubectl -n media logs job/<latest-media-postgres-backup-job>
kubectl -n media exec statefulset/media-postgres-local -- \
  df -h /var/lib/postgresql/data
```

The recovery overlay is
`clusters/homelab/apps/media-postgres-recovery`. It renders the complete base
application while patching the writer to zero replicas and suspending the
backup CronJob before the restore Job. The restore Job tolerates only the
`node.kubernetes.io/unschedulable` taint so it can recover the node-local volume
while `acer` remains cordoned. Use two reviewed Git revisions:

1. Before changing desired state, confirm no backup Job is active and verify
   `acer` has room for both the current and restored data directories. Read the
   exact completed `BACKUP_ID` from the latest successful backup Job log.
2. Change both `BACKUP_ID` and the timestamp/revision in the restore Job name,
   then change `sources[0].path` in the committed
   `unit "argocd_apps_media_postgres"` block in `IaC/terragrunt.stack.hcl` to
   `clusters/homelab/apps/media-postgres-recovery`. From `IaC/`, run
   `terragrunt stack generate`, review and merge the revision, then plan and
   apply the generated `live/argocd-apps/media-postgres` unit through the
   declared workflow.
3. Confirm `media-postgres-local` has no pod, no backup Job is active, and the
   uniquely named restore Job completed. A live writer makes the Job fail
   closed. A PVC marker also keeps the base writer stopped until the directory
   swap completes; after a failure, retry the same `BACKUP_ID` under another
   unique Job name before returning to the base overlay.
4. In the follow-up revision, return the same committed stack source path to
   `clusters/homelab/apps/media-postgres`, set `media-postgres-local` back to
   one replica in `statefulset.yaml`, and set `suspend: false` in
   `backup-cronjob.yaml`. Regenerate the stack, review and merge the revision,
   then plan and apply the generated unit. This removes the restore Job,
   resumes nightly backups, and starts the restored writer.

Never point Argo CD at only `restore-job.yaml`, and never run the restore with a
PostgreSQL pod active. The retained NFS `pgdata` copy is rollback-safe only
before local writes begin; afterward, recover through a fresh logical
dump/restore rather than reattaching the stale physical copy. Preserve
`pgdata.pre-restore-<BACKUP_ID>` until SQL, indexer, and new-backup validation
passes; remove it only through a later repository-owned cleanup.
