# OpenClaw Enterprise Replacement

This runbook tracks the fresh stock Enterprise replacement. The current
standalone OpenClaw remains active until the validated archive and shutdown
lane runs. No Discord, LiteLLM, history, identity, jobs or tools move into the
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

The legacy archive and new Enterprise recovery set use separate private
locations and access grants. Retain the old local databases, NAS workspace,
historical `pre-2026.9.2-runtime` checkpoint, PVs and credentials until a
separate reviewed disposal decision. New recovery includes PostgreSQL,
tenant metadata/secrets, agent volume, bootstrap files, auth secret and private
gateway identity. Verify independent restores; backup listings alone do not
prove recovery.

## Fixed stages and stop gates

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
