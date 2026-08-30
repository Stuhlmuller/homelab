# Dispatcharr

Dispatcharr runs in the `media` namespace as an Octelium-protected IPTV and EPG
manager at `https://dispatcharr.stinkyboi.com`.

## Runtime Shape

- Image: `ghcr.io/dispatcharr/dispatcharr:0.30.0`, pinned to the same immutable
  multi-architecture digest for web and Celery
- Mode: upstream modular container with web and Celery containers
- PostgreSQL: dedicated `dispatcharr-postgres` PostgreSQL 17 StatefulSet
- Redis: in-pod sidecar, ephemeral cache/queue state
- HTTP port: `9191`
- Access: private app hostname through Octelium, no public unauthenticated
  route
- Public IP lookup: disabled with `DISPATCHARR_ENABLE_IP_LOOKUP=false`

The modular mode avoids the upstream all-in-one container's embedded PostgreSQL
ownership reconciliation under `/data/db`, which is not compatible with the
QNAP NFS export's squashed UID behavior. PostgreSQL readiness and liveness
execute `SELECT 1`, so accepting a socket without completing database work does
not count as healthy. The Pod still mounts a memory-backed `/dev/shm` volume
larger than the container runtime default for worker and stream-processing
scratch space.

The `0.30.0` image passed the repository's fixed HIGH/CRITICAL Trivy policy
with zero findings. The `0.29.0` to `0.30.0` source change adds no new Django
migration file, but both retained claims still require a verified snapshot
before rollout. Redis remains on the supported `8.10.1-alpine` image while #898
tracks an upstream rebuild for its two remaining OpenSSL findings.

## Storage

The `data` PVC uses `nfs-default` and stores Dispatcharr uploads, file-backed
runtime data, and first-run admin configuration. PostgreSQL data lives in the
dedicated `dispatcharr-postgres` PVC. Treat both as production state and include
them with normal NFS backup coverage before relying on the service. The database
has 30-minute startup and runtime liveness windows plus a 120-second termination
grace so NFS-backed recovery can complete without a restart loop.

The QNAP export maps writes from container root to UID/GID `65534`. The web
container sets upstream `PUID`/`PGID` to that owner so nginx and Django can use
the data directories without a forbidden `chown`. Its short wrapper gives the
image's existing `nobody` account a login shell before upstream renames that
account to `dispatcharr`; upstream later drops web processes to that UID.

## First Run

After Argo CD reports the `dispatcharr` Application `Synced` and `Healthy`,
open the Octelium-protected UI and finish upstream first-run setup:

```sh
kubectl -n media get pod -l app.kubernetes.io/name=dispatcharr
kubectl -n media logs deploy/dispatcharr -c app --tail=120
kubectl -n media logs deploy/dispatcharr -c celery --tail=120
```

Do not commit IPTV provider credentials, playlist URLs, or guide source secrets.
Configure those through the UI or a future ExternalSecret-backed integration.

## Rollback

Revert both Dispatcharr container pins together to
`0.29.0@sha256:df768adcb9993b58f5e67010cc802c8659b7f964cb1213ab7ff9bb9384db9145`,
then sync the `dispatcharr` Application. Preserve the `data` PVC and the
`dispatcharr-postgres` PVC unless the operator explicitly chooses to discard
Dispatcharr state. Restore a snapshot only if the application changed retained
state incompatibly; upstream provides no downgrade guarantee.
