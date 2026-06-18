# Dispatcharr

Dispatcharr runs in the `media` namespace as an Octelium-protected IPTV and EPG
manager at `https://dispatcharr.stinkyboi.com`.

## Runtime Shape

- Image: `ghcr.io/dispatcharr/dispatcharr`
- Mode: upstream modular container with web and Celery containers
- PostgreSQL: dedicated `dispatcharr-postgres` PostgreSQL 17 StatefulSet
- Redis: in-pod sidecar, ephemeral cache/queue state
- HTTP port: `9191`
- Access: private app hostname through Octelium, no public unauthenticated
  route
- Public IP lookup: disabled with `DISPATCHARR_ENABLE_IP_LOOKUP=false`

The modular mode avoids the upstream all-in-one container's embedded PostgreSQL
ownership reconciliation under `/data/db`, which is not compatible with the
QNAP NFS export's squashed UID behavior. The Pod still mounts a memory-backed
`/dev/shm` volume larger than the container runtime default for worker and
stream-processing scratch space.

## Storage

The `data` PVC uses `nfs-default` and stores Dispatcharr uploads, file-backed
runtime data, and first-run admin configuration. PostgreSQL data lives in the
dedicated `dispatcharr-postgres` PVC. Treat both as production state and include
them with normal NFS backup coverage before relying on the service.

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

Revert the Argo CD Application registration and app manifests, then sync the
`dispatcharr` Application. Preserve the `data` PVC and the
`dispatcharr-postgres` PVC unless the operator explicitly chooses to discard
Dispatcharr state.
