# Tasks: Fresh OpenClaw Enterprise Replacement

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [platform contract](contracts/platform.md),
[Enterprise contract](contracts/enterprise.md), [validation guide](quickstart.md).

**Scope**: Archive and stop standalone OpenClaw; install stock Enterprise and one
fresh Embedded agent. No Discord/LiteLLM continuity, old-state import, or behavior
fork. Only checked tasks have passed. This checklist does not bypass PR checks,
protected workflows, credential boundaries, or rollout gates.

**Tests**: The specification explicitly requires isolation, recovery, retry,
upgrade, and user acceptance tests. Include focused fixtures for those boundaries;
run live scenarios only through declared, validated workflows. Tests precede the
nontrivial implementation they cover; fixtures must expose the intended failure.

**Organization**: The P1 stories use dependency order US2 -> US3 -> US1, followed
by P2 US4. This preserves specification priorities and avoids deploying Enterprise
before its prerequisites. Each story has a separate acceptance checkpoint.

## Format and Execution Rules

- Tasks use `- [ ] Tnnn [P?] [USn?] Description with file path`.
- `[P]` permits concurrent work only within the explicitly listed batches below.
  All prerequisite tasks must already pass; never run live mutations in parallel.
- Paths are repository-relative. Named new files are implementation targets,
  not claims that those files already exist. Reuse surrounding modules/helpers.
- Store detailed inventories, credentials, journals, backups, and failure output
  privately. `docs/evidence/openclaw-enterprise-acceptance.md` holds only sanitized
  source/digest/scenario identifiers and results. Missing evidence stays failed
  or pending; never mark a live task complete from rendering alone.
- Every live task requires its reviewed source on current `main`, matching image
  publication receipts, relevant passing checks, and the declared protected
  workflow. No ad hoc cluster/cloud mutation or generated `IaC/live` edits.
- Recheck external inputs at execution: model/key, canary, capacity, recovery
  copies and artifact provenance. Their absence blocks the dependent task.

## Phase 1: Setup

**Purpose**: Turn the dated design into explicit implementation inputs without
changing live state. The constitution is a template; repository `AGENTS.md` applies.

- [X] T001 Refresh read-only versions, policy/storage inventory and upstream support/advisory evidence in `specs/003-replace-openclaw-enterprise/research.md`; verify the pinned OCE commit and all adjacent upgrade hops, including whether Istio 1.27.9 is required first; reconcile any changed assumptions in `plan.md` before implementation.
- [X] T002 [P] Add `scripts/config/platform-maintenance.json` with the reviewed Talos/Istio/Kubernetes ladder, immutable artifact references, expected starting identities, ordered nodes/stages, deadlines and canary requirements from `contracts/platform.md`; leave execution blocked until measured placement and recovery receipts exist.
- [X] T003 [P] Add `scripts/config/openclaw-enterprise.json` with stock source/image pairing, installation phases, private origins, namespace/agent binding, distinct storage and secret references, private journal/archive contracts and `activationEnabled: false`; absent model/key must never select a default or reuse legacy credentials.

## Phase 2: Foundational Requirements

**Purpose**: Shared artifact, credential and release boundaries. Complete these
before any story implementation; they do not imply platform or app readiness.

- [ ] T004 [P] Extend `scripts/config/harbor-images.json` and use `.github/workflows/harbor-mirror.yml` to publish and verify every selected platform/controller/runtime/CLI/init/database/proxy/test image; inventory transitive images from exact chart renders, preserve source/build pairing, and record immutable receipts in `docs/evidence/openclaw-enterprise-acceptance.md` before
  consumers reference them.
- [X] T005 [P] Declare the exact new SSM producer/reader/consumer contracts in `IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl` and `docs/secrets-aws-ssm.md`, including `/homelab/openclaw-enterprise/model-api-key`, separate DB roles, auth/bootstrap/gateway identity and protected workflow credentials; use references or protected generation/injection, never secret
  values or old credential aliases.
- [X] T006 [P] Create `docs/openclaw-enterprise-rollout.md` and the sanitized receipt ledger `docs/evidence/openclaw-enterprise-acceptance.md`; define fixed release stages, private journal/diagnostic retention, evidence hashes, stop/recovery gates, separate legacy/new archives and current-main checks using existing CI/CD and backup patterns; keep all unrun scenarios pending.

**Checkpoint**: Required artifacts and credential contracts are reviewable; live
operations remain gated. Local development can continue if external secret values
are unavailable, but dependent apply/activation cannot.

## Phase 3: US2 — Stop the Old Assistant Without Losing Recovery Data (P1)

**Goal**: Stop legacy writers and deliveries, retain a verified independent copy,
and preserve a tested compatible recovery path before reclaiming resources.

**Independent test**: Restore every inventoried local/NAS root into isolation;
verify integrity and retained checkpoints, then prove the live old gateway and
schedules remain stopped with zero new writes/deliveries. No Enterprise required.

### US2 tests and implementation

- [X] T007 [P] [US2] Add `scripts/ci/openclaw-retirement-test.py` fixtures for local/NAS coverage, overlapping parent/child PV roots, UID/node mismatch, unsafe archive paths, active/unknown writers, partial archives, missing required data, private diagnostics, and idempotent already-retired optional resources; assert no completion marker on failure.
- [X] T008 [US2] Implement `scripts/openclaw-retirement.py` read-only `inventory`/`verify-archive` and workflow-only `archive` per `contracts/enterprise.md`, reusing existing archive/SQLite integrity helpers; require stopped identity-checked sources, preserve full archives and `pre-2026.9.2-runtime`, and publish completion only after independent restore verification.
- [X] T009 [P] [US2] Prepare explicit stopped desired state in `clusters/homelab/apps/openclaw/values.yaml` and its scheduled-writer sources; preserve retention in `clusters/homelab/platform/storage/openclaw-runtime.yaml` and `IaC/openclaw/stack.hcl`, including prune/finalizer behavior; keep this change staged until the archive/recovery lane is validated.
- [X] T010 [US2] Add `.github/workflows/openclaw-enterprise-operations.yml` with fixed legacy inventory/archive/verification stages, current-main SHA guard, serialized execution, mounted/private credentials and bounded private outputs; add `scripts/ci/openclaw-enterprise-operations-test.py` and update `policy/workflows.rego` plus `policy/workflows_test.rego` for the exact
  reviewed permissions and script hashes.
- [X] T011 [US2] Wire the retirement/workflow checks into `scripts/ci/static-checks.sh`; run the existing OpenClaw assistant/storage/GitHub checks, Conftest, affected Helm renders and authenticated scoped Terragrunt plans from `quickstart.md`; document compatible restore commands and failure handling in `clusters/homelab/apps/openclaw/README.md` before merging shutdown.
- [X] T012 [US2] Run the validated inventory workflow, confirm private archive space/access and retained source identities, then deliver T009 through `.github/workflows/terragrunt-apply.yml` and Argo; verify zero gateway/scheduled-writer Pods and no uncertain node/writer, recording sanitized shutdown evidence in `docs/evidence/openclaw-enterprise-acceptance.md`.
- [ ] T013 [US2] Run the final offline multi-root archive and independent restore through `.github/workflows/openclaw-enterprise-operations.yml`; verify local SQLite databases, NAS workspace/configuration, full archives and historical checkpoint together, and record only the verified receipt reference in `docs/evidence/openclaw-enterprise-acceptance.md`.
- [ ] T014 [US2] Rehearse compatible legacy restoration in isolation using `scripts/openclaw-retirement.py` and `clusters/homelab/apps/openclaw/README.md`; confirm stopped production writers/deliveries remain zero and original PVs/credentials remain retained; mark US2 accepted in `docs/evidence/openclaw-enterprise-acceptance.md` only after T012–T013 pass.

**Checkpoint**: Legacy is stopped and recoverable. If prerequisites later fail,
use this recovery path; do not leave an unverified partial replacement active.

## Phase 4: US3 — Establish Supported Platform Prerequisites (P1)

**Goal**: Prove sufficient capacity, supported component versions, real policy
enforcement and compatible shared routing before Enterprise installation.

**Independent test**: Inspect actual node/component versions; run the full allowed,
denied and lifecycle traffic matrix on an isolated canary and each expanded node;
verify existing app/recovery paths and private routing dependencies independently.

### US3 tests and implementation

- [X] T015 [P] [US3] Add `scripts/ci/platform-maintenance-test.py` for exact SHA/stage/node matching, unsupported hops, artifact substitution, missing recovery evidence, incomplete receipts, interrupted upgrades, unsafe retry and accidental mutation by inspect/validate; explicitly reject treating `upgrade-k8s --dry-run` as read-only.
- [ ] T016 [US3] Implement `scripts/platform-maintenance.py` inspect/validate/execute using the committed input and per-node receipts; prepare role-appropriate target patches under `.talos/patches/`, preserve image-factory schematic/extensions/disk identity, require strict Talos validation, and use ordered upgrade APIs rather than applying Kubernetes image patches to upgrade live nodes.
- [ ] T017 [US3] Add `.github/workflows/platform-maintenance.yml` with fixed current-main upgrade/qualification/owned-cleanup stages, protected authenticated Talos access, concurrency control, private etcd/recovery checks and bounded receipts; reject missing/unvalidated stage helpers, update `policy/workflows.rego` and `policy/workflows_test.rego`, and extend
  `docs/talos-control-plane-maintenance.md` with direct-access recovery and stop conditions.
- [ ] T018 [P] [US3] Audit all currently affected ingress and egress policies using `scripts/network-policy-inventory.py`; create `docs/evidence/openclaw-enterprise-policy-review.json` with sanitized owner paths/render hashes and exact required corrections, then fix the listed source manifests before enforcement; retain strict broad-egress findings and separately record OCE's
  accepted public-443/private-range boundary.
- [ ] T019 [P] [US3] Add `scripts/ci/network-policy-enforcement-test.py`, `scripts/network-policy-qualification.py` and `clusters/homelab/platform/network-policy/canary/kustomization.yaml` with declared traffic fixtures and fixed lifecycle scenarios from `contracts/platform.md`; cover ownership-limited cleanup and refusal to touch foreign rules, reuse inventory logic, store
  detailed results privately, and distinguish fixture success from actual Talos qualification.
- [ ] T020 [US3] Implement pinned firewall-only kube-router in `clusters/homelab/platform/network-policy/daemonset.yaml` with exact contract flags/RBAC and no CNI/NRI/router/service-proxy ownership; add `kustomization.yaml` and workflow-invoked `scripts/network-policy-cleanup.py` that removes only proven owned firewall objects, preserves Flannel/kube-proxy,
  and refuses uncertain ownership or active Enterprise tenants.
- [ ] T021 [US3] Add `IaC/platform-network-policy/stack.hcl` and its `IaC/terragrunt.stack.hcl` unit; extend `IaC/terragrunt-catalog/modules/kubernetes-node-labels/main.tf`, `variables.tf`, `metadata.tftest.hcl` and `IaC/terragrunt-catalog/units/live/kubernetes-node-labels/terragrunt.hcl` only as needed for explicit canary labels/taints; keep deployment disabled until capacity admission,
  with matching test tolerations and infrastructure DaemonSet review.
- [ ] T022 [US3] Remeasure every node after US2 shutdown; commit the concrete safe placement, taint, steady/transient reservations and local-storage allocations in `scripts/config/platform-maintenance.json` and the node catalog inputs; record sanitized measured peaks/headroom in `docs/evidence/openclaw-enterprise-acceptance.md`; block on insufficient capacity or absent isolated
  canary without evicting unrelated apps or buying hardware.
- [ ] T023 [US3] Add platform/enforcement checks to `scripts/ci/static-checks.sh` and relevant Conftest policies; run HCL formatting/generation/validation, strict Talos config validation, source renders and scoped authenticated plans from `quickstart.md`; publish any changed artifact digests and verify direct recovery plus fresh off-node etcd backup before live maintenance.
- [ ] T024 [US3] Execute `.github/workflows/platform-maintenance.yml` for Talos `1.11.3 -> 1.11.6 -> 1.12.12 -> 1.13.11 -> 1.14.4`, retaining Kubernetes 1.34; for every hop upgrade workers serially then the sole control plane, checking API/etcd/DNS/storage/access/apps between nodes and recording per-node receipts referenced by `docs/evidence/openclaw-enterprise-acceptance.md`.
- [ ] T025 [US3] Deliver Istio `1.27.3 -> 1.28.10 -> 1.29.9 -> 1.30.6` as separate reviewed changes in `IaC/istio/stack.hcl` and `clusters/homelab/apps/istio/`; include the first-hop patch resolved by T001, order base/CRDs, istiod, CNI, ztunnel and gateways, and require live mesh/access/webhook health at each minor before proceeding.
- [ ] T026 [US3] Execute the declared Kubernetes `1.34.11 -> 1.35.9` stage through `.github/workflows/platform-maintenance.yml`; verify all node/control-plane versions, system components and recovery access, then record source-bound results in `docs/evidence/openclaw-enterprise-acceptance.md`; no automatic downgrade or bypass on failure.
- [ ] T027 [US3] Activate only the admitted tainted canary through `IaC/platform-network-policy/stack.hcl`; run `scripts/network-policy-qualification.py` on actual Talos for allowed/denied traffic, first application traffic, enforcer graceful/crash restart, API loss, policy/conntrack changes, IP reuse, rescheduling and cold node reboot, including owned-rule
  cleanup/recovery and IPv6-absence checks.
- [ ] T028 [US3] Expand enforcement one reviewed node at a time through `IaC/platform-network-policy/stack.hcl`, rechecking capacity, policy hashes and the T027 matrix for each node; prove DNS, API, TLS DB, HBONE/probes, webhooks, NFS, ESO/Argo, Octelium and image pulls, and record separate host-network/privileged/VPN/Multus evidence in `docs/evidence/openclaw-enterprise-acceptance.md`.
- [X] T029 [US3] Add `clusters/homelab/platform/envoy-gateway/values.yaml`, `crds-values.yaml` and `gatewayclass.yaml` for Gateway 1.9.2, Gateway API 1.6.1 experimental and Envoy CRDs 1.9.2; enable both CRD groups only in the CRD chart, disable controller-chart CRDs, retain safe-upgrade resources and pin mirrored images per `contracts/enterprise.md`.
- [X] T030 [US3] Register `IaC/platform-envoy-gateway/stack.hcl` in `IaC/terragrunt.stack.hcl` using the existing shared Application module; declare the sole shared CRD owner, server-side apply, CRDs-before-controller readiness and specific project permissions; render/assert no duplicate owner, public listener or retirement prune of shared CRDs.
- [ ] T031 [US3] Apply the Envoy registration through `.github/workflows/terragrunt-apply.yml` and Argo; verify required Gateway/Envoy/cert-manager APIs, Istio's retained TCPRoute/UDPRoute v1alpha2 and ReferenceGrant v1beta1 watches, and a private test route after proxy cold restart; require expected image digests, Accepted/Programmed state and no xDS rejection in
  `docs/evidence/openclaw-enterprise-acceptance.md`.
- [ ] T032 [US3] Re-run the platform capacity and isolation checks from `specs/003-replace-openclaw-enterprise/quickstart.md`; accept US3 in `docs/evidence/openclaw-enterprise-acceptance.md` only when every node/stage and required path passes, preserving strict OCE broad-egress findings without claiming FQDN filtering or global egress hardening.

**Checkpoint**: Platform prerequisites pass with live receipts. Freeze the tested
configuration hashes; any relevant change invalidates the affected qualification.
Actual OCE-generated policy and native routing are checked again in US1.

## Phase 5: US1 — Use the New Enterprise Assistant (P1, MVP)

**Goal**: Deliver one fresh stock agent through private authenticated browser
access, with a distinct model credential and visible revision/model outcomes.

**Independent test**: Through the stable URL, sign in and open OCE's returned
native origin; complete three real conversations, verify active revision and
model failure reporting, and deny unauthorized console/agent/workspace/secret access.

### US1 tests and implementation

- [ ] T033 [P] [US1] Add `scripts/ci/openclaw-enterprise-test.py` fixtures for discovery, duplicate/foreign identities, Configuration POST lost responses, CAS conflicts, deployment ambiguity, worker restart, grant revocation/partial grants and repeated reconciliation; test explicit model/key gating, read-only verify and no legacy secret/state import.
- [ ] T034 [P] [US1] Add `scripts/ci/openclaw-enterprise-lifecycle-test.py` for first-install ownership, candidate preflight, exact hook ordering, writer fencing, stale/active init Jobs, cancellation and failed migration; assert Helm-only hooks, no selective-sync/self-heal bypass, correct shared CRDs and the single EnvoyProxy image-only override.
- [ ] T035 [P] [US1] Add `clusters/homelab/platform/storage/openclaw-enterprise.yaml` and wire its `kustomization.yaml`; use T022's verified node paths for distinct retained 10Gi PostgreSQL, 10Gi agent and 1Gi bootstrap allocations, explicit SQLite-compatible local classes and no NFS fallback or old-PVC adoption; let OCE own the eventual agent claim.
- [ ] T036 [US1] Add dedicated PostgreSQL 18.6, strict TLS and role bootstrap in `clusters/homelab/apps/openclaw-enterprise-foundation/postgres.yaml` and `database-bootstrap.sql`; isolate admin/migrator/app privileges, add `backup.sh` and `restore-drill.yaml` covering DB plus declared recovery material, and validate role/bootstrap/restore fixtures; live DB restore is T045 and
  complete agent-state restore is T049.
- [ ] T037 [US1] Add `clusters/homelab/apps/openclaw-enterprise-foundation/namespace.yaml` and adjacent `externalsecret.yaml`, `networkpolicy.yaml` and `kustomization.yaml`; prepare `openclaw-system`/`openclaw-agents` outside ambient mesh, immutable candidate inputs, bootstrap retention and required scoped permissions; verify exact T005 secret projection/refresh and file-backed
  inputs wherever upstream supports them.
- [ ] T038 [P] [US1] Add the authenticated private console and post-authentication legacy-URL redirect to `docs/examples/octelium/homelab-services.yaml`; route only opaque native origins under `agents.oce.stinkyboi.com` through private Tailscale/Traefik to OCE API, which enforces exact-Agent permission.
  Update owned Traefik DNS/certificate/proxy declarations and tests; use `console.oce.stinkyboi.com`, cookie scope `oce.stinkyboi.com`, Host/WebSocket preservation and trusted-proxy boundaries.
- [ ] T039 [US1] Add `clusters/homelab/apps/openclaw-enterprise/values.yaml` for pinned stock source `33bb74590a749f37934da4502fca6035cd234a55`, matched Harbor images and a fresh inactive Embedded agent; add `envoyproxy.yaml` as the final-source override for `oce-private-gateway`, preserving every rendered field except the explicit mirrored `distroless-v1.39.3` image; assert
  exactly one expected repeated-resource warning.
- [ ] T040 [US1] Add `clusters/homelab/apps/openclaw-enterprise/hooks.yaml`, adjacent `quiesce.py` and `validation/lifecycle.yaml` fixtures; implement weights -40/-30/-20/-18/-15/-10 as contracted, mount checksum-pinned upstream `check-installation.mjs`, fence exact API/worker writers with narrow scale RBAC, and block migration/resume on uncertain ownership, active prior Jobs or failed gates.
- [ ] T041 [US1] Implement `scripts/openclaw-enterprise.py` check/reconcile/verify against the supported API/CLI contract; use a protected serialized journal, `existingNamespace`, exact grants and generation checks, explicit runtime credentials, supported stop and returned native origin; recover unknown create/deploy outcomes before retry and never redeploy unchanged input or
  send inference from verify.
- [ ] T042 [US1] Add `IaC/openclaw-enterprise-foundation/stack.hcl`, `IaC/openclaw-enterprise/stack.hcl` and root units; add `clusters/homelab/argocd/self-management/openclaw-enterprise-appproject.yaml` with exact repositories/namespaces/resource kinds, pinned upstream Git chart plus local `main` sources, bounded foundation readiness, `selfHeal: false`, full-sync
  serialization and no Argo ownership of OCE-managed tenant objects.
- [ ] T043 [US1] Extend `.github/workflows/openclaw-enterprise-operations.yml` with fixed full-sync/reconcile/stop/verification/restore/acceptance stages using `scripts/config/openclaw-enterprise.json`, exact-main guards and private journal locking; separate inference probes from read-only verification, wire new checks into `scripts/ci/static-checks.sh`, and update exact
  workflow-policy permissions/hashes in `policy/workflows.rego` and tests.
- [ ] T044 [US1] Run all local, render, secret-boundary and authenticated scoped plan gates in `specs/003-replace-openclaw-enterprise/quickstart.md`; inspect effective multi-source output, RBAC, provider/credential/storage boundaries and candidate immutability, then publish/verify any remaining transitive images before enabling the foundation/Application registrations.
- [ ] T045 [US1] Deploy foundation and the declared isolated lifecycle-validation candidate through protected registration/Argo; exercise `clusters/homelab/apps/openclaw-enterprise/validation/lifecycle.yaml` on the installed Argo version for empty install, failed preflight/quiescence/migration, cancellation/restart and safe retry/resume; verify DB role/TLS/restore and stop on
  any mismatch before production installation.
- [ ] T046 [US1] Switch to the validated production installation phase in `scripts/config/openclaw-enterprise.json` and perform one full gated sync through `.github/workflows/openclaw-enterprise-operations.yml`; verify foundation readiness, successful terminal initialization, private console/auth, source/image identity and the actual OCE EnvoyProxy digest/routes after cold
  restart; keep agent activation disabled.
- [ ] T047 [US1] Configure the owner's explicit supported model ID and distinct provider key through `scripts/config/openclaw-enterprise.json` and the protected T005 secret contract, then enable activation only after all prior receipts pass; reconcile twice via `.github/workflows/openclaw-enterprise-operations.yml`, record the real provider probe/revision, and require unchanged
  IDs/grants with no duplicate deployment.
- [ ] T048 [US1] Execute browser and actual generated-policy acceptance from `specs/003-replace-openclaw-enterprise/quickstart.md`: three authenticated conversations, visible model failure/revision, trusted native-origin TLS/WebSocket, denied unauthorized/private/cross-agent access and no inherited state/jobs/credentials; preserve the strict broad-egress finding and record
  sanitized results in `docs/evidence/openclaw-enterprise-acceptance.md`.
- [ ] T049 [US1] Capture and restore the complete new DB/tenant metadata/secrets/agent volume/bootstrap/auth/gateway recovery set into isolation using `clusters/homelab/apps/openclaw-enterprise-foundation/restore-drill.yaml`; verify it independently of legacy archives and accept US1 in `docs/evidence/openclaw-enterprise-acceptance.md` only after this restore and T048 pass.

**Checkpoint**: MVP usable and recoverable. Console-only or credential-missing
states remain incomplete. Old archives and stopped resources remain retained.

## Phase 6: US4 — Operate and Recover the Replacement (P2)

**Goal**: Prove repeatable operation, revision/upgrade safety, scheduled backups,
recovery ordering and selective retirement after observation.

**Independent test**: Repeat setup without duplicate identities/grants; deploy one
revision and restart it through the declared lifecycle; rehearse failed upgrades
and complete recovery, then observe 24 hours before obsolete resources are removed.

### US4 tests and implementation

- [ ] T050 [P] [US4] Add `scripts/ci/openclaw-enterprise-recovery-test.py` for agent-stop-before-control-plane ordering, interrupted/unknown runtime termination, preservation of failed/new state, compatible legacy restore, owned-PVC retention and blocked enforcement removal; ensure failed recovery never resumes uncertain writers or deletes archives.
- [ ] T051 [P] [US4] Add `clusters/homelab/apps/openclaw-enterprise-foundation/backup-cronjob.yaml` using the verified T036 backup path; declare schedule, retention, private off-node destination, resource reservations and failure reporting, wire it into foundation `kustomization.yaml`, and validate a scheduled complete backup/restore without exposing contents.
- [ ] T052 [US4] Run repeated setup, one real configuration revision and a declared runtime restart through `scripts/openclaw-enterprise.py`; require stable installation/agent/grant IDs, proper generation conflict handling, persisted fresh state and observed active revision, recording SC-004 evidence in `docs/evidence/openclaw-enterprise-acceptance.md`.
- [ ] T053 [US4] Rehearse the full upgrade protocol on an isolated copy of the accepted new recovery set through `.github/workflows/openclaw-enterprise-operations.yml`, using the pinned release and migration-failure fixtures from `clusters/homelab/apps/openclaw-enterprise/validation/`; block external delivery/inference from the copy and prove writer fencing, failed-migration
  shutdown and exactly-once successful retry without overlapping init Jobs.
- [ ] T054 [US4] Complete the recovery stage in `scripts/openclaw-enterprise.py` and `.github/workflows/openclaw-enterprise-operations.yml`: disable conflicting autosync declaratively, stop agents through OCE while available, prove zero runtime Pods/writers, then quiesce API/worker and archive new state before compatible restoration; rehearse in isolation and refuse uncertain
  termination, unavailable-control-plane shortcuts or database merging.
- [ ] T055 [US4] Observe the accepted replacement for 24 hours using `.github/workflows/openclaw-enterprise-operations.yml` verification and the T051 schedule; record backup success, capacity/health, required shared-service/recovery checks and zero legacy writes/deliveries in `docs/evidence/openclaw-enterprise-acceptance.md`; any failure resets the acceptance window after repair.
- [ ] T056 [US4] After T055, prepare selective retirement in `IaC/openclaw/stack.hcl`, `IaC/terragrunt.stack.hcl`, old workload sources and `docs/examples/octelium/homelab-services.yaml`; retire only obsolete active routes/jobs/grants through existing retirement helpers, preserving the Enterprise redirect, legacy volumes/archives, shared LiteLLM/Discord-independent
  services and shared Gateway API resources.
- [ ] T057 [US4] Validate and deliver T056 through `.github/workflows/terragrunt-apply.yml`, Argo and the protected operations workflow; verify prune/finalizers do not delete retained data, only the new assistant is active, shared dependencies/recovery still work and no broad secret deletion occurred; close SC-005 in `docs/evidence/openclaw-enterprise-acceptance.md`.
- [ ] T058 [US4] Finish `clusters/homelab/apps/openclaw-enterprise/README.md`, `clusters/homelab/apps/openclaw-enterprise-foundation/README.md` and `docs/openclaw-enterprise-rollout.md` with repeat setup, full-sync upgrade, backup/restore, stop/recovery and secret-rotation commands, expected outcomes and failure paths; document controller-managed agent environment projection
  and separate authorization for data disposal.

**Checkpoint**: All four stories accepted; completed retirement preserves both
recovery sets and shared platform dependencies.

## Phase 7: Polish and Cross-Cutting Validation

- [ ] T059 Update `docs/runtime-isolation.md`, `docs/image-egress-hardening.md`, `docs/secrets-aws-ssm.md`, `docs/argocd-app-onboarding.md` and `docs/talos-control-plane-maintenance.md`; refresh affected `openwiki/` pages through the repository's approved OpenWiki maintenance path using these source docs, recording ownership/version/policy changes without hand-editing generated pages.
- [ ] T060 Run the complete relevant validation set in `specs/003-replace-openclaw-enterprise/quickstart.md`, including HCL/stack generation, static/Conftest, Helm/Kustomize, lifecycle/recovery tests and secret scans; verify the documented fresh-cluster root `terragrunt apply` dependency path and distinct protected maintenance path, and resolve every remaining failure or
  explicitly unavailable live gate.
- [ ] T061 Reconcile all FR-001–FR-012 and SC-001–SC-005 receipts in `docs/evidence/openclaw-enterprise-acceptance.md` against actual deployed source/digests; update `specs/003-replace-openclaw-enterprise/tasks.md` checkboxes only from evidence and update `plan.md`/`quickstart.md` for implemented paths, leaving unresolved gates unchecked.

## Dependencies and Execution Order

```text
T001 -> (T002 || T003) -> (T004 || T005 || T006)
  -> US2 T007–T014: legacy shutdown and verified recovery
  -> US3 T015–T032: capacity -> Talos -> Istio -> Kubernetes
                    -> policy canary -> all nodes -> shared routing
  -> US1 T033–T049: storage/DB/secrets -> hooks -> isolated lifecycle tests
                    -> private console -> model activation -> acceptance/restore
  -> US4 T050–T058: operational proofs -> 24h observation -> retirement
  -> T059–T061: documentation and final evidence
```

- Setup and foundation block every story. Equal-priority P1 story order is
  dependency-driven; US4 stays P2. US1 cannot be activated independently of US2/US3.
- Tests belong to the story they prove. Basic journal/retry, writer fencing and
  full-restore support are implemented in US1 because first use needs them;
  US4 tests ongoing operation and extends scheduling/recovery without a cycle.
- Within a story, execution follows task order except the explicit parallel
  batches below. In US2, T010 waits for T008/T009; T012 waits for T011.
- US3's T022 requires the verified legacy archive, not merely a stopped Pod.
  T023 blocks all maintenance. T027 requires all version stages and prepared
  canary admission; T028 requires full canary recovery/lifecycle proof.
- T045 requires T044 and all US3 receipts. T047 requires the complete foundation,
  lifecycle and actual routing checks plus explicit model/key input. T049 blocks
  MVP completion. T056 requires the full successful 24-hour T055 window.
- Rerendering or changing policy, images, placement, credentials, hooks or schema
  invalidates the associated prior receipt. Re-run the affected gate before use.
- Split live changes into reviewed stages; do not merge all final target values
  at once and let auto-sync skip intermediate versions, tests or shutdown gates.

## Parallel Execution Examples

These are opportunities within this checklist, not instructions to start agents.
No concurrent edits to shared configuration, workflow policy or root unit files.

| Story/phase | Ready after | Safe concurrent work |
| --- | --- | --- |
| Setup | T001 | T002 platform input and T003 Enterprise input |
| Foundation | T002–T003 | T004 artifact catalog, T005 secret contracts, T006 release/receipt docs |
| US2 | Foundation | T007 archive failure fixtures and T009 stopped-state/retention manifests; T008 follows T007 |
| US3 | US2 | T015 maintenance fixtures, T018 policy audit/corrections, T019 qualification runner/fixtures; serialize any common policy-owner edits |
| US1 | US3 | T033 API fixtures, T034 lifecycle fixtures, T035 storage and T038 private access; T036/T037 follow storage and share no parallel edit window |
| US4 | US1 | T050 recovery failure fixtures and T051 scheduled-backup manifests; both complete before dependent operational proofs |

## Requirement Coverage

| Requirement/outcome | Main implementation and acceptance tasks |
| --- | --- |
| FR-001, SC-001: fresh agent and real response | T039, T041–T048 |
| FR-002: private stable/native access | T038, T046, T048 |
| FR-003, SC-002: stopped and recoverable legacy | T007–T014 |
| FR-004: no old state/integration/credential import | T003, T008–T014, T033, T039, T048 |
| FR-005: explicit distinct provider input | T003, T005, T033, T047–T048 |
| FR-006: supported ordered platform | T001–T002, T015–T017, T023–T026 |
| FR-007, SC-003: actual isolation and lifecycle proof | T018–T021, T027–T032, T048 |
| FR-008: capacity/storage/routes/secrets/recovery | T022, T029–T037, T044–T049 |
| FR-009, SC-004: reproducible operations and retries | T010, T017, T033–T034, T040–T047, T052–T054 |
| FR-010: secret and permission boundaries | T005, T010, T017, T036–T043, T048, T060 |
| FR-011: writer fencing and complete recovery | T034, T036, T040, T045, T049–T054 |
| FR-012, SC-005: observation and selective retirement | T055–T061 |

## Implementation Strategy

1. Complete shared inputs/artifacts, then deliver US2 as a recoverable shutdown
   increment. It can free only legacy OpenClaw's own resources.
2. Deliver US3 as separate version and enforcement increments. Capacity or canary
   failure stops progression; restore legacy service through its declared path
   if the replacement cannot proceed.
3. MVP is **US1 plus its mandatory US2/US3 prerequisites**, T001–T049. Native UI,
   model inference, denied access and full restore must pass; console readiness
   alone is not an MVP. Keep old data and obsolete inactive resources retained.
4. Finish US4's operational proof and successful 24-hour observation before final
   retirement. Complete documentation and final checks; never shorten gates to
   finish a coding session or mark unavailable live evidence passed.

## Generation Validation

61 tasks: setup 3, foundation 3, US2 8, US3 18, US1 17, US4 9, polish 3.
All task IDs are sequential; every task has a path and story-phase labels.
Parallel batches above are the only permitted exceptions to sequential order.
No `.specify/extensions.yml` was present when tasks were generated; no before/after
task hooks applied. No implementation or live rollout was performed.
