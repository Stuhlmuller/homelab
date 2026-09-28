# AFFiNE

AFFiNE is deployed from the official self-host container shape as the public
workspace UI at `https://affine.tail67beb.ts.net` and tailnet host
`https://affine.stinkyboi.com`.

The deployment mirrors the official `v0.26.3` release self-host bundle:

- `ghcr.io/toeverything/affine:stable`
- PostgreSQL through `DATABASE_URL`
- Redis through `REDIS_SERVER_HOST`
- persistent `/root/.affine/storage`
- persistent `/root/.affine/config`
- pre-start `node ./scripts/self-host-predeploy.js`

The latest GitHub release endpoint returned `v0.26.3` on 2026-07-12. Newer git
tags existed at that time, but the self-host Docker Compose and
`default.env.example` assets were verified from the release asset list.

## Secrets

AFFiNE reads these SSM-backed values through External Secrets:

- `/homelab/affine/private-key`
- `/homelab/affine/postgres-app-password` through `affine-postgres-client`

PostgreSQL admin and app passwords are owned by the `affine-postgres` support
app. The app receives only the app connection string.

## Public Exposure

The public route is an intentional Tailscale Funnel route for the full AFFiNE
web UI. The app also keeps a normal tailnet route through
`affine.stinkyboi.com`.

## Validation

Render the desired state:

```sh
kubectl kustomize clusters/homelab/apps/affine
```

After Argo CD sync:

```sh
kubectl -n collaboration get deploy,pod,pvc,svc -l app.kubernetes.io/name=affine
kubectl -n collaboration logs deploy/affine -c migrate --tail=100
kubectl -n tailscale get statefulset,pod -l tailscale.com/parent-resource=affine-funnel
curl -I https://affine.tail67beb.ts.net
```

## Rollback

Remove `affine-funnel`, the `affine-funnel` Gateway, and the public
`AFFINE_SERVER_EXTERNAL_URL` first if public exposure needs to be stopped.
Preserve the AFFiNE PVC and `affine-postgres` PVC unless intentionally
rebuilding from exports and database backups.
