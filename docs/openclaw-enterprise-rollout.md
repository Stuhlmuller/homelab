# OpenClaw Enterprise Replacement

This runbook tracks the fresh stock Enterprise replacement. The standalone
OpenClaw gateway and scheduled backup writer are stopped by GitOps; their
volumes remain mounted read-only for the offline archive. No Discord, LiteLLM,
history, identity, jobs or tools move into the
new agent. The [specification](../specs/003-replace-openclaw-enterprise/spec.md),
[task order](../specs/003-replace-openclaw-enterprise/tasks.md), and
[validation guide](../specs/003-replace-openclaw-enterprise/quickstart.md)
define acceptance; this page owns operator stop and recovery decisions.

## Release identity and private evidence

Every mutation must run from current protected `main` through the declared
workflow with its exact `expected_sha`. The workflow verifies the SHA again
before using credentials, takes a serialization lock, and accepts only fixed
stage names. Keep full inventories, logs, backup manifests, diagnostics,
credential material and durable reconciliation journals outside Git with
restricted permissions. Record their content hashes, source SHA, selected OCI
digests, workflow run, stage, time and pass/fail only in the sanitized
[acceptance ledger](evidence/openclaw-enterprise-acceptance.md). A missing or
ambiguous receipt is a failed gate, not permission to retry a mutation blindly.
The pinned `cmd/occ` Linux amd64 binary is built with Go 1.27.1 and a reviewed
SHA-256, then packaged with the controller/runtime images through the protected
Enterprise image workflow. The same workflow builds, signs and fully pulls the
repository-owned journal operator image from an exact clean `main` commit; its
embedded source SHA must match the dispatcher declaration. Record the verified
CLI and operator image digests before replacing their null declarations.

The [operations workflow](../.github/workflows/openclaw-enterprise-operations.yml)
has a fixed `bind-installation` lane. It rechecks current `main` after checkout,
runs under the protected production environment and shared operations queue,
pins the reviewed binder checksum, and withholds private output. The binder
can annotate only the already reviewed startup Secret after proving the live
Installation, Pod, and Secret identities; the patch uses UID/resource-version
preconditions. The lane requires the owner-controlled, 0600 bootstrap service
key at the fixed `bootstrap.serviceKeyFile` path. No declared runner currently
delivers that private file, so hosted dispatch fails before binding. Do not
dispatch it until credential delivery and the dormant Installation are proven.
The fixed `full-sync` lane can sync both Applications only after a reviewed
`installationPhase` and source registration; the current `unselected` phase
blocks it before cluster access. Reconcile, stop, verification, restore and
acceptance remain reserved and fail closed. The GitHub runner has no durable
shared mount for `privateJournal.mountPath` in
[`openclaw-enterprise.json`](../scripts/config/openclaw-enterprise.json).
Copying a runner-local journal after a command exits would lose a pending API
intent if that command or runner stops mid-operation. T043 remains open until a
declared private runner mounts the same journal and lock across retries, and the
remaining runtime and recovery stages have tested source-owned paths.
Read-only verification never sends inference. Native-origin and browser checks
need the owner's OCE session and remain T048 acceptance evidence.

The legacy archive and new Enterprise recovery set use separate private
locations and access grants. Retain the old local databases, NAS workspace,
historical `pre-2026.9.2-runtime` checkpoint, PVs and credentials until a
separate reviewed disposal decision. New recovery includes PostgreSQL,
tenant metadata/secrets, agent volume, bootstrap files, auth secret and private
gateway identity. Verify independent restores; backup listings alone do not
prove recovery.

The declared off-NAS destination is the versioned, encrypted
`operator/application-backup-storage` bucket. It was created by protected
Terragrunt apply `39110519607`, with versioning, KMS encryption and public-access
block verified. For a fresh installation, after the bucket change reaches
protected `main`, dispatch
`.github/workflows/terragrunt-apply.yml` at that exact `expected_sha` with
`application_backup_storage=true` and no Argo CD target. This scopes the
saved-plan and policy-checked apply to the archive bucket, avoiding unrelated
pending stack changes. Verify the bucket and an upload/download restore before stopping the legacy
writer. The separate application-backup service remains inactive. The archive
worker runs detached because the prior long Kubernetes exec stream disconnected;
a distinct `publish-archive` stage is required after its private result appears.
Publication streams bounded multipart parts and checks the complete byte count
and SHA256 before S3 completion. Its run SHA/ID is the offsite archive reference
for `verify`; the original archive worker SHA/ID remains the source reference.
On failure, the protected job exposes only a fixed category. Upload categories
separate source reads, S3 multipart calls and digest mismatch. After upload,
`publication-archive-head` and `publication-archive-metadata` check the completed
object; `publication-receipt-upload` and `publication-receipt-head` check the
receipt object; `publication-restore-*` identifies which offsite restore step
failed. Private error details stay withheld. None is an offsite restore receipt.
Before upload, `baseline-s3-read` identifies the offsite baseline fetch,
`baseline-mounted-compare` checks its retained mounted copy, and
`baseline-source-status` checks stopped-source identity. The detached result,
observed inventory and receipt, destination absence, and source size have
separate `publication-*` categories. These labels identify the failing
operation without publishing private paths, content or credentials.
Exact-main [run `39459571090`](https://github.com/Stuhlmuller/homelab/actions/runs/39459571090)
passed credentials but failed `publication-source-read` with 64 MiB Kubernetes
exec ranges. The uploader now assembles each 64 MiB S3 part from at most 8 MiB
exec slices. That attempt produced no offsite receipt.
Exact-main [run `39466313228`](https://github.com/Stuhlmuller/homelab/actions/runs/39466313228)
completed the bounded multipart uploader, then failed in the former broad
`publication-version` category at 2026-10-20 20:34:59 UTC. That category cannot
distinguish object metadata, receipt upload/version, or archive and receipt restore.
That attempt did not produce a final versioned, independently restored receipt.
Keep the retained local source and failed-run S3 objects.
[Archive launcher `39366476872`](https://github.com/Stuhlmuller/homelab/actions/runs/39366476872)
produced the private source result. [Exact-main `publish-archive` run
`39501240221`](https://github.com/Stuhlmuller/homelab/actions/runs/39501240221)
used that result and succeeded at 2026-10-21 02:58 UTC. Its reviewed source
requires a versioned upload, offsite restore, archive verification and private
final receipt before success. Later [runs `39700564687`](https://github.com/Stuhlmuller/homelab/actions/runs/39700564687)
and [`39908653791`](https://github.com/Stuhlmuller/homelab/actions/runs/39908653791)
used the publication run as if it were the archive worker; they failed before
upload and do not invalidate the successful publication. Separate [verify run
`39910018168`](https://github.com/Stuhlmuller/homelab/actions/runs/39910018168)
is running against the publication reference. T013 remains open until it passes.
The reader mounts its private scratch volume at `/tmp` because SQLite may need
writable temporary files while independently indexing the archive on a
read-only-root container. A failed detached archive is not a receipt: retain
its partial bundle for diagnosis, verify the reader rollout, and retry the
protected archive stage on a fresh exact `main` SHA. Publish only the new
verified result. The fixed inventory/archive/verify dispatches and compatible
old-service recovery order are in the [OpenClaw runbook](../clusters/homelab/apps/openclaw/README.md#enterprise-replacement-retention).

## Fixed stages and stop gates

The private console is `https://console.oce.stinkyboi.com` through Octelium.
At final cutover, `https://openclaw.stinkyboi.com` must switch from the
suspended legacy backend to the catalog's post-sign-in redirect.
OCE returns each native Agent origin under `*.agents.oce.stinkyboi.com`;
private Traefik accepts only its `agent-<32-hex>` hosts and sends them to the
OCE API, which requires the shared `oce.stinkyboi.com` session and exact Agent
`administer` permission. Apply and verify the Octelium catalog before switching
the old Traefik route; a Git merge alone does not apply that catalog. Do not
enable the Enterprise agent until the console, redirect, native TLS/WebSocket,
and unauthorized-access probes pass.

After the Enterprise API is ready, use an existing authenticated Octelium
operator session from a clean `main` checkout to reconcile only the `oce`
Namespace and two Enterprise Services:

```sh
python3 -I scripts/openclaw-enterprise-access.py
python3 -I scripts/openclaw-enterprise-access.py --execute --expected-sha "$(git rev-parse HEAD)"
```

The script rechecks remote `main` before each write, applies Namespace before
Service, and requires a second no-change apply and identity readback. A stale
SHA, changed auth contract, or failed readback stops the cutover. Rerun it from
the new reviewed `main` after a concurrent merge; do not bypass its guard.

| Stage | Action | Required exit receipt |
| --- | --- | --- |
| Prepare | Confirm source/image pairing, publish all chart-rendered images to Harbor, inventory placement and recovery access | Exact digest and current-main receipts |
| Legacy stop | Archive inventory, verify private space, stop old gateway and scheduled writers via GitOps | Zero Pods, deliveries and uncertain writers |
| Legacy archive | Copy all local/NAS roots offline and restore independently | Full verified archive and compatible restore |
| Platform | Remeasure capacity; upgrade Talos, Istio and Kubernetes one stage/node at a time | Fresh etcd backup, direct access and per-hop health |
| Isolation | Review policies, qualify tainted Talos canary, expand one node at a time | Allowed/denied and lifecycle matrix for every node |
| Foundation | Install shared Envoy/Gateway API, PostgreSQL/TLS, storage, secrets and private access | Health, TLS, exact image and isolated restore |
| Enterprise | Validate hook failure paths, full-sync stock chart, reconcile inactive agent | Hook ordering, private console and source identity |
| Activate | Supply explicit model/key, reconcile and test owner access | Three real conversations, access denials and new-state restore |
| Observe | Monitor 24 hours, then retire obsolete active legacy resources | Stable new service; old archives and PVs retained |

The [21:00 UTC capacity recheck](evidence/openclaw-enterprise-acceptance.md)
still blocks placement: only `acer` has space for the distinct 21 GiB local
claims, but it lacks even the PostgreSQL-plus-gateway memory request; no worker
is an isolated canary. Every worker has unrelated running Pods without canary
taint tolerations and less than 10 GiB free for one new local claim. Freeing
`zimaboard-2` and shifting Grafana would disrupt unrelated single-replica
services, and the measured margin does not cover peaks or rolling overlap.
Do not declare PV nodes or apply a canary taint until the placement,
transient-load and service-continuity review passes.
The [2026-10-23 read-only recheck](evidence/openclaw-enterprise-acceptance.md)
still finds only `acer` with space for a 10 GiB claim; it is 503 MiB short of
the 2,304 MiB database-plus-gateway request. The best worker has 9.00 GiB
filesystem free and its 38 non-DaemonSet Pods request about 3,342 MiB, more
than the other nodes' combined 2,036 MiB unreserved. Source declares both
Crossplane controllers at zero replicas, but two live 256 MiB Pods remain on
`acer`; reconciling that drift would still leave just 9 MiB after the minimum
request and no isolated canary. Rebalancing alone does not admit T022 or T035.

Stop at the first failed stage. Do not force-delete a writer, downgrade
Kubernetes automatically, disable network policy, reuse a legacy key, switch to
an unpaired image, or report a console-only installation as accepted. Stopping
old OpenClaw may leave intentional downtime while platform prerequisites are
prepared. If the old archive/restore fails, leave its retained sources intact
and do not proceed. If later prerequisites fail, use the compatible legacy
restore path after proving the new agent and control-plane writers are stopped.

For a new-service failure, stop the agent through Enterprise's supported API
while the control plane is available, then confirm runtime termination before
quiescing API/worker through GitOps. Preserve both recovery sets. If stop state
or node identity is uncertain, stop the recovery workflow and use the declared
disaster-recovery path; scaling API alone does not stop an agent. The detailed
commands and expected outcomes enter the repository only with the tested
retirement, maintenance and operations helpers; never substitute ad hoc live
`kubectl` or `talosctl` mutations.

Local verification follows the [validation guide](../specs/003-replace-openclaw-enterprise/quickstart.md).
The protected Terragrunt registration path is documented in [CI/CD](ci-cd.md),
and direct Talos/etcd recovery in [control-plane maintenance](talos-control-plane-maintenance.md)
and [etcd backup](talos-etcd-backup.md).
