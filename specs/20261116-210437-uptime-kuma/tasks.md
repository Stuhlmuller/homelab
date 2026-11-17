# Tasks: Homelab uptime monitoring

**Input**: [spec](spec.md), [plan](plan.md), [research](research.md),
[data model](data-model.md), [native contract](contracts/native-api.md),
[quickstart](quickstart.md), [review](checklists/review.md).

**Prerequisites**: Requirements review 24/24 pass after R1 correction. Separate
read-only analyze must pass before implementation. All tasks start unchecked;
no implementation or delivery is implied by this document.

**Tests**: Explicitly required by spec FR-010/011 and SC-001–007. Use real pinned
Kuma for interface/storage contracts and negative fixtures for catalog and
freshness. Keep one writer/branch; checkpoints retain evidence and exact SHA.

## Phase 1: Setup

Goal: retain scope, current app inventory and ownership without changing live state.

- [x] T001 Refresh current source/live app union and lifecycle evidence in `specs/20261116-210437-uptime-kuma/inventory-evidence.md`, preserving source-only/staged/partially suspended entries and the issue #1847 ownership record.
- [x] T002 Confirm runtime test tools and existing helper-image pins in `specs/20261116-210437-uptime-kuma/research.md`; use temporary Nix packages when needed, and record actual pinned-image Node/SQLite/Python capabilities without installing runtime dependencies.

## Phase 2: Foundational image publication

Goal: publish required artifacts before any consumer reaches main. Independent
exit condition: exact catalog bundle and authenticated complete-pull receipt.

- [x] T003 Add the resolved Kuma index and only required helper pins to `scripts/config/harbor-images.json` and new `scripts/config/harbor-uptime-kuma-images.json`, preserving provenance and supported platforms.
- [x] T004 Add fixed `uptime-kuma` scope to `.github/workflows/harbor-mirror.yml` and `scripts/ci/harbor-publish.sh`, with invalid-scope, exact-inventory and unchanged-destination tests in `scripts/ci/harbor-publish-test.py` and affected existing publisher tests.
- [ ] T005 Validate and deliver only the image prerequisite through protected PR merge, dispatch exact-main mirror scope, and record successful publication/full-pull run and bundle hash in `specs/20261116-210437-uptime-kuma/delivery.md`; do not merge consuming references before this receipt.

## Phase 3: US1 — See homelab availability (P1, MVP)

Goal: private authenticated Kuma with automatically configured, complete meaningful
coverage. Independent test: pinned-image login/catalog reconciliation, then live
owner access and three observations for every active monitor after delivery.

- [x] T006 [US1] Define explicit app lifecycle and monitor records in `clusters/homelab/apps/uptime-kuma/monitors.json`, reconciling T001 evidence; select each endpoint or exact shared component health signal from current source and record meaning, limits and actual source observation period.
- [x] T007 [US1] Add catalog validator and negative fixtures in `scripts/ci/uptime-kuma-check.py` and `scripts/ci/uptime-kuma-check-test.py` for missing app coverage, unknown/duplicate IDs, invalid ownership links, absent cadence evidence, unsafe targets and unjustified lifecycle exclusions.
- [x] T008 [US1] Implement native bootstrap and reconciliation in `clusters/homelab/apps/uptime-kuma/reconcile.js`: loopback init server, first-owner setup only, full-record owned-field merge, bounded acknowledgements/events, uncertain-add reread, stable description keys, pause retirement, no-op settings retention and sanitized status.
- [x] T009 [US1] Add adapter tests in `scripts/ci/uptime-kuma-test.js` for setup denial on existing account, invalid credential failure, duplicate-key preflight, partial failure, uncertain successful add, preserving unowned/settings fields, and zero-change second reconciliation.
- [x] T010 [US1] Declare app-template values, service, config packaging, retained local storage and backup claim in `clusters/homelab/apps/uptime-kuma/{values.yaml,kustomization.yaml,local-storage.yaml,backup-pvc.yaml}`; set Recreate, startup/readiness, bounded resources, UID 1000, no API-token mount, loopback init and one reconciler writer.
- [x] T011 [US1] Add generated owner password to `IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl` and exact secret projection in `clusters/homelab/apps/uptime-kuma/externalsecret.yaml`; preserve existing reader ownership and mount credential only into bootstrap/reconciler consumers.
- [x] T012 [US1] Register pinned chart/overlay in `IaC/homelab/us-west-2/apps/uptime-kuma/{stack.hcl,terragrunt.stack.hcl}` with monitoring destination and existing homelab AppProject; extend targeted prerequisite/SSM apply lane in `scripts/ci/terragrunt-apply.sh` and negative/ordering coverage in `scripts/ci/terragrunt-apply-test.py`.
- [x] T013 [US1] Add private hostname route in `clusters/homelab/apps/traefik/routes.yaml`, hostname discovery in `clusters/homelab/apps/traefik/values.yaml`, and `scripts/config/tailscale-private-dns.json`; add exact Kuma/target principals and ports in owning AuthorizationPolicy/NetworkPolicy files, without public/Funnel routes or namespace-wide access grants.
- [x] T014 [US1] Build/run disposable pinned-image integration harness `scripts/ci/uptime-kuma-integration.sh` proving bundled dependencies, rootless CLI startup, loopback bootstrap, graceful stop before main, existing-account preservation, real Socket.IO add/edit/pause/no-op and settings retention; retain sanitized results in `specs/20261116-210437-uptime-kuma/validation.md`.

## Phase 4: US2 — Trust failure and recovery (P1)

Goal: truthful app health and bounded fault transitions without disrupting any app.
Independent test: health predicates reject redirects/stale/missing signals, and a
disposable fixture transitions healthy→down→healthy within 180 seconds each.

- [x] T015 [US2] Extend `scripts/ci/uptime-kuma-test.js` and `scripts/ci/uptime-kuma-check-test.py` with JSONata/health cases for missing/multiple results, false workload health, zero desired replicas, stale metrics, 401/302, and a 15-second scrape where age 31 seconds fails and age 30 seconds is eligible.
- [x] T016 [US2] Implement read-only verify and bounded acceptance fixture modes in `clusters/homelab/apps/uptime-kuma/reconcile.js`; require three real observations, test localhost-only disposable target failure/recovery, pause only the test-owned monitor afterward and preserve existing app/monitor state.
- [x] T017 [US2] Extend `scripts/ci/uptime-kuma-integration.sh` to exercise actual pinned JSON-query monitors, source-specific freshness predicates, unauthorized administrative access denial and the complete controlled acceptance fixture; record real outcomes in `specs/20261116-210437-uptime-kuma/validation.md`.

## Phase 5: US3 — Reproducible durable monitoring (P2)

Goal: retained history and a usable, isolated recovery path. Independent test:
backup a live WAL database, restore it privately, log in and read prior history;
repeat configuration/replacement without duplicate IDs or lost observations.

- [x] T018 [US3] Complete online SQLite snapshot, integrity verification, permitted ancillary files, checked atomic archive publication and safe extraction in `clusters/homelab/apps/uptime-kuma/backup.py`; preserve passing read-only WAL/retention cases, source database and immutable archive. Restore verification is incomplete until T029 fences only its disposable clone before native startup.
- [x] T019 [US3] Preserve backup/restore regressions in `scripts/ci/uptime-kuma-backup-test.py` and the actual pinned `scripts/ci/uptime-kuma-backup-integration.sh`: concurrent WAL
  writes through read-only source, corrupt/incomplete archives, traversal, failed publication, stable account/IDs/history. Require T030 network-enabled positive/negative
  execution-fence proof; network-none storage tests alone cannot complete restore acceptance.
- [x] T020 [US3] Complete initial backup, nightly retained backup and restore verification Jobs in
  `clusters/homelab/apps/uptime-kuma/{backup-job.yaml,backup-cronjob.yaml,restore-verification-job.yaml}` with bounded time, concurrency, node affinity and no production data mount
  on restore. Require T031 dedicated restore identity and T029 pre-start fence; declared deny-all NetworkPolicy is additional desired defense, not claimed enforcement.
- [x] T021 [US3] Update `clusters/homelab/apps/uptime-kuma/README.md` with actual reconciliation/rollout, backup schedule/retention, node/NAS limits, clone execution fencing and
  reviewed writer-fenced production recovery. Explain current network-enforcement limits, fixed image/schema acceptance and source/backup immutability; commands must match
  implemented snapshot/verify interfaces and must not offer direct production restore.

## Phase 6: Cross-cutting checks, delivery and functional acceptance

Goal: deliver reviewed source and prove requested behavior. A passing local test,
PR merge or Argo health alone does not complete the task.

- [ ] T022 Wire Kuma checks into `scripts/ci/static-checks.sh` and applicable existing offline/static entrypoints; run catalog/adapter/backup tests, pinned-image integration, Kustomize/Helm rendering, policy/security checks and generated Terragrunt formatting/render/plans; retain exact commands/results/limits in `specs/20261116-210437-uptime-kuma/validation.md`.
- [x] T023 Update affected `docs/argocd-app-onboarding.md`, `docs/secrets-aws-ssm.md`, `openwiki/workloads/inventory.md`, `openwiki/architecture/storage-and-state.md`, `openwiki/architecture/secrets-and-identity.md` and `openwiki/operations/validation-gates.md`; describe current private routing without claiming stale Octelium-only requirements or touching generated wiki artifacts.
- [x] T024 Run separate source-convergence stage after implementation/checks; append any gaps to this `tasks.md` under convergence, implement them in separate turns and rerun analysis when an owning artifact changes; preserve the report in `specs/20261116-210437-uptime-kuma/checkpoint.md` without marking runtime tasks complete.
- [ ] T025 Deliver consuming source through protected PR review/checks/merge, refresh exact main, run declared targeted apply with valid prerequisites and saved-plan safeguards, and record PR/run/source revisions in `specs/20261116-210437-uptime-kuma/delivery.md`; never bypass a failed check or mutate live resources ad hoc.
- [ ] T026 Verify exact deployed revision with `scripts/verify-gitops.py`, private owner login/unauthorized denial, current live/source inventory coverage and three observations per enabled monitor; run repository-owned acceptance fixture and report actual target outages separately in `specs/20261116-210437-uptime-kuma/acceptance.md`.
- [ ] T027 Verify repeated reconciliation, declared GitOps replacement preserving IDs/history, first checked backup and clone-fenced native-login/history restore with unchanged archive, dedicated identity and verified pre-start postconditions; recheck deployed revision and record backup/scheduled-run evidence and limits in `specs/20261116-210437-uptime-kuma/acceptance.md`.
- [ ] T028 Run final separate convergence after actual acceptance, close gaps through append-only tasks and implementation loops, update issue #1847 and `specs/20261116-210437-uptime-kuma/checkpoint.md` with final revision, coverage, receipts and truthful remaining limitations; complete only when all requested outcomes pass.

## Dependencies and bounded implementation turns

T001–002 → T003–005 → US1 (T006–014) → US2 (T015–017) and US3 (T018–021)
→ T022–024 → T025 → T026–027 → T028. Within phases, earlier shared-file changes
precede later edits; T013 depends on T006 target selection. T020 depends on T018, T019, and T029–T031 recovery proof. T029 precedes
T030; T031 follows T029 and is checked with T030. T021 and T027 require all
three repair tasks; a local network-none success is insufficient. T025 requires T005 publication evidence and source
convergence; T028 requires functional evidence, not task checkbox counts.

Suggested bounded turns: image prerequisites; catalog/bootstrap/workload;
health acceptance; backup/restore; checks/docs; source convergence; protected
delivery; functional acceptance; final convergence. Each ends in a checkpoint.
Do not bundle analysis or convergence edits into implementation.

Parallel opportunities (optional read-only review or explicitly disjoint work):
US1 T007 validator review versus T011 secret-contract review after T006; US2
predicate-fixture review versus US3 backup test design after US1. No `[P]`
markers are assigned because the delivery owner retains one writer and most
changes share integration/test files. This is not a reason to create extra
feature branches or independent deployments.

## Requirement and outcome coverage

| Requirement/outcome | Tasks |
| --- | --- |
| FR-001, SC-002/007 private access/authentication | T008–014, T017, T026 |
| FR-002, SC-001 complete classified coverage | T001, T006–007, T026 |
| FR-003, SC-004 stable reconciliation | T008–009, T014, T027 |
| FR-004/005, SC-003 meaningful/fresh health | T006–007, T015–017, T026 |
| FR-006 history/retention | T008, T014, T018–020, T027 |
| FR-007, SC-005 durable recovery | T010, T018–021, T027, T029–031 |
| FR-008 declared delivery/secret safety | T003–005, T010–014, T022, T025 |
| FR-009 narrow network permissions | T006, T013, T017, T022, T029–031 |
| FR-010, SC-006 inventory validation | T007, T015, T022–023 |
| FR-011 exact-revision functional proof | T014, T017, T019, T026–028 |
| FR-012 scope and existing observability | T001, T006, T013, T023, T026 |

## Implementation strategy

US1 is the first demonstrable slice, but full delivery includes US2/US3 and
functional proof; an empty dashboard or untested recovery is not completion.
Only mark tasks checked after evidence exists. Pinned-image tests can use
local disposable storage; production writes must remain in declared GitOps or
explicit repository-owned acceptance commands. Review decisions remain in the
review artifacts; implementation must not edit checklist markers.

## P1 restore-isolation repair tasks (append-only IDs)

These tasks implement the separately repaired design. T001–T028 retain their
identities and prior evidence. T018–T021 remain reopened; no production
NetworkPolicy-enforcer activation or other infrastructure repair is authorized
by this correction. Read-only analyze must pass before implementation.

- [x] T029 [US3] Add fail-closed disposable-clone fencing to `clusters/homelab/apps/uptime-kuma/backup.py`: verify fixed image/schema/column types and unique setting keys, capture
  private original account/auth/monitor/notification/history evidence, then transactionally pause monitors, disable notification active/default flags and maintenance, remove
  notification bindings, and upsert JSON `checkUpdate=false`, `nscd=false`, `cloudflaredTunnelToken=""`. Independently reopen and assert every postcondition and unchanged permitted
  evidence before any native spawn. Preserve source/archive unchanged; native verifier uses needSetup=false, login/read-only APIs only, fixed loopback argv and allowlisted child
  environment without inherited Node/Kuma/proxy/tunnel overrides.
- [x] T030 [US3] Extend `scripts/ci/uptime-kuma-backup-test.py` and `scripts/ci/uptime-kuma-backup-integration.sh` with network-enabled reachable probe/notification sinks, an
  unfenced positive control that emits traffic, and a fenced clone observed for at least two configured monitor intervals with zero sink traffic and successful native
  auth/identity/history proof. Exercise pinned updater/tunnel guard semantics with observable positive/negative call/launch counters without public-service contact. Inject unknown
  schema, duplicate/missing/wrong settings, active/null flags, bindings, premature spawn and hostile inherited overrides; fail before native startup. Prove archive hash/evidence
  unchanged and each fence mutation detectable. Record sanitized evidence in `validation-backup.md`.
- [x] T031 [US3] Add a dedicated `uptime-kuma-restore` ServiceAccount in `clusters/homelab/apps/uptime-kuma/restore-serviceaccount.yaml`, wire it in `kustomization.yaml` and
  `restore-verification-job.yaml`, and verify no token, RBAC, production-backend grants or production PVC. Render/test exact readonly backups/config/credential plus ephemeral
  writable data and fixed verify command. Keep deny-all policy but document its present enforcement limit; validate the version-bound application execution fence as the primary
  guarantee.

Repair coverage: T029/T030 cover FR-007/010/011 and SC-005; T031 covers
FR-008/009 and SC-005. T021 documents limitations; T022 runs all repair tests;
T027 validates the actual deployed fenced verifier. Source convergence and
protected delivery remain mandatory after the repair.


## Phase 7: Convergence

Source convergence found two HIGH partial gaps. T032–T033 must complete before
T022 validation is finalized and T024 source convergence is repeated, then T025
delivery. Existing publication and deployed acceptance tasks remain unchanged.

- [x] T032 [US1] Make `scripts/ci/uptime-kuma-check.py` lifecycle-aware so explicit disabled owned monitor records can pass validation and remain available for the reconciler to
  pause without deleting IDs/history. Replace the fixture-only retired-app restriction with evidence-backed retirement validation; preserve rejection of unexplained exclusions and
  require enabled meaningful coverage for every active app. Keep ownership links consistent for retained disabled monitors and shared monitors with active owners. Add positive
  retirement/pause and negative uncovered-active/shared-owner regressions in `scripts/ci/uptime-kuma-check-test.py` and applicable native adapter tests, and document the executable
  catalog transition in `clusters/homelab/apps/uptime-kuma/README.md` and `docs/argocd-app-onboarding.md`. Trace: FR-003, FR-010, US2/AC3 (partial). Evidence: the current owner
  reciprocity and enabled-link checks reject every disabled record; retired app IDs are restricted to `live`.
- [x] T033 [US1] Extend the explicit reviewed private-only hostname suffix in `scripts/tailscale-private-dns-check.py` to accept `uptime-kuma.stinkyboi.com` from
  `scripts/config/tailscale-private-dns.json`, preserving the original 27-name migration inventory/hash/order and exactly 26 approved non-apex public-retirement names. Add
  regressions in `scripts/ci/tailscale-private-dns-test.py` proving the current inventory passes, unknown suffixes still fail, and Kuma is never included in public retirement;
  rerun affected DNS checks and T022 validation. Trace: FR-001, FR-008, FR-009, plan: private ingress/DNS integration (partial). Evidence: `inventory()` currently requires the
  entire suffix after position 27 to equal only `OCE_NAMES`, rejecting the committed Kuma hostname.
