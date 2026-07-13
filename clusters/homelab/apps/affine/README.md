# AFFiNE

AFFiNE runs as a self-hosted collaborative knowledge base at
`https://affine.stinkyboi.com`. Public internet reachability terminates at the
shared Cloudflare Tunnel, then Octelium requires an authenticated HUMAN
clientless browser session before proxying the request through the Istio
gateway. There is no unauthenticated Funnel route to the workload.

## Runtime contract

- AFFiNE server: `ghcr.io/toeverything/affine:0.26.3`, one replica on port
  `3010`, with the upstream `/info` health endpoint.
- Database: dedicated PostgreSQL 16 plus pgvector, authenticated with
  `/homelab/affine/postgres-password` and persisted on a 20 Gi
  `nfs-default` claim.
- Cache and jobs: dedicated authenticated Redis 8.2 with append-only
  persistence on a 5 Gi `nfs-default` claim.
- Application state: uploaded blobs use a 50 Gi retained PVC; the AFFiNE config
  directory uses a 1 Gi retained PVC. The committed `config.json` is mounted
  read-only so security, storage, and URL behavior remain declarative.
- Signing identity: `/homelab/affine/private-key` is an OpenTofu-generated P-256
  ECDSA private key stored as an encrypted SSM SecureString and materialized by
  External Secrets. Do not rotate it without invalidating sessions and planning
  encrypted-data recovery.
- Database migrations: the digest-pinned AFFiNE image runs
  `scripts/self-host-predeploy.js` as an Argo CD Sync hook after PostgreSQL and
  Redis are healthy and before the server Deployment is reconciled.
- Copilot: disabled. The current homelab LiteLLM catalog exposes a text model
  but not AFFiNE's required embedding and image capabilities. Add the complete
  model set and a file-backed secret contract before enabling it.
- SMTP: not configured because the homelab does not own a shared SMTP provider.
  Do not add mail credentials to `config.json`; introduce SSM parameters and
  ExternalSecret mappings before enabling password-reset or invite delivery.

## First login

Open `https://affine.stinkyboi.com` through Octelium. AFFiNE allows signup so
the first authenticated homelab user can complete the upstream admin bootstrap.
After the intended accounts exist, set `auth.allowSignup` to `false` in
`configmap.yaml` and roll the change through GitOps.

## Validation

```sh
kubectl kustomize clusters/homelab/apps/affine
kubectl -n argocd get application affine
kubectl -n affine get deploy,statefulset,job,pod,pvc,svc,externalsecret
kubectl -n affine exec statefulset/affine-postgres -- \
  psql -U affine -d affine -c 'select extversion from pg_extension where extname = '\''vector'\'';'
kubectl -n affine exec statefulset/affine-redis -- /bin/sh -ec \
  'redis-cli --no-auth-warning -a "$(cat /run/secrets/affine/REDIS_PASSWORD)" ping'
curl -I https://affine.stinkyboi.com
```

Expected results: the Argo CD Application is synced and healthy, both
StatefulSets and the AFFiNE Deployment are ready, all four PVCs are bound, the
`vector` extension exists, Redis returns `PONG`, and the public URL starts the
Octelium clientless login flow instead of exposing AFFiNE anonymously.

## Backup, restore, and rollback

Before upgrades, capture a PostgreSQL logical dump and a consistent QNAP backup
of the PostgreSQL, Redis, storage, and config claims. Restore PostgreSQL and the
blob/config claims from the same recovery point. Redis can be restored from its
claim or rebuilt only when queued work loss is acceptable. Roll application
code back through Git; never delete the retained claims as part of a rollback.
