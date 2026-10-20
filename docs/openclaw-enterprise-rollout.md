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
Enterprise image workflow. Record the signed CLI image digest from that
workflow's verified pull before replacing the null `source.cli.artifactDigest`.

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

The [latest capacity snapshot](evidence/openclaw-enterprise-acceptance.md)
still blocks placement: only `acer` has space for the distinct 21 GiB local
claims, but it lacks even the PostgreSQL-plus-gateway memory request; no worker
is an isolated canary. Freeing `zimaboard-2` and shifting Grafana would disrupt
unrelated single-replica services, and the measured margin does not cover peaks
or rolling overlap. Do not declare PV nodes or apply a canary taint until the
placement, transient-load and service-continuity review passes.

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
