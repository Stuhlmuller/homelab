# Langfuse

Langfuse is the homelab LLM-observability service. Its operator UI is
`https://langfuse.stinkyboi.com`, protected by the Octelium
`homelab-human-web-access` policy.

The public path is Cloudflare Tunnel -> Octelium `WEB` Service -> Istio
`VirtualService` -> `langfuse-web.langfuse.svc.cluster.local:3000`. Do not add
Tailscale Funnel or a direct Ingress.

The application owns the dedicated `langfuse` namespace and deploys the
Langfuse chart `2.1.1`. The upstream bundled datastores are disabled. The
overlay owns direct, single-replica `Recreate` Deployments for PostgreSQL
(`20Gi`), Valkey (`8Gi`), and ClickHouse (`100Gi`), each on a retained
`nfs-default` PVC. No database operator is installed.

The namespace joins Istio ambient with default-deny authorization. Only the
ingress gateway and declared AI service accounts reach the web service, and
only Langfuse's service account reaches the datastores. Datastore passwords
are mounted as files; the containers run without root and with read-only image
filesystems. ClickHouse receives writable temporary/user-config directories.

Langfuse raw events, uploaded media and batch exports share a dedicated S3
bucket with a 30-day object-retention policy (noncurrent versions expire after
7 days). Media links and export downloads therefore expire too; download any
export needed longer before that limit. This is not a database backup: there is no automatic logical backup or
restore job for PostgreSQL, Valkey, or ClickHouse. Retained PVCs protect
against accidental GitOps deletion but are not an independent recovery copy.
Treat state recovery as unverified until a restore procedure and drill exist.

## Web memory

Web memory request and limit are both `2Gi`; CPU and worker resources are unchanged.
The worker cannot schedule on `zimaboard-2`: its 1 GiB limit can overwhelm that
worker's 1.28 GiB allocatable memory alongside node services and PostgreSQL.
The pinned image uses Node 24 with no runtime heap override. Reserve the full
container budget so scheduling accounts for memory beyond the JavaScript heap.
The pinned-chart check verifies both rendered web memory values.

This is a bounded homelab allocation, below the upstream
[production sizing recommendation](https://langfuse.com/self-hosting/configuration/scaling)
of 4 GiB per application container; it is not a throughput or production-sizing
claim. Before rollout, recheck node requested/available memory, MemoryPressure
and rolling-update surge capacity. Accept only after web initialization,
readiness and authenticated UI access succeed without heap aborts; verify real
ingestion separately. Keep live measurements and logs private.

## Database startup and retained recovery state

The web container applies database schema upgrades before starting HTTP. Chart
`2.1.1` has no web startup probe; `langfuse.web.livenessProbe.initialDelaySeconds:
600` gives initialization ten minutes before liveness checks begin. Readiness
withholds traffic until the app is ready. The pinned-chart regression verifies
this allowance and rendered replica counts.

`recovery-pvc.yaml` retains the `langfuse-migration-recovery` claim with
`Prune=false,Delete=false`. Its private artifacts contain database DDL and
schema history; do not remove this claim during workload cleanup. It is on the
same NAS and provides neither an independent backup nor verified general
restore coverage. No recovery script or one-shot Job is deployed.

If startup fails, use a reviewed change setting global, web, and worker replicas
to zero while preserving datastore and recovery claims. Check all writer Pods
have stopped before a separately reviewed recovery. Never reset PVCs, force
schema versions, or replay historical recovery commands against live data.

```sh
nix develop --command bash scripts/ci/langfuse-startup-check.sh
kubectl -n langfuse get pvc langfuse-migration-recovery
```

## Valkey offline capture and candidate inspection

On October 10, 2026, the pinned Valkey 8.0.11 process rejected
`appendonly.aof.4.incr.aof` as malformed after loading its base RDB. The worker
restarted repeatedly. HTTP readiness of the web service does not prove event
ingestion while the queue is unavailable.

[`scripts/langfuse-valkey-recovery.py`](../../../../scripts/langfuse-valkey-recovery.py)
supports separate capture and explicitly approved promotion modes. Capture
required a read-only inspector; promotion used a writable inspector while web,
worker and Valkey replicas stayed at zero. The inspector had no credentials,
API token or network access; its image root was read-only. The prior revision
pruned it before this writer restart. PostgreSQL, ClickHouse and all retained
claims are unchanged. UI and ingestion need live verification after restoration.

For the completed inspection, build the matching checker from the official
Valkey 8.0.11 source at commit
`4bf1df6441949d70b38e748ffe39daaca9f6f89c`, using
`make -j4 MALLOC=libc BUILD_TLS=no valkey-check-aof`. Capture ran from a clean
checkout of the exact merged read-only-inspector revision after both PVC and
volume-mount `readOnly` fields were true and all three writers had stopped.
The following capture command is historical; without that inspected revision
and Pod it cannot run against current `main`.

```sh
python3 -I scripts/langfuse-valkey-recovery.py \
  --capture-cluster --expected-sha '<merged-main-sha>' \
  --destination /private/durable-off-nas/new-valkey-inspection \
  --checker /private/valkey-8.0.11/src/valkey-check-aof
```

The destination must not exist; its parent must exist on durable private
off-NAS storage with room for five copies plus 64 MiB. Do not use an ephemeral
temporary directory. The helper checks the canonical cluster endpoint, stopped
Deployments, absence of writer Pods, and the inspector's read-only mount before
capture. It streams `original.tar` locally and verifies source hashes and Pod
identity again afterward. The private (0700) directory retains that archive,
its SHA-256 digest, extracted `source`, and `inspection/` containing an
unmodified `original`, separately repaired `candidate`, checker logs and
`report.json`. Source changes, unsafe archive/manifest paths, reused destinations,
checker errors and invalid candidates fail closed. Only the candidate is ever
passed to `--fix`. The report measures discarded bytes, not lost event count;
inspect it privately before requesting approval for a live replacement. Keep a
separate off-NAS backup: a directory on the same NAS is not disaster recovery.

On October 10, the operator approved the verified prefix repair: only
`appendonlydir/appendonly.aof.4.incr.aof` changes, from 10,328,329 to
9,987,809 bytes (340,520 bytes discarded). This does not quantify lost events.
The following command was run from the clean, exact merged promotion revision
while the writable inspector was present. It cannot be rerun from current
`main` because the inspector was removed:

```sh
python3 -I scripts/langfuse-valkey-recovery.py \
  --promote-cluster /private/durable-off-nas/existing-valkey-inspection \
  --expected-sha '<merged-main-sha>' --approved-discarded-bytes 340520
```

Promotion verifies the archive checksum and contents, unchanged original,
candidate hashes, one prefix-only truncation and exact approved byte loss.
It requires all writers stopped, the expected PVC/image and a writable
inspector without credentials. It uploads a private staging file, rechecks
Pod identity and original/staged hashes, then atomically renames that one file.
It never runs `--fix` against live data and never starts writers. A retry
accepts an exact already-promoted set; drift or unexpected staging files stop
recovery. Keep writers stopped on failure and inspect retained files before
retrying. Do not restore the corrupt original and restart it as rollback.

On October 10, the approved candidate was installed and its live hashes
verified. The first GitOps follow-up removed the inspector while all writers
remained stopped. Argo observed merged `836e7f0f`, pruned the inspector, and
reported Synced/Healthy at 22:05 UTC; no Pod mounted
`langfuse-valkey-data`. This revision restores global/web/worker and Valkey
replicas to one. Preserve the private original and all PVCs throughout
recovery. Merely restarting the corrupt original does not restore service.
Require stable Valkey and worker readiness, then fresh correlated Langfuse
generations from each caller. Safety tests cover offline guards and candidate
isolation. Run the native checker fixture with
`python3 -I scripts/ci/langfuse-valkey-recovery-test.py --checker <checker-path>`;
synthetic corruption tests do not establish production recovery.

Source: [Valkey persistence and AOF corruption](https://valkey.io/topics/persistence/).

## ClickHouse diagnostic quarantine

Six `system` log tables had corrupt parts and repeated failed merges, generating
heavy NFS metadata traffic and delaying Plex playback on the shared QNAP.
`clickhouse-log-quarantine.xml` disables those six log writers and permanently
detaches their tables before metadata loading. A non-root init container
creates the pinned server's native empty `.sql.detached` markers; it retains
the original `.sql` metadata and data files; Langfuse's `default` database and healthy system logs are unchanged.
These six SQL diagnostic histories stop recording while quarantined.

The generated ConfigMap syncs at wave `-2`, before the datastore deployment at
wave `-1`; its hash replaces the ClickHouse Pod when configuration changes.
The init container resolves the Atomic system database UUID and validates its
metadata alias plus all six table/marker paths before creating any marker.
Unexpected metadata, symlinks, or nonempty markers stop startup. Missing tables
on fresh installs and already-detached tables are no-ops. This is a short ClickHouse outage during the existing `Recreate` rollout.

```sh
nix develop --command python3 -I scripts/ci/clickhouse-log-quarantine-test.py
# Requires a local Linux Docker engine; CI runs this against the pinned image.
nix develop --command python3 -I scripts/ci/clickhouse-log-quarantine-test.py --runtime docker
```

After Argo CD observes the merged revision, verify ClickHouse readiness and use
an authenticated, read-only client to check `system.detached_tables`: the incident's
`error_log`, `histogram_metric_log`, `opentelemetry_span_log`, `part_log`,
`query_log`, and `text_log` must all have `is_permanently=1`. None may remain in
`system.tables` or `system.merges`. Confirm error counters 33/117 stop increasing,
Langfuse tables remain readable, NAS metadata traffic falls, and Plex start/seek
improves. Fresh installs legitimately have no detached tables.

Rollback requires a reviewed forward recovery: remove the quarantine init
container first, keep affected writers disabled, then repair and deliberately
reattach the retained tables through a repository-owned recovery path. A config
revert does not reattach tables; blindly reattaching corrupt parts restarts the
merge failures. Do not delete retained files. The cause of the corruption and
independent datastore backup/restore remain unresolved storage work.

The marker is an internal format, so the init container must use the same
pinned image as the server. CI reproduces overlapping parts that prevent
ordinary startup, then verifies quarantine preserves the files and application
data across restart. See the [native marker implementation](https://github.com/ClickHouse/ClickHouse/blob/f0cf8bd49aa0956d1f8709dfc7a81857aea915b5/src/Databases/DatabaseOnDisk.cpp#L326-L345),
[metadata loader](https://github.com/ClickHouse/ClickHouse/blob/f0cf8bd49aa0956d1f8709dfc7a81857aea915b5/src/Databases/DatabaseOrdinary.cpp#L269-L317),
and [ClickHouse DETACH](https://clickhouse.com/docs/reference/statements/detach)
and the [incident evidence](../../../../openwiki/operations/plex-recovery-2026-10-05.md).

## Validation

Use the protected full Terragrunt apply or its dependency-aware
`argocd_app=langfuse` dispatch. Both reconcile the **entire shared SSM unit**
(including its existing parameter adoption), then Langfuse S3, then Application
registration, with policy-checked saved plans. Review the private SSM plan for
unrelated changes before approving production; this is not a Langfuse-only
secret update. PR plans exclude both secret-bearing AWS units.

The targeted path requires the existing `homelab` AppProject destination,
sources and Namespace permission, Synced/Healthy external-secrets, cert-manager,
Istio and platform-storage Applications, established workload CRDs, Ready
`aws-ssm` ClusterSecretStore and `nfs-default` StorageClass. It checks these
before state repair or prerequisite writes. If a check fails, reconcile the
platform through its declared path first; do not bypass the check. It skips
bootstrap, node labels, AzureAD, other Application registrations and Kubernetes
Secret materialization, and never advances the full-apply checkpoint.

Before production approval, use an authenticated operator AWS session from a
clean checkout of the reviewed current `main`. In `nix develop`, generate and
privately review both plans without importing state or applying anything:

```sh
(
set -euo pipefail
umask 077
git fetch origin main
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = '<reviewed-main-sha>'
test "$(git rev-parse origin/main)" = '<reviewed-main-sha>'
plan_dir="$(mktemp -d /tmp/homelab-langfuse-review.XXXXXX)"
printf 'Private plan directory: %s\n' "$plan_dir"
(cd IaC && terragrunt stack generate)
for unit in aws-ssm-parameters langfuse-blob-storage; do
  (
    cd "IaC/live/$unit"
    terragrunt run --download-dir "$plan_dir/cache/$unit" -- init -no-color >"$plan_dir/$unit.log" 2>&1
    terragrunt run --download-dir "$plan_dir/cache/$unit" -- plan -out "$plan_dir/$unit.plan" -no-color >>"$plan_dir/$unit.log" 2>&1
    terragrunt --log-disable run --download-dir "$plan_dir/cache/$unit" -- show -json "$plan_dir/$unit.plan" >"$plan_dir/$unit.json" 2>>"$plan_dir/$unit.log"
  )
  conftest test --policy policy "$plan_dir/$unit.json" >"$plan_dir/$unit.policy.log" 2>&1
done
)
```

The plan files, backend metadata and logs can contain secrets; their download
cache stays inside the private directory, outside the checkout. Keep it private.
Review all shared SSM changes, including reader IAM policies and generated
secrets. If existing parameters require adoption, resolve their ownership
through the documented full path before proceeding. CI **replans** against
live state, checks policy and immediately applies its own saved plans; it does
not pause for another plan approval. Recheck if the commit or live state changes.

After reviewing the exact current `main` commit and private plans:

```sh
gh workflow run terragrunt-apply.yml --ref main \
  -f expected_sha='<reviewed-main-sha>' -f argocd_app=langfuse
```

Obtain normal `homelab-production` approval and require that exact run to
succeed. Do not treat registration as runtime readiness. Initial login is
`operator@stinkyboi.com`, with the generated password at
`/homelab/langfuse/init-user-password` in SSM (`us-west-2`). Retrieve it only
through authenticated private secret access; never paste it into PRs or logs.
[Headless initialization](https://langfuse.com/self-hosting/administration/headless-initialization)
creates missing resources rather than resetting existing users.

```sh
kubectl kustomize clusters/homelab/apps/langfuse
kubectl -n argocd get application langfuse
kubectl -n langfuse get externalsecret,pvc,deploy
scripts/octelium-e2e-check.sh
```

## Caller activation

This change stages Langfuse and its credentials first. Existing OpenClaw and
LiteLLM runtime configuration stays unchanged: an asynchronous protected
apply must not race a caller restart requiring credentials that do not exist.
The old OpenClaw gateway token still aliases the operator master key; the new
`/homelab/openclaw/litellm-app-token` is provisioned independently. Do not rotate
the old parameter during staging.

Before a follow-up activation PR:

1. Complete the protected full `Terragrunt Apply` or its dependency-aware
   `argocd_app=langfuse` dispatch described above. Both plan/policy-check and
   apply SSM/S3 producers before registering Langfuse.
2. Reconcile the separate Octelium Service and public DNS paths. Terragrunt does
   not apply either. The existing `homelab-human-web-access` Policy must already
   exist. Install the pinned client through `scripts/install-octeliumctl.sh` and
   use an existing native operator login. Preview from a trusted checkout:

   ```sh
   nix develop --command python3 -I scripts/octelium-langfuse-reconcile.py
   ```

   The helper reuses the [NOFX carrier](../../../../docs/octelium-nofx-reconciliation.md)
   without changing workstation hosts, DNS, saved client configuration or
   credentials. `--homedir` selects another existing private operator login.
   A browser Portal session alone is not proof of native authentication.
   Before execution, verify the clean, reviewed current `main` **before entering
   Nix**; the helper repeats that guard before opening transport:

   ```sh
   (
   set -euo pipefail
   reviewed_main_sha='<reviewed-main-sha>'
   test -z "$(git status --porcelain=v1 --untracked-files=all --ignore-submodules=none)"
   test "$(git rev-parse HEAD)" = "$reviewed_main_sha"
   test "$(git ls-remote https://github.com/Stuhlmuller/homelab.git refs/heads/main | cut -f1)" = "$reviewed_main_sha"
   nix develop --command python3 -I scripts/octelium-langfuse-reconcile.py \
     --execute --expected-sha "$reviewed_main_sha"
   )
   ```

   This applies only `langfuse.default`, never Policies, Users or credentials;
   it requires a no-change second apply and verifies the non-anonymous human
   policy and routing contract afterward. Native errors fail closed, including
   CLI errors reported with exit zero. Do not add `--prune`. Repair or roll back
   the declared Service through a reviewed PR and rerun the helper; removing
   the helper does not remove the live Service or bypass its human policy.
   Wait for Argo CD's `octelium-public` Application to be
   Synced/Healthy with the new tunnel pod revision before dispatching DNS:

   ```sh
   gh workflow run octelium-public-tunnel.yml --ref main -f expected_sha='<reviewed-main-sha>'
   ```

   Obtain normal `homelab-production` approval and require that exact run to
   succeed. If `main` changed, review the new commit before redispatching; do
   not bypass SHA or environment gates or edit DNS in the provider console.
3. Verify the Langfuse Application is Synced/Healthy, datastore and retained
   recovery PVCs are Bound, the project is initialized, and the authenticated
   UI opens through Octelium.
   Verify `langfuse-secrets` and `litellm-app-keys`
   ExternalSecrets are Ready without printing their values.
   Run `nix develop --command python3 scripts/octelium-tunnel-check.py` and
   `scripts/octelium-e2e-check.sh`; DNS/catalog/backend or login failures block
   caller activation. An unauthenticated redirect alone is not UI acceptance.
4. Implement caller activation in a separate PR. This foundation intentionally
   contains no activation patch or gateway callback implementation: the prior
   candidate allowed request-level logging overrides before the pre-call hook
   and on authentication failures. Require production-matched regressions for
   the complete admission/startup path before enabling app authentication or
   callbacks. Preserve newer image, timeout, provider and agent settings.
   Use gateway-only export for routed OpenClaw inference: its native plugin
   emits overlapping per-call and run-total token usage. Remove the
   prerequisites-only staging check and its static-gate invocation when the
   reviewed activation supersedes those invariants; add the actual runtime
   regressions instead. Run the full static gate, review the live plan and
   render/diff affected workloads.
5. After activation, verify one real OpenClaw free-model turn and gateway request
   produce correlated traces with expected provider/model, content and available
   usage. Preserve `openrouter/free` for interactive turns, heartbeat and
   schedules, along with the retained Astra OAuth recovery metadata. Complete
   the separate n8n migration through its managed OpenAI credential and verify
   its own correlated generation.
6. Activate NOFX separately using its
   [image and routing gates](../nofx/README.md#litellm-routing).
   Pin the verified published image pair containing source patch `0013` only
   after LiteLLM and `nofx-litellm` are Ready. Preserve the original
   provider/model and require a real correlated trace without credential leakage.

The activation PR must document rollback of any persisted caller settings,
not just a Helm revert; retain Langfuse data and keys.
The staging merge does not establish inference coverage or a datastore restore
drill. Those acceptance gaps remain in the knowledge base.
