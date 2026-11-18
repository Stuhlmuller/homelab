# n8n PostgreSQL Desired State

`n8n-postgres` is a dedicated PostgreSQL instance for n8n in the `automation`
namespace. It keeps n8n workflow metadata, credentials metadata, user records,
and execution history out of the SQLite file on the n8n PVC.

The database runs only inside the cluster at
`n8n-postgres.automation.svc.cluster.local:5432` and persists data on the
`nfs-default` StorageClass.

## Secret Contract

- `/homelab/n8n/postgres-admin-password`: PostgreSQL superuser password used
  only by the database container.
- `/homelab/n8n/postgres-app-password`: n8n database user password exposed to
  n8n as a file-backed secret.

The app password is mounted into n8n through `n8n-postgres-client` and read via
`DB_POSTGRESDB_PASSWORD_FILE`. The admin password stays in
`n8n-postgres-auth` and is not mounted into the n8n application pod.

## Database Bootstrap

The PostgreSQL init script creates:

| Role  | Database | Notes                                             |
| ----- | -------- | ------------------------------------------------- |
| `n8n` | `n8n`    | Owns the database and `public` schema used by n8n |

The init script runs only when PostgreSQL initializes an empty data directory.
Changing database names, users, or passwords after first boot requires an
explicit migration or `ALTER ROLE` plan.

## SQLite Migration Note

This desired state points n8n at PostgreSQL. It preserves the existing
`/home/node/.n8n` PVC but does not automatically import rows from an existing
`database.sqlite` file. Export workflows and credentials before rollout if the
current SQLite contents must be preserved, then import them after n8n starts
against PostgreSQL.

## NFS Interruption Recovery

PostgreSQL 14 writes temporary collector statistics to a 32 MiB memory-backed
`emptyDir` at `/run/postgresql-stats`, configured with `stats_temp_directory`.
Keeping these frequently refreshed files off NFS avoids statistics reads
waiting up to ten seconds for a stalled collector. The existing pod `fsGroup`
makes the mount writable by UID/GID 65534. Database files, WAL, and permanent
statistics remain on the existing PVC; this does not weaken commit durability.
The memory limit includes these temporary files. Remove this PostgreSQL-14-only
setting when migrating to PostgreSQL 15 or newer, which uses shared-memory
statistics. See the [PostgreSQL 14 documentation](https://www.postgresql.org/docs/14/runtime-config-statistics.html).

Changing this setting rolls the single database pod, causing a brief n8n outage.
Rollback is a Git revert of the arguments and temporary volume; retain the PVC.
This reduces statistics-related NFS traffic but does not eliminate stalls in
durable database I/O.

The readiness and liveness probes execute `SELECT 1`, so accepting a socket
without completing database work does not count as healthy. Readiness removes
PostgreSQL from its Service after six failed checks, but startup and liveness
failures tolerate 30 minutes of QNAP recovery and shutdown receives 120 seconds
to finish. This reduces forced crash recovery after an NFS stall.

## Validation

After Argo CD syncs `n8n-postgres`, verify the secrets, StatefulSet, PVC, and
database connectivity:

```sh
kubectl -n automation get externalsecret n8n-postgres-auth n8n-postgres-client
kubectl -n automation get secret n8n-postgres-auth n8n-postgres-client
kubectl -n automation get statefulset,pod,pvc,svc -l app.kubernetes.io/name=n8n-postgres
kubectl -n automation exec statefulset/n8n-postgres -- \
  psql -U postgres -d n8n -Atqc 'select 1'
kubectl -n automation exec statefulset/n8n-postgres -- \
  psql -U postgres -d n8n -Atqc 'show stats_temp_directory'
kubectl -n automation rollout status deployment/n8n --timeout=10m
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://n8n-webhook.tail67beb.ts.net/webhook/__missing__
```

Require a Ready PostgreSQL Pod, bound PVC, successful SQL query, and n8n
readiness. The statistics directory must be `/run/postgresql-stats` on a tmpfs
mount. Check fresh logs for collector warnings and database ping timeouts.
The missing callback should return an n8n HTTP 404 rather than a
gateway response. Follow the [n8n callback gates](../n8n/README.md#access-contract)
for fixed-hook migration and fresh signed-delivery acceptance.

## Backup And Restore

NFS snapshots protect the PostgreSQL volume, but application-ready restore
requires logical dumps. Before upgrades or storage maintenance, dump the n8n
database and keep it with the n8n PVC backup:

```sh
kubectl -n automation exec statefulset/n8n-postgres -- pg_dump -U postgres n8n
```

For a full restore, restore the PostgreSQL PVC or recreate the database from a
logical dump, restore the n8n `/home/node/.n8n` PVC for the instance config and
binary data, then re-sync n8n through Argo CD.
