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

PostgreSQL uses a 20Gi `nfs-default` PVC. Redis uses a 5Gi `nfs-default` PVC
with AOF enabled. The QNAP NFS export squashes ownership, so both pods run as
UID/GID 65534 like the other file-backed PostgreSQL workloads in this repo.
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

## Validation

```sh
kubectl -n octelium-storage get externalsecret,secret octelium-storage-auth
kubectl -n octelium-storage get statefulset,cronjob,pod,pvc,svc
kubectl -n octelium-storage exec statefulset/octelium-postgres -- psql -U octelium -d octelium -Atqc 'SELECT 1'
kubectl -n octelium-storage exec statefulset/octelium-redis -- redis-cli ping
kubectl -n octelium-storage get cronjob octelium-postgres-backup -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'
kubectl -n octelium-storage get job -l app.kubernetes.io/name=octelium-postgres-backup
kubectl -n octelium-storage logs job/<latest-octelium-postgres-backup-job>
```

Redis requires authentication for real clients; the unauthenticated `PING` can
return `NOAUTH` while still proving the TCP listener is reachable.
