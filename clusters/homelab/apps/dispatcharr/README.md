# Dispatcharr

Dispatcharr runs in the `media` namespace as an Octelium-protected IPTV and EPG
manager at `https://dispatcharr.stinkyboi.com`.

## Runtime Shape

- Image: `ghcr.io/dispatcharr/dispatcharr`
- Mode: upstream all-in-one container with embedded Redis, Celery, nginx, and
  PostgreSQL state under `/data`
- HTTP port: `9191`
- Access: private app hostname through Octelium, no public unauthenticated
  route
- Public IP lookup: disabled with `DISPATCHARR_ENABLE_IP_LOOKUP=false`

The all-in-one mode matches the upstream-supported simple Docker deployment.
The Pod mounts a memory-backed `/dev/shm` volume larger than the container
runtime default because Dispatcharr's embedded PostgreSQL can exhaust the
default shared-memory mount during startup or worker activity.

## Storage

The `data` PVC uses `nfs-default` and stores Dispatcharr application data,
embedded database files, uploads, cacheable metadata, and first-run admin
configuration. Treat it as production state and include it with the normal NFS
backup coverage before relying on the service.

## First Run

After Argo CD reports the `dispatcharr` Application `Synced` and `Healthy`,
open the Octelium-protected UI and finish upstream first-run setup:

```sh
kubectl -n media get pod -l app.kubernetes.io/name=dispatcharr
kubectl -n media logs deploy/dispatcharr -c app --tail=120
```

Do not commit IPTV provider credentials, playlist URLs, or guide source secrets.
Configure those through the UI or a future ExternalSecret-backed integration.

## Rollback

Revert the Argo CD Application registration and app manifests, then sync the
`dispatcharr` Application. Preserve the `data` PVC unless the operator
explicitly chooses to discard Dispatcharr state.
