# Octelium Storage

`octelium-storage` provides the in-cluster PostgreSQL and Redis stores required
by `octops init` for the self-hosted Octelium Cluster. The stores are dedicated
to Octelium and are not shared with application data.

## Secret Contract

Terragrunt generates these SSM SecureStrings:

- `/homelab/octelium/postgres-password`
- `/homelab/octelium/redis-password`

The `octelium-storage-auth` ExternalSecret materializes the values into the
`octelium-storage` namespace. The bootstrap script reads the Kubernetes Secret,
creates a temporary Octelium bootstrap file outside git, runs `octops init`, and
then deletes the temporary file.

## Storage

PostgreSQL 14.24 uses a 20Gi `nfs-default` PVC. Redis 7.4.11 uses a 5Gi
`nfs-default` PVC with AOF enabled. The QNAP NFS export squashes ownership, so
both pods run as UID/GID 65534 like the other file-backed PostgreSQL workloads
in this repo.
PostgreSQL has a 30-minute startup window, a 90-second runtime liveness window,
and a 120-second termination grace period. Readiness and liveness execute
`SELECT 1` instead of only checking that PostgreSQL accepts a socket connection,
so a query-stalled server is removed from service and restarted promptly. The
pod is pinned to `zimaboard-1`; this avoids the worst observed NFS client but
does not make QNAP NFS reliable database storage.

## PostgreSQL Backup

`octelium-postgres-backup` runs daily at 02:30 UTC. It writes
one recovery set under `logical-backups/<UTC timestamp>/` on the retained
`octelium-postgres-backup` NFS claim. Each set contains PostgreSQL globals
without role password hashes, one custom-format `octelium` database dump, and
SHA-256 checksums. The Job validates the dump with `pg_restore --list`, checks
the files before and after an atomic directory rename, and retains 14 days of
completed sets.

The nominal RPO is 24 hours; the actual RPO is the age of the newest successful
Job. The source and backup claims use the same QNAP export, so this protects
against logical database failure and supports a later storage migration, but it
does not protect against NAS loss or malicious modification. A restore path and
restore drill remain required before this backup can be treated as proven
disaster recovery.

Redis AOF state has no independent repository-owned backup or restore path.
That is a rollout blocker, not an instruction to take an ad hoc NAS snapshot.

## Security Patch Gate

Issue #789 phase 1 keeps PostgreSQL on major 14 and Redis on release line 7.4.
Argo CD applies the PostgreSQL StatefulSet at sync wave 0, the backup CronJob at
wave 1, and the Redis StatefulSet at wave 2. PostgreSQL must become healthy
before Argo CD restarts Redis. Updating the CronJob does not start an ad hoc
backup Job.

Do not merge the phase until all preflight evidence is attached to its review:

1. Confirm the latest backup Job succeeded less than 24 hours ago and its log
   ends with `completed backup`. This proves `pg_restore --list` and both
   checksum passes completed, but not that the dump restores successfully.
2. Complete the PostgreSQL restore drill tracked by GitHub issue #790.
3. Inventory every connectable, non-template PostgreSQL database. Confirm the
   cluster has no non-built-in logical output plugin and each inventoried
   database has no `pgcrypto`, `btree_gist`, or `ltree` extension. Any result
   needs a release-note-specific configuration, data cleanup, or reindex plan.
4. Add and prove a repository-owned Redis AOF backup and restore path, or prove
   from Octelium's owned contract that its Redis state is safely rebuildable.
5. Record pod restart counts, SQL and Redis health, Redis persistence status,
   and the Octelium end-to-end result as the before-state.

Run these read-only checks:

```sh
kubectl -n octelium-storage get statefulset,pod,pvc,cronjob
kubectl -n octelium-storage get cronjob octelium-postgres-backup \
  -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'
kubectl -n octelium-storage get job \
  -l app.kubernetes.io/name=octelium-postgres-backup \
  --sort-by=.metadata.creationTimestamp \
  -o custom-columns='NAME:.metadata.name,COMPLETED:.status.completionTime,SUCCEEDED:.status.succeeded,FAILED:.status.failed'
kubectl -n octelium-storage logs job/<latest-successful-backup-job>
kubectl -n octelium-storage exec statefulset/octelium-postgres -- \
  psql -U octelium -d octelium -Atqc 'SELECT 1'
kubectl -n octelium-storage exec statefulset/octelium-postgres -- \
  psql -U octelium -d octelium -P pager=off -c \
  "SELECT slot_name, plugin FROM pg_replication_slots WHERE plugin NOT IN ('pgoutput', 'test_decoding') ORDER BY 1;"
kubectl -n octelium-storage exec statefulset/octelium-postgres -- sh -ec '
  databases="$(psql -U octelium -d postgres -Atqc \
    "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY 1")"
  test -n "$databases"
  printf "%s\n" "$databases" |
  while IFS= read -r database; do
    printf "database=%s\n" "$database"
    psql -U octelium --dbname="$database" -Atqc \
      "SELECT extname FROM pg_extension WHERE extname IN ('\''pgcrypto'\'', '\''btree_gist'\'', '\''ltree'\'') ORDER BY 1"
  done
'
kubectl -n octelium-storage exec statefulset/octelium-redis -- sh -ec \
  'redis-cli --no-auth-warning -a "$(cat /run/secrets/octelium-storage/REDIS_PASSWORD)" ping'
kubectl -n octelium-storage exec statefulset/octelium-redis -- sh -ec \
  'redis-cli --no-auth-warning -a "$(cat /run/secrets/octelium-storage/REDIS_PASSWORD)" info persistence | grep -E "^(loading|aof_enabled|aof_rewrite_in_progress|aof_last_bgrewrite_status|aof_last_write_status):"'
scripts/octelium-e2e-check.sh
```

Expected: the backup timestamp is less than 24 hours old; the latest Job shows
one success and its log contains `completed backup`; SQL and Redis return `1`
and `PONG`; the logical-plugin query returns no rows; the extension check lists
every expected database and no extension below any `database=` heading; Redis
reports `loading:0`, `aof_enabled:1`, no rewrite in progress, and `ok` for its
last rewrite and write; the end-to-end script exits zero.

After merge, require the `octelium-storage` Argo CD Application to become
`Synced/Healthy`. Re-run every check above, confirm PostgreSQL reports 14.24 and
Redis reports 7.4.11, and retain the output as post-rollout evidence:

```sh
kubectl -n argocd get application octelium-storage
kubectl -n octelium-storage exec statefulset/octelium-postgres -- \
  psql -U octelium -d octelium -Atqc 'SHOW server_version'
kubectl -n octelium-storage exec statefulset/octelium-redis -- sh -ec \
  'redis-cli --no-auth-warning -a "$(cat /run/secrets/octelium-storage/REDIS_PASSWORD)" info server | grep "^redis_version:"'
```

Observe for 24 hours before closing the phase. Require zero unexpected pod
restarts, no PostgreSQL or Redis persistence errors, no Octelium control-plane
failure, stable query/request latency, and no sustained CPU or memory increase.

Rollback stays declarative and preserves both PVCs. If PostgreSQL fails before
wave 2, revert this phase through Git; Argo CD will not have restarted Redis.
If Redis fails after PostgreSQL is healthy, use a reviewed Git change restoring
only Redis 7.4.2 while leaving PostgreSQL 14.24 in place. If PostgreSQL starts
but data is inconsistent, do not blindly downgrade its binaries: fence through
repository-owned desired state and use the proven pre-rollout restore path.
Never delete, patch, restart, or force-recreate a live StatefulSet or PVC.

## Validation

```sh
kubectl -n octelium-storage get externalsecret,secret octelium-storage-auth
kubectl -n octelium-storage get statefulset,cronjob,pod,pvc,svc
kubectl -n octelium-storage exec statefulset/octelium-postgres -- psql -U octelium -d octelium -Atqc 'SELECT 1'
kubectl -n octelium-storage exec statefulset/octelium-redis -- sh -ec \
  'redis-cli --no-auth-warning -a "$(cat /run/secrets/octelium-storage/REDIS_PASSWORD)" ping'
kubectl -n octelium-storage get cronjob octelium-postgres-backup -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'
kubectl -n octelium-storage get job -l app.kubernetes.io/name=octelium-postgres-backup
kubectl -n octelium-storage logs job/<latest-octelium-postgres-backup-job>
```

The Redis check reads the mounted password inside the pod and does not print it.
