# Media PostgreSQL

`media-postgres` is the shared PostgreSQL 14 instance for Sonarr, Radarr, and
Prowlarr. It runs in the `media` namespace. During the first cutover phase, it
cold-copies its active database to the static `media-postgres-local` volume
pinned to `acer`, serves it read-only, and exposes only the in-cluster Service
`media-postgres.media.svc.cluster.local:5432`.

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

`PGDATA` points at a `pgdata` subdirectory inside the PVC. PostgreSQL continues
to run as UID/GID 65534 so the one-time NFS copy preserves ownership without
rewriting every database file.

## Local Storage Cutover

Repeated QNAP NFSv3 stalls made PostgreSQL accept connections while ordinary
queries took tens of seconds or failed. The active database therefore uses a
20 Gi static volume backed by `/var/lib/media-postgres` on `acer`'s Talos
`EPHEMERAL` filesystem. The Kubernetes PV has `Retain` policy and hostname node
affinity. The requested 20 Gi capacity is descriptive because `hostPath` does
not enforce a quota; verify `acer` filesystem capacity during rollout and
monitor it directly in steady state.

On the first rollout, StatefulSet ordering stops the old pod before the new pod
starts. `migrate-nfs-data` then copies the stopped NFS `pgdata` directory into
an atomic staging directory on the local volume, verifies PostgreSQL major
version 14, removes only the copied stale `postmaster.pid`, and renames the
completed copy into place. Later starts skip the copy when local `PG_VERSION`
already exists.

The first phase starts PostgreSQL with
`listen_addresses=''` and `default_transaction_read_only=on`. Disabling TCP is
the hard fence for Sonarr, Radarr, and Prowlarr writes. The pinned
`media-postgres-cutover-backup` Job connects through a Unix socket shared on the
local volume and writes verified logical dumps of all six databases to the
retained NFS claim.

After the copy and backup are verified, the second phase must scale the legacy
StatefulSet to zero and create a clean replacement StatefulSet that mounts only
`media-postgres-local`, with neither the legacy `volumeClaimTemplates` nor the
migration init container. Only that replacement re-enables writes. Removing
the init container from the existing StatefulSet is insufficient because its
immutable claim template would still mount the old NFS claim.

This local volume survives ordinary Talos reboots and upgrades because `/var`
is the Talos `EPHEMERAL` system volume, but it is node-bound and is lost if
`acer` is reset or its system disk fails. Move it to a dedicated Talos
UserVolume if the database grows materially or node-local recovery becomes
unacceptable.

## Recovery Probes

The startup probe allows PostgreSQL up to 30 minutes to finish crash recovery
before Kubernetes enables its liveness and readiness probes. Readiness executes
`SELECT 1`, so a process that merely accepts a socket while database work is
stalled is removed from the Service. Liveness remains the recovery-tolerant
`pg_isready` check and requires 30 minutes of continuous failures before
restarting PostgreSQL.

The pod also has a 120-second termination grace period so PostgreSQL has more
time to finish a fast shutdown without being forcibly killed. If startup
recovery or a runtime liveness failure reaches the 30-minute limit, verify QNAP
and NFS health before changing the probe thresholds or rolling dependent
applications.

## Databases

The init script creates the logical databases that Servarr expects:

| App | Main database | Log database |
|-----|---------------|--------------|
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

After Argo CD syncs the first cutover phase, verify the secret, local volume,
StatefulSet, migration marker, read-only fence, database list, query latency,
and completed backup:

```sh
kubectl -n media get externalsecret media-postgres-auth media-postgres-arr-env
kubectl -n media get secret media-postgres-auth media-postgres-arr-env
kubectl get storageclass,persistentvolume media-postgres-local
kubectl -n media get statefulset,pod,pvc,svc -l app.kubernetes.io/name=media-postgres
kubectl -n media get pod media-postgres-0 -o wide
kubectl -n media exec statefulset/media-postgres -- \
  test -f /var/lib/postgresql/data/pgdata/.nfs-migration-complete
kubectl -n media exec statefulset/media-postgres -- psql -U media_apps -d media_apps -c '\l'
kubectl -n media exec statefulset/media-postgres -- \
  psql -U media_apps -d media_apps -c 'SELECT 1'
kubectl -n media exec statefulset/media-postgres -- \
  psql -U media_apps -d media_apps -Atqc 'SHOW default_transaction_read_only'
kubectl -n media exec statefulset/media-postgres -- \
  psql -U media_apps -d media_apps -Atqc 'SHOW listen_addresses'
kubectl -n media get job media-postgres-cutover-backup
```

The database list should include `sonarr-main`, `sonarr-log`, `radarr-main`,
`radarr-log`, `prowlarr-main`, and `prowlarr-log`. The pod must run on `acer`,
the read-only setting must report `on`, repeated `SELECT 1` calls should
complete without the NFS-correlated stalls, `listen_addresses` must be empty,
and the backup Job must complete.

## Backup And Restore

`media-postgres-cutover-backup` writes one verified recovery set containing
custom-format dumps for all six databases, role globals, and checksums under
`logical-backups/` on the retained NFS claim. This is a first-phase cutover
gate, not the steady-state backup schedule. The writable replacement phase must
replace it with a nightly CronJob before the cutover is complete.

```sh
kubectl -n media get job media-postgres-cutover-backup
kubectl -n media logs job/media-postgres-cutover-backup
```

For a full restore, declare a fresh local volume in Git, restore globals and
the six matching dumps through a repository-owned recovery Job, restore each
app's `/config` backup, then re-sync Sonarr, Radarr, and Prowlarr. The retained
NFS `pgdata` copy is a valid immediate rollback point only before writes reach
the local database; afterward, rollback requires a fresh logical dump and
restore rather than reattaching the stale NFS copy.
