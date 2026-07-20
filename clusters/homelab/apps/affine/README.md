# AFFiNE

AFFiNE runs as a self-hosted collaborative knowledge base at
`https://affine.stinkyboi.com`. Public internet reachability terminates at the
shared Cloudflare Tunnel and passes through an anonymous Octelium `WEB` Service
to the Istio gateway. AFFiNE owns end-user authentication. This exception to
the normal clientless-login boundary is required because stock AFFiNE Desktop
must reach `/graphql`, auth endpoints, blobs, and Socket.IO directly.

## Runtime contract

- AFFiNE server: `ghcr.io/toeverything/affine:0.26.3`, one replica on port
  `3010`, with the upstream `/info` health endpoint.
- Database: dedicated PostgreSQL 16 plus pgvector, authenticated with
  `/homelab/affine/postgres-password` and persisted on a 20 Gi
  `nfs-default` claim. Checkpoints are spaced at 15-minute intervals and spread
  across each interval, full-page WAL images are compressed, and PostgreSQL I/O
  timing is enabled for post-rollout verification. Synchronous commit remains
  enabled; the tuning does not trade committed database durability for speed.
  Startup and liveness failures tolerate a 30-minute QNAP recovery window, and
  shutdown receives 120 seconds to finish. During the 2026-07-20 incident, the
  StatefulSet is intentionally fenced at zero replicas until the old pod is
  confirmed absent and a separate repository-owned recovery hook clears its
  stale `postmaster.pid` before restoring one replica.
- Cache and jobs: dedicated authenticated Redis 8.2 with AOF and RDB
  persistence disabled, matching AFFiNE's official deployment model. Redis
  runtime files use a 256 Mi node-local `emptyDir`, so cache and queue churn
  cannot issue NFS writes. The former 5 Gi NFS claim remains mounted read-only
  at `/retained-data` for rollback and is not active Redis storage.
- Application state: uploaded blobs use a 50 Gi retained PVC; the AFFiNE config
  directory uses a 1 Gi retained PVC. The committed `config.json` is mounted
  read-only so security, storage, and URL behavior remain declarative.
- Signing identity: `/homelab/affine/private-key` is an OpenTofu-generated P-256
  ECDSA private key stored as an encrypted SSM SecureString and materialized by
  External Secrets. Do not rotate it without invalidating sessions and planning
  encrypted-data recovery.
- Database migrations: the digest-pinned AFFiNE image runs
  `scripts/self-host-predeploy.js` as an init container. The Deployment uses
  `Recreate`, so the previous server stops before the replacement pod migrates
  the database and starts the new server.
- Copilot: disabled. The current homelab LiteLLM catalog exposes a text model
  but not AFFiNE's required embedding and image capabilities. Add the complete
  model set and a file-backed secret contract before enabling it.
- SMTP: not configured because the homelab does not own a shared SMTP provider.
  Do not add mail credentials to `config.json`; introduce SSM parameters and
  ExternalSecret mappings before enabling password-reset or invite delivery.

## First login

Open `https://affine.stinkyboi.com` and sign in with an existing AFFiNE account,
or enter that URL in AFFiNE Desktop's self-hosted connection dialog. Public
signup is disabled because the intended accounts already exist. Re-enable it
only for a time-bounded, reviewed account bootstrap and bump the Deployment's
`homelab.rst.io/config-revision` annotation so the subPath-mounted config is
loaded by a new pod.

## Validation

### Recovery phase 1: fenced

```sh
kubectl kustomize clusters/homelab/apps/affine
kubectl -n argocd get application affine
kubectl -n affine get statefulset affine-postgres \
  -o jsonpath='{.spec.replicas}{" "}{.status.currentReplicas}{"\n"}'
kubectl -n affine get pod affine-postgres-0 --ignore-not-found
kubectl -n affine get pvc data-affine-postgres-0
```

Expected phase-one results: Argo CD reports the Application synced, the
StatefulSet prints desired replica count `0` with no current replica, the pod
lookup prints nothing, and the retained PostgreSQL PVC remains `Bound`. Do not
run the recovery hook until all four conditions hold.

### Recovery phase 2: restored

```sh
kubectl -n affine get deploy,statefulset,pod,pvc,svc,externalsecret
kubectl -n affine exec statefulset/affine-postgres -- \
  psql -U affine -d affine -c 'select extversion from pg_extension where extname = '\''vector'\'';'
kubectl -n affine exec statefulset/affine-redis -- /bin/sh -ec \
  'redis-cli --no-auth-warning -a "$(cat /run/secrets/affine/REDIS_PASSWORD)" ping'
kubectl -n affine exec statefulset/affine-redis -- /bin/sh -ec \
  'redis-cli --no-auth-warning -a "$(cat /run/secrets/affine/REDIS_PASSWORD)" info persistence | grep -E "^(aof_enabled:0|rdb_bgsave_in_progress:0)"'
kubectl -n affine exec statefulset/affine-postgres -- \
  psql -U affine -d affine -Atc \
  "select name || '=' || setting from pg_settings where name in ('checkpoint_timeout', 'checkpoint_completion_target', 'wal_compression', 'track_io_timing', 'track_wal_io_timing') order by name;"
curl -I https://affine.stinkyboi.com
curl -sS -X OPTIONS -D - -o /dev/null \
  -H 'Origin: assets://.' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type,x-affine-version,x-operation-name' \
  https://affine.stinkyboi.com/graphql
```

Expected post-recovery results: the Argo CD Application is synced and healthy,
both StatefulSets and the AFFiNE Deployment are ready, all four PVCs are bound,
the `vector` extension exists, Redis returns `PONG` with AOF disabled and no RDB
save in progress, PostgreSQL reports the committed NFS-aware settings, and the
native-client CORS preflight returns `200` or `204` with
`Access-Control-Allow-Origin: assets://.`.
Unauthenticated users may reach AFFiNE's public shell and server-discovery API,
but the e2e gate must receive `AUTHENTICATION_REQUIRED` for an anonymous
workspace query before this route is considered safe.

## NFS interruption recovery

The PostgreSQL readiness probe removes the database Service endpoint after six
failed checks, but kubelet allows up to 30 minutes before restarting the
container. This favors recovery in place because killing PostgreSQL while its
NFS volume is stalled forces crash recovery and can leave `postmaster.pid`
behind. If a restart is eventually required, kubelet allows 120 seconds for a
clean shutdown.

Recovery from the 2026-07-20 stale-lock incident is intentionally staged. Phase
1 sets the StatefulSet to zero replicas and does not modify the PVC. After Argo
CD confirms `affine-postgres-0` is absent, phase 2 may clear only
`pgdata/postmaster.pid` with a repository-owned hook and then restore one
replica. Never force-delete the pod or remove the lock while an old node could
still run PostgreSQL against the NFS volume.

After an interruption, confirm that `affine-postgres-0` becomes ready without a
growing restart count and that its logs reach `database system is ready to
accept connections`. Repeated NFS timeouts or a recovery-hook failure means the
QNAP export is still unhealthy; inspect the NAS pool, disks, and wired network
path before retrying a rollout. Preserve the PostgreSQL PVC throughout
recovery.

## Backup, restore, and rollback

Before upgrades, capture a PostgreSQL logical dump and a consistent QNAP backup
of the PostgreSQL, storage, and config claims. Restore PostgreSQL and the
blob/config claims from the same recovery point. Redis is intentionally
ephemeral: a pod or node restart clears caches and can discard queued work, so
verify background jobs after recovery. The former Redis AOF claim is retained
only as a rollback artifact while this mitigation is evaluated. Roll
application code back through Git; never delete retained claims as part of a
rollback.
