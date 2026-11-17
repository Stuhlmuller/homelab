# Tasks: AdGuard Tailnet DNS

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contract](contracts/dns-and-admin.md),
[quickstart](quickstart.md). Custom review 24/24; built-in checklist 16/16.

Tests below are required by FR-013/017/019 and the reviewed plan, including
negative cases for consequential cutover guards. New behavioral fixtures precede
their implementation. Paths are repository-relative. All tasks initially pending;
a checkbox requires actual evidence. Never edit requirements-review markers from
implementation. Follow existing task ownership/protected PR skills for delivery.

## Phase 1: Setup

- [X] T001 Refresh main, confirm existing issue/branch ownership and inspect available Nix/runtime tools and current prerequisite health; record exact baseline and any unavailable validation in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/implementation.md` without replacing the isolated worktree.
- [X] T002 Resolve and verify the AdGuard v0.107.80 multi-platform index from research, add only its immutable upstream artifact to `scripts/config/harbor-images.json`, and run the existing inventory/coverage checks.

## Phase 2: Foundational delivery and contracts

These tasks establish the image, credential and registration boundaries.
Source preparation and fixtures may proceed while T003 publication runs; they do
not prove publication. T031 source review and a draft PR may proceed after T030
while publication is pending. T003 must pass before marking that PR ready or any
consuming-source merge at T032. No application registration/apply or DNS change
is authorized by source-only completion.

- [ ] T003 Deliver the T002 prerequisite through its protected PR and exact-main `.github/workflows/harbor-mirror.yml` dispatch; require digest/platform preservation and authenticated full pulls, recording PR/run/SHA evidence in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/image-publication.md` before any consuming manifest merges.
- [X] T004 Add generated `/homelab/adguard/admin-password` and exact ESO reader grant in `IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl`; enforce “32 characters, <=72 UTF-8 bytes; exact reader grant; never output values” and cover the declaration with existing SSM module tests.
- [X] T005 Add shared app registration at `IaC/homelab/us-west-2/apps/adguard/stack.hcl` and `terragrunt.stack.hcl`, using homelab-workloads/automation and the five reviewed dependencies; generate/inspect Application without broadening AppProject or namespace access.
- [X] T006 Add failing targeted AdGuard prerequisite/SSM-lane cases in `scripts/ci/terragrunt-apply-test.py`, including unavailable upstream health, wrong namespace/store scope, missing NFS and an unrelated app exclusion.
- [X] T007 Extend `scripts/ci/terragrunt-apply.sh` for exact AdGuard registration and SSM prerequisites using existing bounded app paths; pass T006 without introducing DNS administrator scopes or bypassing current-main guards.

## Phase 3: US1 — Direct filtering service (P1)

**Goal**: A correctly configured, signed, directly queryable filtering resolver.
**Independent evidence**: Runtime fixture first; live direct UDP/TCP acceptance
at T036. This story alone does not switch global DNS.

- [X] T008 [P] [US1] Add manifest/config boundary cases in `scripts/ci/adguard-test.py` for one replica, DNS-only tailnet Service, non-root capabilities, no public/setup exposure, one valid admin hash, privacy flags and retained storage; show relevant failures before implementation.
- [X] T009 [P] [US1] Add `scripts/ci/adguard-runtime-test.py` using the pinned image and synthetic credentials/upstreams/filter list; cover both transports, A/AAAA null-IP blocking, permitted/NXDOMAIN/private answers, private failure isolation, failed-refresh retention, empty-cache rejection and exact security-context startup.
- [X] T010 [US1] Implement `clusters/homelab/apps/adguard/init-config.py` to validate schema 34, “exactly one nonempty bcrypt user; no plaintext password,” resolve the fixed cluster-local private resolver, and atomically write mode-0600 JSON-compatible YAML; fail closed on malformed input, ambiguous address or failed resolution.
- [X] T011 [US1] Create `clusters/homelab/apps/adguard/externalsecret.yaml` with OnChange/revision-driven bcrypt rendering, guarded password length, default ad filter/daily refresh, explicit general/private upstreams, empty fallback and disabled querylog/statistics/discovery; mount files without runtime credential environment variables.
- [X] T012 [US1] Create `clusters/homelab/apps/adguard/deployment.yaml`, `pvc.yaml` and `kustomization.yaml` with Recreate/non-root/NET_BIND_SERVICE-only profile, no token mount, ambient opt-out, bounded probes/resources, writable config and 1Gi retained nfs-default work cache; enforce “One writer; retained claim; failed refresh preserves usable cache.”
- [X] T013 [US1] Create `clusters/homelab/apps/adguard/service.yaml` and `networkpolicy.yaml` for DNS-only operator LoadBalancer and separate ClusterIP admin service; declare intended peers and document actual external enforcement limitations.
- [X] T014 [US1] Add the exact automation/adguard-dns/homelab-adguard signing target and `--adguard-only` mode to `scripts/tailscale-ingress-sign.py` with corresponding existing signer fixtures; preserve trusted signer/current-main/identity guards and reject unrelated targets.
- [X] T015 [US1] Implement read-only `scripts/adguard-check.py` plus `scripts/ci/adguard-check-test.py` to bind observed Service/peer identity and config/deployed revisions, verify enabled nonempty filter membership, and check required direct DNS samples with three-second single-attempt deadlines; never invent endpoint IP or treat fixture peers as live proof.

## Phase 4: US2 — Tailnet DNS adoption support (P1)

**Goal**: Reviewed helper and acceptance interfaces for the later global switch.
**Independent evidence**: Fixture validation of cutover and client-mode contracts;
actual tailnet/system-resolver outcome is deliberately delayed to T037–T039 until
US3/US4 and live direct acceptance are complete.

- [X] T016 [US2] Add `scripts/ci/adguard-dns-cutover-test.py` cases for exact DNS-only plans, unrelated changes/replacement/deletion/unknown values, stale/future evidence, changed source/config/Service/peer/plan bytes/live DNS and uncertain-write recovery; enforce “300-second full-check and 60-second completion-to-apply bounds.”
- [X] T017 [US2] Implement preview-by-default cutover mode in `scripts/adguard-dns-cutover.py`, rerunning all required checks in the same invocation, binding full before/after policies and plan SHA-256, re-reading guarded state immediately before exact saved-plan apply, preserving native state locks and verifying actual policy after apply.
- [X] T018 [US2] Extend `scripts/ci/adguard-check-test.py` with real-system-resolver adapter fixtures, cache treatment and OS/client-version/exit-node metadata; reject direct-query receipts presented as client acceptance and missing/unsupported exit-node evidence.
- [X] T019 [US2] Add client acceptance mode to `scripts/adguard-check.py` and document its actual CLI in `specs/20261115-185603-adguard-tailnet-dns/quickstart.md`; support required fresh blocked/permitted samples, private-name inventory and MagicDNS, with conditional existing-exit-node coverage and no synthetic pass for unavailable access.
- [X] T020 [US2] Add DNS cutover expectation fixtures under `IaC/terragrunt-catalog/modules/tailscale-access/` for one observed AdGuard global nameserver, override enabled and exit-node use while preserving full split DNS/MagicDNS/search paths; do not put a placeholder address into active `main.tf` before T037.

## Phase 5: US3 — Private administration (P2)

**Goal**: Authenticated private HTTPS UI without public routing.
**Independent evidence**: Route/render/auth fixtures followed by live UI checks at
T036; no global DNS switch needed to test this story.

- [X] T021 [US3] Extend `scripts/ci/traefik-routes-test.py` and `scripts/ci/tailnet-dns-test.py` for the approved AdGuard name, fixed private backend, TLS coverage and absence from Funnel/setup routes.
- [X] T022 [US3] Add private AdGuard router/backend in `clusters/homelab/apps/traefik/routes.yaml`, its approved-name annotation in `values.yaml`, and matching private resolver allowlist in `clusters/homelab/platform/tailnet-dns/values.yaml`; keep the route/name/view contract synchronized.
- [X] T023 [US3] Extend `scripts/ci/adguard-runtime-test.py` with initialized authenticated administration, rejected unauthenticated protected reads/writes, no first-run setup, and no retained query/statistics history; use synthetic credentials only.
- [X] T024 [US3] Extend `scripts/adguard-check.py` and `clusters/homelab/apps/adguard/README.md` for private TLS/admin acceptance using file-backed credentials without printing secrets; document inspection versus repository-owned persistent changes.

## Phase 6: US4 — Recovery and rollback (P2)

**Goal**: Recover effective configuration and restore prior DNS even when AdGuard
is unavailable. **Independent evidence**: Isolated restore and rollback eligibility
fixtures; no destructive live outage is required.

- [X] T025 [US4] Add rollback-mode cases to `scripts/ci/adguard-dns-cutover-test.py`: AdGuard DNS/UI/peer unavailable must not block an otherwise exact restoration, unrelated drift/missing prior record must fail, already-restored must be no-op, and uncertain result must be inspected before retry.
- [X] T026 [US4] Implement `--mode rollback` in `scripts/adguard-dns-cutover.py` with separate gates; enforce “Prior policy must agree with reviewed source; fresh live policy must match activated or already-restored policy; rollback eligibility excludes AdGuard health,” preserving timing/state locks/storage/secrets and diagnostic-only private resolver availability.
- [X] T027 [US4] Add a repository-owned isolated recovery mode to `scripts/adguard-check.py` (or an explicitly documented sibling helper if isolation requires it), with synthetic replacement/restore cases in `scripts/ci/adguard-runtime-test.py`; reconstruct Git plus protected credential source versions and prove effective configuration/authentication/filtering without modifying production.
- [X] T028 [US4] Document state reconstruction, protected credential custody, retained cache, explicit rollback CLI and offline-AdGuard recovery in `clusters/homelab/apps/adguard/README.md`, `docs/storage-nfs.md` and `docs/application-recovery.md`; distinguish recovered behavior from backup existence.

## Phase 7: Integration, delivery and functional acceptance

These tasks complete all stories in dependency order. They remain pending when
source tests pass but live prerequisites or required operator access are absent.

- [X] T029 Update `openwiki/workloads/inventory.md`, `openwiki/runbooks/tailnet-ingress.md`, `openwiki/architecture/storage-and-state.md`, `docs/secrets-aws-ssm.md` and `openwiki/operations/validation-gates.md` with actual app, credential, storage, validation and client limitations; preserve generated wiki artifacts.
- [X] T030 Run all new fixture/render/runtime checks and affected existing route/DNS/signing/SSM/targeted-apply/OpenWiki checks plus relevant HCL formatting/plans from `docs/validation-runbook.md`; record exact results and material limits in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/validation.md`.
- [X] T031 Review the complete app diff for FR coverage, secret safety and executable cutover/rollback guards; prepare a bounded draft PR and delivery evidence with image publication explicitly pending until T003 passes in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/delivery.md` without claiming unfinished runtime acceptance.
- [ ] T032 Deliver app/route/secret/helper source through protected PR merge under `.agents/skills/homelab-protected-prs/SKILL.md`, preserving ownership and exact-commit check evidence; record final main SHA in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/delivery.md`.
- [ ] T033 Refresh live prerequisite health and diagnose the observed Traefik Application Progressing discrepancy; if a source correction is required, deliver it through its owning code path and tests before AdGuard apply; record evidence and dependency disposition in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/delivery.md` without bypassing preflight.
- [ ] T034 Dispatch the tested exact-main AdGuard path in `.github/workflows/terragrunt-apply.yml`, inspect SSM/ESO/PVC/workload/route results without printing credentials, and verify deployed revision with `scripts/verify-gitops.py`; record actual rollout evidence in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/runtime.md`.
- [ ] T035 Run the reviewed fixed signing path from `scripts/tailscale-ingress-sign.py` on the existing trusted signer, then record actual online signed AdGuard peer and Service address in private receipts referenced by `specs/20261115-185603-adguard-tailnet-dns/checkpoints/runtime.md`; if operator access is missing, prepare this exact handoff rather than expanding trust.
- [ ] T036 Run live direct DNS/admin checks, routine replacement through the declared delivery path and isolated recovery with `scripts/adguard-check.py`; prove US1/US3/US4 acceptance and recheck actual revision, recording only sanitized results in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/runtime.md`.
- [ ] T037 After T036, replace the global DNS entries with the observed AdGuard IPv4 and override/exit-node flags in `IaC/terragrunt-catalog/modules/tailscale-access/main.tf`; preserve all unrelated DNS fields, run T020 tests and deliver the narrow cutover PR through protected merge with prior-policy capture referenced in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/cutover.md`.
- [ ] T038 Generate and inspect the existing encrypted administrator saved plan, then preview/execute `scripts/adguard-dns-cutover.py --mode cutover` from reviewed current main with fresh bound checks; inspect effective tailnet policy and retain private exact-plan/prior-policy receipts, recording sanitized outcome in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/cutover.md`.
- [ ] T039 Perform normal-client blocked/permitted/private/MagicDNS acceptance using `scripts/adguard-check.py`, recording OS/Tailscale version/cache handling/exit-node mode, additional existing-exit-node coverage or explicit unverified limitation, and final deployed revision in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/runtime.md`; use reviewed rollback if acceptance fails.
- [ ] T040 Run separate speckit-converge against the implemented task list and current spec/plan, resolve any appended work through additional implementation/convergence turns, then update issue #1842 and the existing tracker only after required functional evidence is complete; save final disposition in `specs/20261115-185603-adguard-tailnet-dns/checkpoints/converge.md`.

## Dependencies and implementation strategy

```text
T001 -> T002 -> T003
T002 -> T004/T005 -> T006 -> T007
T007 -> US1 (T008..T015)
US1 -> US2 source (T016..T020), US3 (T021..T024), US4 (T025..T028)
all source -> T029 -> T030
T030 -> T031 (source review / draft PR)
T003 + T031 -> T032 (ready / protected merge) -> T033..T036
T036 -> T037 -> T038 -> T039 -> separate convergence T040
```

US2 appears in priority order but its live activation is intentionally in the
final phase: US3 authenticated access and US4 rollback are prerequisites to
switching all client DNS. Within source work, T026 depends on T017 and T025;
T024 depends on T015/T022/T023. T027 depends on T010–012 and T023. Source changes
that share files are sequential, never concurrent writers.

The initial T001–T002 source increment is complete and T003 publication is
running. After the dependency correction is analyzed, prepare T004–T007 source
while monitoring that same publication run. Keep the app branch unmerged until
T003 passes. MVP is directly tested US1 plus its necessary private admin/recovery
support; no global cutover until the final dependency gates pass. Continue in
coherent story increments and retain exact task/test/checkpoint evidence.

Parallel opportunities: only T008/T009 are marked [P] because their independent
fixture files can be authored together after foundation. US2 client fixtures and
US3 route fixtures may be inspected concurrently, but editing shared checker or
runtime-fixture files stays sequential. US4 rollback and restore tasks also share
those files; no parallel writer example applies. This task list does not itself
request additional agents.

## Requirement coverage

| Requirements | Tasks |
| --- | --- |
| FR-001 | T002–007, T012, T030–034 |
| FR-002 | T008–009, T012–015, T035–036 |
| FR-003–004 | T009–011, T015, T036 |
| FR-005–006 | T008, T011, T013, T021–024, T036 |
| FR-007 | T004, T010–012, T023, T027–028, T036 |
| FR-008 | T014–017, T035–038 |
| FR-009–011 | T016–020, T022, T037–039 |
| FR-012 | T018–020, T037–039 |
| FR-013–014 | T015–019, T024, T036–039 |
| FR-015 | T016–017, T025–026, T028, T037–039 |
| FR-016 | T008–012, T023–024, T029–030 |
| FR-017 | T027–028, T036 |
| FR-018 | T024, T028–029, T039 |
| FR-019 | T029–040 |

SC-001 maps to T009/T015/T036; SC-002 to T018–019/T038–039;
SC-003 to T015/T021–022/T036/T039; SC-004 to T023–024/T036;
SC-005 to T027/T036; SC-006 to T030–040. All story outcomes need live receipts,
not merely source-file presence or unchecked fixture descriptions.

## Phase 8: Convergence

- [X] T041 Correct the direct acceptance Application binding in `scripts/adguard-check.py` and its fixtures to match the
  generated shared registration's single-element `spec.sources` and corresponding `status.sync.revisions`, while
  rejecting multiple sources, wrong project/destination/revisions and unintended legacy source combinations; validate
  against the actual generated Application projection per FR-001/013/019 and plan: shared registration (partial, HIGH).
  Complete before any live acceptance or cutover helper integration.

## Phase 9: Convergence

- [X] T042 Require the complete declared evidence-key set and nonempty values in `validate_binding` in `scripts/adguard-dns-cutover.py`; add negative cases for two equally empty or equally incomplete snapshots, preserving mismatch rejection, before wiring execution per FR-013/019 and plan: cutover evidence binding (partial, HIGH).

## Phase 10: Convergence

- [X] T043 Bind the saved plan's DNS resource to the pinned default Tailscale provider and exact existing administrator
  OAuth file expressions in `scripts/adguard-dns-cutover.py`; reject alternate provider aliases, credential sources,
  tailnets/API endpoints and unknown provider configuration, with negative fixtures, before any execution per
  FR-008/013/019 and plan: administrator-owned saved-plan path (partial, HIGH).

## Phase 11: Convergence

- [X] T044 Document practical domain-based blocking limits, same-domain ads/content tradeoffs, and browser/application encrypted-DNS bypass prerequisites in `clusters/homelab/apps/adguard/README.md`, linked from `openwiki/runbooks/tailnet-ingress.md`, per FR-018 (partial); preserve explicit macOS/exit-node verification limits and do not promise all ads are removed.

## Delivery review corrections

- [X] T045 Disable implicit NodePort allocation on the AdGuard DNS LoadBalancer in `clusters/homelab/apps/adguard/service.yaml` and cover it in `scripts/ci/adguard-test.py`; enforce the existing no-NodePort exposure contract (FR-002/FR-006).

- [X] T046 Reconcile AdGuard source with the merged Uptime Kuma ownership/catalog and shared route/apply policies; retain both applications, add exact AdGuard readiness coverage to the exhaustive catalog, and validate affected guards before draft delivery.

- [ ] T047 Deliver the `bind.dnsutils` devShell addition as a prerequisite before the final AdGuard publication receipt, preserving the byte-identical publication bundle across consumer delivery; run the exact-main scoped publisher after that toolchain source is merged.
