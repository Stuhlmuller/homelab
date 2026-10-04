# Multica

Multica runs in the shared `ai` namespace as the upstream OCI Helm chart
`ghcr.io/multica-ai/charts/multica`. The release includes the Multica frontend,
backend API/WebSocket server, and a dedicated pgvector PostgreSQL instance.

Human access is through Octelium at `https://multica.stinkyboi.com`, routed to
the frontend service. The frontend proxies API, auth, upload, and WebSocket
traffic to the in-cluster backend service, so the backend does not have a
separate browser-facing hostname.

## Upgrade to 0.6.1

The chart, backend, frontend, and runtime CLI are pinned to `0.6.1` together.
Desktop `0.6.1` calls session-renewal and search-index APIs absent from `0.4.29`.
The new backend applies its migrations automatically before serving requests;
the chart allows ten minutes for startup and uses database-independent
`/health` liveness with database-dependent `/healthz` readiness. First-party
self-host telemetry is explicitly disabled with `doNotTrack: "1"`.

Before merging an upgrade, wait for active agent tasks to finish and capture a
private logical database backup plus uploads outside the checkout:

```sh
install -d -m 700 /private/operator/backups/multica
python3 scripts/multica-upgrade-backup.py backup \
  --context admin@homelab --destination /private/operator/backups/multica
python3 scripts/multica-upgrade-backup.py verify \
  --directory /private/operator/backups/multica/<printed-backup-directory>
```

The destination is an operator-specific placeholder. The helper only reads
existing Pods through the declared API. It checks the PostgreSQL custom dump
with `pg_restore`, verifies matching upload contents before and after the dump,
and rejects active tasks, changed attachments/migrations, or changed source
Pods. Claimed, running, and local-directory-waiting tasks must finish; queued
and deferred work remains in the database. Metadata reads are bounded to 30
seconds; archive streaming/validation allows one hour per operation for full
volumes. Archives are mode `0600` in a mode `0700` directory and contain private
application data; never commit or publish them. This is an online backup with
stable uploads, not an atomic snapshot or a tested restore. It excludes the
runtime PVC and external secrets, which must remain intact.

Review [upstream migrations](https://github.com/multica-ai/multica/tree/v0.6.1/server/migrations)
before rollout: this upgrade resets legacy plugin records and removes obsolete
PR references. Pre-upgrade inspection found no rows in the affected plugin and
reference-only PR tables. Reverting only the images does not roll back schema
or data. Recovery requires a reviewed maintenance change that stops writers,
restores the database and uploads from the same capture, restores the previous
chart/image pins, then resumes the workload; preserve the original archives.

After the reviewed merge, dispatch the exact current `main` revision through
`terragrunt-apply.yml` with `argocd_app=multica` to reconcile the chart version.
Argo CD also consumes the committed image pins automatically. Verify chart and
all three Multica binaries are `0.6.1`, all four workloads are Ready, database
queries succeed, and the native desktop's search manifest and session renewal
return `200` with a connected WebSocket. Keep Octelium and fixed-code sign-in
unchanged. Before enabling the declared Harbor mirrors, publish the refreshed
image inventory: all four nodes still used upstream registries during this
upgrade's preflight.

## Server agent runtime

`runtime.yaml` runs a separate, single-replica Multica daemon on `acer`.
Kubernetes restarts it automatically; `Recreate` prevents concurrent daemons
using the same retained `multica-runtime-local` PVC. The volume keeps the CLI
token, daemon identity, Codex state, repositories, and task workspaces across
pod and node restarts. It does not provide node-loss recovery or an off-node
backup. See [storage ownership](../../../../docs/knowledge-base/architecture/storage-and-state.md).

An init container copies the CLI from the same pinned Multica backend image
and installs checksum-verified Codex 0.153.2 binaries. Settings live in
`runtime/settings.json`; automatic CLI updates are disabled so upgrades remain
reviewed GitOps changes. Both CLIs are mounted into `/usr/local/bin` so agent
tasks can invoke them through their normal restricted PATH. `HOME` only supplies
the standard OS home path needed by both CLIs; application settings and
credentials use files.

On first boot, `runtime/bootstrap.py` signs in as `rodman@stuhlmuller.net`
using only the fixed-code key from `multica-backend-secrets`, then creates a
90-day personal token. The daemon renews this token in place. Subsequent boots
reuse it; revoked or expired tokens fail closed. The code is mounted only in
the init container. The daemon has no database credentials, signing secret,
Kubernetes token, host sockets, or other application's home directory.

Codex uses native ChatGPT OAuth. Its login state lives under
`/home/multica/.codex` on the retained runtime PVC and survives pod restarts;
it is not copied into SSM or Kubernetes Secrets. After the first rollout, sign
in once through the pinned CLI's device flow:

```sh
kubectl -n ai exec -it deployment/multica-runtime -- \
  /tools/codex login --device-auth
kubectl -n ai exec deployment/multica-runtime -- \
  /tools/codex login status
```

Never share the device code. Repeat login only if the credential is revoked,
expires, or the PVC is replaced. Before starting a task, inspect every
workspace's agents and clear the retired LiteLLM-only model alias wherever it
appears; an empty model uses the native Codex default:

```sh
kubectl -n ai exec deployment/multica-runtime -- \
  /tools/multica --workspace-id <workspace-id> agent list --output json
kubectl -n ai exec deployment/multica-runtime -- \
  /tools/multica --workspace-id <workspace-id> \
  agent update <agent-id> --model ''
```

The current `Homelab` workspace has only Mika and its model is already empty,
so it needs no migration. The runtime registers in every workspace
accessible to Rodman, including `Homelab`, with one task running at a time.
The dedicated ServiceAccount is allowed to reach only the Multica backend
through its Istio authorization policy. No runtime Service or public listener
is exposed. Multica executes tasks with full access inside this unprivileged
container; Kubernetes is the execution boundary. Flannel currently does not
enforce NetworkPolicy egress isolation.

After Argo sync, verify readiness and the `Homelab Codex` online runtime in
Multica's Runtimes page:

```sh
kubectl -n ai rollout status deployment/multica-runtime --timeout=10m
kubectl -n ai exec deployment/multica-runtime -- \
  /tools/multica daemon status --output json
```

The login status must report a ChatGPT login. The daemon status must be
`running`, list `codex`, and contain workspace runtime IDs. Start one bounded
task and require a successful response before treating OAuth migration as
complete; daemon health alone does not exercise model authentication.
Non-interactive daemon logs are in `/home/multica/.multica/daemon.log` on the
PVC; avoid publishing log contents or CLI configuration containing credentials.
To stop or roll back the runtime, change its replica count to zero in Git and
preserve the PVC/PV. The web app and database are independent of this daemon.

## Sign-in and application storage

Secret material is delivered by External Secrets from AWS SSM Parameter Store
into `multica-secrets` for PostgreSQL and `multica-backend-secrets` for the
backend. The required bootstrap secrets are generated by the
`IaC/live/aws-ssm-parameters` unit:

- `/homelab/multica/jwt-secret`
- `/homelab/multica/postgres-password`
- `/homelab/multica/dev-verification-code` (generated six-digit code)

Email and OAuth providers are not configured. Sign-in uses the same private
six-digit code on every login through `MULTICA_DEV_VERIFICATION_CODE` and
`APP_ENV=development`, following the upstream
[fixed-code setting](https://multica.ai/docs/auth-setup#fixed-local-verification-code).
Retrieve `/homelab/multica/dev-verification-code` from SSM through an authorized
operator session and keep it private. Enter your email, request a code, then
enter that fixed code; the request still expires after ten minutes and must be
repeated after use. Email delivery is unnecessary, but the code prompt remains.

This is a trusted-operator deployment: Octelium's `homelab-human-web-access`
policy remains the outer access boundary. Anyone with the fixed code and app
access can sign in as any existing Multica email. Do not expose this setup
without Octelium or treat the code as per-user identity verification. HTTPS
cookies remain secure because `FRONTEND_ORIGIN` is HTTPS.

The native desktop app has no clientless browser session. A desktop connection
therefore requires an Octelium CLIENT session with data-plane reachability. The
public Cloudflare carrier reaches only Octelium's control-plane API; it does not
carry WireGuard or QUIC traffic to private Services. Native desktop access from
outside the LAN remains unsupported and returns HTTP 401 at the public hostname.
Do not bypass Octelium for `/auth`, `/api`, or `/ws`; the shared development code
is safe only behind this access boundary. The Service preserves Multica's
`Authorization` header for authenticated CLIENT sessions so application JWTs
reach the backend.

Apply the generated SSM parameter through the normal Terragrunt workflow before
the GitOps rollout. The new backend Secret syncs first; switching the chart's
`existingSecret` makes the backend wait for that Secret and rolls its pod.
PostgreSQL keeps its existing Secret. Verify:

```sh
kubectl -n ai wait --for=condition=Ready \
  externalsecret/multica-backend-secrets --timeout=2m
kubectl -n ai rollout status deployment/multica-backend --timeout=5m
```

Then confirm fixed-code sign-in through Octelium and denied unauthenticated
access. Roll back through Git by restoring `appEnv: production` and
`existingSecret: multica-secrets`, then removing the backend ExternalSecret;
retain the SSM parameter. Production
ignores fixed codes, so configure email or Google OAuth before restoring normal
multi-user authentication.

PostgreSQL data and backend uploads use `nfs-default` PVCs. Preserve both PVCs
on rollback unless intentionally rebuilding the Multica instance from scratch.

PostgreSQL startup and liveness allow 30 minutes for NFS recovery, with a
120-second shutdown grace period, matching the other NFS-backed app databases.
Readiness executes `SELECT 1` and removes an unusable database from its Service
after six failed checks; accepting connections alone does not prove queries
work. This avoids repeatedly interrupting slow recovery while keeping failed
queries out of service.

After the reviewed GitOps rollout, verify one ready replica, stable restart
counts, and query execution:

```sh
kubectl -n ai rollout status deployment/multica-postgres --timeout=35m
kubectl -n ai get pods \
  -l app.kubernetes.io/name=multica,app.kubernetes.io/component=postgres
kubectl -n ai exec deployment/multica-postgres -- \
  psql -U multica -d multica -Atqc 'SELECT 1'
```

The query must print `1`. Repeated NFS errors need NAS/network diagnosis;
preserve the PVC and never remove PostgreSQL locks while a writer may be alive.
Reverting these probe settings through Git does not change the image or data,
but restores the unsafe short recovery window.
