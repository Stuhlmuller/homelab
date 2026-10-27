# Implementation Plan: Fresh OpenClaw Enterprise Replacement

**Branch**: `codex/openclaw-enterprise`; Spec Kit feature ID `003-replace-openclaw-enterprise`

**Date**: 2026-10-17 | **Spec**: [spec.md](spec.md)

**Input**: `specs/003-replace-openclaw-enterprise/spec.md`, revised by the owner's
fresh-replacement clarification during planning.

**Status**: Research, design, [task generation](tasks.md), and the initial
prerequisite catalog are prepared. Production gates below are not passed. This
plan performs no shutdown or deployment.

## Summary

Archive and stop standalone OpenClaw, then install stock OpenClaw Enterprise with
one fresh Embedded OpenClaw agent. Preserve legacy data for recovery; do not port
Discord, LiteLLM, old jobs, identity, history, or tools. No controller/runtime fork.

First establish supported Talos/Kubernetes/Istio versions and actual NetworkPolicy
enforcement. Use firewall-only kube-router while retaining Flannel, kube-proxy,
and Multus. Use existing Terragrunt/Argo, Harbor, External Secrets, Octelium, and
cert-manager patterns. Give Enterprise separate PostgreSQL, local agent state,
private browser access, and repository-owned installation/upgrade hooks.

## Technical Context

**Language/Version**: Existing HCL, YAML, Bash, Python 3 and Nix; checksum-pinned
upstream Node 24 preflight in the matching controller image. No new app framework.

**Primary Dependencies**: Talos 1.14.4; Kubernetes 1.35.9; Istio 1.30.6;
kube-router 2.11.1; stock OCE source `33bb74590a749f37934da4502fca6035cd234a55`;
Envoy Gateway 1.9.2; Gateway API 1.6.1 experimental CRDs; Envoy Proxy
distroless-v1.39.3; PostgreSQL 18.6.
Exact rendered transitive images and chart digests enter the publication lock
before consumption. Recheck security/support advisories when implementing.

**Storage**: Dedicated local PostgreSQL data; OCE-owned 10Gi RWO gateway claim
on SQLite-compatible retained local storage; private bootstrap volume; independent
verified database/configuration/secret/agent backups. Retain old local and NAS state.

**Testing**: Existing Nix/static/Conftest/Terragrunt/Helm gates; narrow Python
fixtures for lifecycle/provisioning/archive boundaries; real Talos canary network
and restart tests; isolated restore; browser/WebSocket and real model acceptance.

**Target Platform**: Existing four-node amd64 Talos cluster. No automatic failover
or new hardware assumed. OCE namespaces remain outside ambient mesh initially.

**Project Type**: Production infrastructure and application replacement.

**Performance Goals**: Three consecutive successful owner conversations; no legacy
writes/deliveries after shutdown; 24-hour healthy observation; no regressions in
DNS, access, storage, controllers, or shared applications.

**Constraints**: Capacity/canary allocation currently blocks execution. No manual
live fixes, unverified image substitutions, automatic Kubernetes downgrade,
secret disclosure, or old-data deletion. Fresh agent activation requires explicit
model/key configuration and a real model probe.

The 2026-10-17 read-only refresh in [research.md](research.md#r4--capacity-is-a-real-execution-gate)
confirmed the starting versions and no canary/CRDs. Istio 1.27.9 is unnecessary
before the selected 1.28.10 hop because no Gateway API CRDs are installed.

**Scale/Scope**: One installation, one fresh owner-scoped agent. No channels,
optional broker/collector, Codex Harness, inherited assistant schedules, or
cluster-wide internet destination filtering beyond the selected policy contract.

## Constitution Check

The constitution is an unfilled template. Apply repository `AGENTS.md` instead.

| Gate | Before research | After design |
| --- | --- | --- |
| Repository-owned desired state and protected delivery | Pass | Pass: maintenance inputs, Argo hooks and reconciler contracts |
| Public-repo secret boundary | Pass | Pass: references, private receipts and mounted/controller-managed credentials |
| Preserve personal state and shared dependencies | Pass | Pass: archive-first shutdown and separate recovery stores |
| Smallest complete scope | Pass | Pass: stock fresh installation; no legacy compatibility fork |
| Reproducible root bootstrap | Pass | Pass by design: shared registration plus bounded dependency readiness |
| Validate before production changes | Pass | Pass: explicit gates, none presented as live success |
| Source-linked operational documentation | Pass | Pass: implementation includes source docs and affected wiki maintenance |

No justified policy violations. Failed execution gates are errors, not waivers:
missing capacity, canary, artifact receipt, isolation proof, model input, or backup
verification must stop the owning stage. Phase 1 design passing is not deployment
approval or evidence that those execution gates passed.

## Project Structure

### Documentation (this feature)

```text
specs/003-replace-openclaw-enterprise/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
├── contracts/
│   ├── platform.md
│   └── enterprise.md
└── checklists/requirements.md
```

`tasks.md` sequences implementation and live acceptance; its checked items and
the acceptance ledger record the current evidence separately.

### Source Code (repository root)

Implementation surfaces in the deployment-oriented Terragrunt layout:

```text
.talos/patches/                         # reviewed role/version inputs
scripts/config/platform-maintenance.json
scripts/platform-maintenance.py         # bounded upgrade lane
.github/workflows/platform-maintenance.yml
clusters/homelab/platform/network-policy/
IaC/homelab/us-west-2/apps/platform-network-policy/stack.hcl
IaC/homelab/us-west-2/apps/istio/stack.hcl # sequential version changes
clusters/homelab/apps/istio/
clusters/homelab/platform/envoy-gateway/
IaC/homelab/us-west-2/apps/platform-envoy-gateway/stack.hcl
clusters/homelab/apps/openclaw-enterprise-foundation/
IaC/homelab/us-west-2/apps/openclaw-enterprise-foundation/stack.hcl
clusters/homelab/apps/openclaw-enterprise/ # local values and lifecycle hooks
IaC/homelab/us-west-2/apps/openclaw-enterprise/stack.hcl
scripts/config/openclaw-enterprise.json
scripts/openclaw-enterprise.py           # serialized API reconciliation/verification
scripts/openclaw-retirement.py          # inventory/archive verification and handoff
scripts/ci/*-test.py                    # focused boundary/failure tests
```

Also change each app's adjacent `terragrunt.stack.hcl` unit, node placement
declarations, scoped AppProject, exact SSM/ESO contracts, platform-storage PVs,
Harbor image catalog, Octelium catalog/private DNS, old OpenClaw desired state,
and CI workflow security hashes/policies as required. Do not edit generated
`terragrunt.hcl` or `terragrunt.values.hcl` under `IaC/homelab/us-west-2`.

**Structure Decision**: Reuse existing shared Application registration, operator
maintenance, backup, image publication and private access patterns. New helpers
cover only missing operations; no new generalized operator or scheduler.

## Delivery Sequence and Stop Gates

| Stage | Work and owner | Required exit evidence |
| --- | --- | --- |
| A — prepare | Review full source diff, publish required pinned artifacts, add fixture-tested maintenance/retirement paths, refresh read-only baseline | Exact images, node/storage identity, dependency and policy inventories |
| B — legacy shutdown | Quiesce old gateway/jobs through GitOps; final full archive across local/NAS stores; verify independent recovery; keep replicas zero | No writers/deliveries; verified recovery receipt; retained PVs and credentials |
| C — capacity | Recalculate after stopping old app; allocate a tainted canary and per-node reservations | All steady/transient requests and measured peaks fit; no unrelated eviction |
| D — versions | Talos adjacent-minor ladder, Istio adjacent-minor ladder, then Kubernetes 1.35.9 | Per-node/component receipts, healthy API/etcd/DNS/storage/access/apps |
| E — enforcement | Correct affected ingress/egress policies, deploy firewall-only canary, qualify, expand node-by-node | Complete allowed/denied and lifecycle matrix passes on real Talos |
| F — foundation | Envoy/Gateway API, PostgreSQL roles/TLS, storage, ESO, private identity/routes | Independent dependencies Healthy; backup restore and access tests pass |
| G — Enterprise | Stock chart plus ordered hooks; native IAM; idempotent fresh agent setup | Console healthy, no duplicate resource/grant, lifecycle failure tests pass |
| H — activate | Configure explicit model/key; deploy fresh agent; owner native UI/model tests | Three conversations, access denials, exact active revision, restore proof |
| I — retire | Observe 24h; remove obsolete active routes/jobs/grants selectively | Only new assistant active; old data retained; shared services verified |

Stage B may run before platform rollout to release OpenClaw's own resources.
Downtime can last through prerequisite work. If the final archive or safe shutdown
fails, stop; do not delete the source or proceed as though it is recoverable.
If prerequisites cannot be met after shutdown, restore the old service through
its declared recovery path rather than improvise a partial replacement.

### Platform detail

Use the exact ladders and limitations in [research.md](research.md#r2--upgrade-supported-platform-branches-in-separate-stages)
and [platform contract](contracts/platform.md). Workers upgrade serially, sole
control plane last for each Talos hop. Preserve a verified direct recovery route
independent of mesh/Harbor and fresh off-node etcd backups. Kubernetes changes use
the declared Talos operation, not direct machine-image patch application.

The enforcing DaemonSet receives narrow firewall privileges and owns no CNI,
router, service proxy, or NRI configuration. All 61 current policies require
review against renders and live selectors. Audit ingress in addition to the
existing egress inventory helper. New and existing Pods must preserve DNS,
HBONE/probes where applicable, NFS, APIs, webhooks, image pulls and human/CI access.

### Enterprise ownership and lifecycle

Foundation Application owns PostgreSQL, secret projection, retained storage,
versioned installation input and prerequisites. Platform Application owns Envoy
and Gateway API. Enterprise Application owns the pinned source chart and lifecycle
hooks and one image-pinned EnvoyProxy override. OCE owns its tenant/runtime
resources; Argo must not independently own those
same Deployments, ConfigMaps, Secrets or claims.

Platform Envoy is the sole owner of shared Gateway API CRDs. Keep experimental
1.6.1's compatibility versions for Istio 1.30.6. Pin the proxy image on OCE's
attached EnvoyProxy; changing only the controller's default image is insufficient.
See [routing dependency contract](contracts/enterprise.md#gateway-api-and-private-envoy).

Use a scoped AppProject for required namespaces, upstream chart repository and
specific cluster resource kinds; do not broaden `homelab-workloads` to `*`.
Treat Namespace/Role/ClusterRole permissions as installation capabilities; the
agent itself receives no installation administration or Kubernetes credential.

All hooks in this Application use Helm-style annotations. Order compatibility
preflight before quiescence, then upstream migration/bootstrap, then normal Sync.
Disable inherited `selfHeal`, prohibit selective sync and `ApplyOutOfSyncOnly`,
and serialize releases. Supporting secrets/volumes must already exist before
PreSync. Test cancellation, retry and Argo restart before enabling production.
See [Enterprise contract](contracts/enterprise.md#installation-and-upgrades).

Initial root apply registers the dependency chain and Applications; bounded hooks
wait for runtime readiness. This retains the reproducible initial setup path.
Later maintenance upgrades remain deliberately staged, with a full reviewed sync
as the release unit. No stage may resume old writers after an uncertain migration.

### State and private access

Use a dedicated PostgreSQL 18.6 instance with strict TLS and split application,
migration and administrator credentials. Start with 10Gi local DB storage, 10Gi
local agent storage and 1Gi private bootstrap storage, then verify measured fit
before committing concrete node paths. Local PV capacity is not a filesystem
quota. New classes must not silently fall back to default NFS.

Prepare `openclaw-system` and `openclaw-agents` namespaces, binding the logical
OCE Namespace to the latter through its supported `existingNamespace` input.
Create an OCE-owned fresh agent claim; never adopt old claims. Keep new and old
archives separate and independently recoverable.

Private owner flow: stable OpenClaw URL -> Octelium-authenticated console ->
OCE native exact-Agent authorization -> private Envoy -> agent gateway.
Resolve the native origin from OCE, not a guessed hash. The console and old
redirect use Octelium; only the narrow native HostRegexp goes directly from
private Tailscale/Traefik to OCE API, preserving Host/WebSocket behavior and
the `oce.stinkyboi.com` session cookie.

## Validation and Requirement Coverage

| Requirements | Primary evidence |
| --- | --- |
| FR-001/002/005, SC-001 | Native browser/WebSocket, real model response, unauthorized access tests |
| FR-003/004, SC-002 | Full old-state archive restore, zero writers, no old secrets/jobs in new runtime |
| FR-006/007/008, SC-003 | Platform receipts, real policy lifecycle tests, capacity report |
| FR-009/010, SC-004 | API lost-response/CAS fixtures, permissions/secret scans, full-sync retry tests |
| FR-011/012, SC-004/005 | Stopped-writer migration failure tests, isolated restores, 24h observation |

[quickstart.md](quickstart.md) specifies commands and expected outcomes. Extend
existing static/Conftest gates rather than create a parallel validation framework.
Source changes include workload/recovery runbooks, secret matrix, runtime-isolation
and upgrade docs; update affected generated wiki through its approved maintenance
path, without hand-editing generated state.

## Recovery Boundaries

- Legacy recovery is a compatible image/configuration plus retained full state,
  never an image-only downgrade. Stop OCE agents through its supported lifecycle
  while the control plane still runs; verify zero runtime Pods/writers, then
  quiesce API/worker and archive new state before restoring old service.
- OCE database rollback requires compatible verified state; preserve failed/new
  data before restore. An old agent configuration is a new revision, not a
  filesystem rollback. Do not delete an OCE agent to preserve its owned PVC.
- Stock Agent stop clears the active revision; resuming requires a new deployment,
  because old revisions cannot restart ([pinned Agent API](https://github.com/openclaw/openclaw-enterprise/blob/33bb74590a749f37934da4502fca6035cd234a55/docs/reference/agents.md#L328-L334)).
  Before scheduling T051, prove a complete identity-checked recovery set and
  encrypted off-node destination, then either prove a consistent online snapshot
  or serialize stop, capture, new-revision deployment and failure recovery in a
  durable journal. Keep ordinary unchanged-input reconciliation idempotent.
  The operator journal and Agent gateway-state claims are in different
  namespaces, so one Pod cannot mount both; OCC Secret reads omit value bytes.
  Coordinate namespace-local state and exact tenant Kubernetes Secret capture,
  then publish one immutable completed set. GitHub OIDC publisher identity does
  not authenticate the scheduled in-cluster Job; declare that credential or
  protected publication boundary before T051.
- Talos A/B fallback applies only to the immediately prior verified compatible
  image. Kubernetes has no automatic downgrade path; stop and use reviewed
  forward repair or separately declared disaster recovery.
- Quiesce OCE before disabling enforcement. Removing kube-router leaves rules;
  cleanup must target only proven owned firewall objects. Never blindly run its
  all-controller cleanup against retained Flannel/kube-proxy.
