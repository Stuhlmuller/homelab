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
PostgreSQL has 30-minute startup and liveness windows plus a 120-second
termination grace period so NFS recovery is allowed to complete without a
crash-recovery loop. Readiness and liveness execute `SELECT 1` instead of only
checking that PostgreSQL accepts a socket connection, so a query-stalled server
is not reported healthy. The pod is pinned to `zimaboard-1`, whose NFS client
remained responsive during the 2026-07-29 incident that repeatedly stalled the
same retained claim on `acer`.

## Validation

```sh
kubectl -n octelium-storage get externalsecret,secret octelium-storage-auth
kubectl -n octelium-storage get statefulset,pod,pvc,svc
kubectl -n octelium-storage exec statefulset/octelium-postgres -- psql -U octelium -d octelium -Atqc 'SELECT 1'
kubectl -n octelium-storage exec statefulset/octelium-redis -- redis-cli ping
```

Redis requires authentication for real clients; the unauthenticated `PING` can
return `NOAUTH` while still proving the TCP listener is reachable.
