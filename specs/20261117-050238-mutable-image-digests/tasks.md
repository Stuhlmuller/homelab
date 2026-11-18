# Tasks: Mutable References and Automatic Image Digests

**Input**: Design documents in `specs/20261117-050238-mutable-image-digests/`

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`,
`contracts/enrollment.md`; requirements and ownership reviews completed.

Tests below are required by the specification's observable acceptance outcomes
and provider ownership clarification. They are not optional implementation mirrors.
All paths are repository-relative. `[P]` indicates independent files only;
maintain one writer per branch and serialize shared-file edits.

## Phase 1: Setup

- [x] T001 Record installed binary/provider/chart availability, current branch/base and reviewed checklist state in `specs/20261117-050238-mutable-image-digests/checkpoint.md`; use existing tools and report unavailable capabilities without bypassing the sandbox.

## Phase 2: Foundation

- [x] T002 Define typed enrollment inputs in
  `IaC/terragrunt-catalog/modules/argocd-application-image-updater/variables.tf` and update
  `specs/20261117-050238-mutable-image-digests/contracts/enrollment.md` with exact names: unique aliases,
  tagged image names, Helm/Kustomize mappings, exact repository-relative owned `source_paths` and paused
  state; preserve the constraint "No digest, semver-update policy, wildcard application selection, Git
  credential or write-back branch input is accepted."
- [x] T003 Build focused native-HCL/schema fixture coverage in `scripts/ci/argocd-image-updater-test.py` for
  single-source and source-zero-plus-refs forms, duplicate/missing/digest selectors, ambiguous renderers,
  configured empty/seeded runtime-override rejection, source-path traversal/globs/out-of-source paths and
  partially owned same-package occurrences; establish failing cases before implementation.

**Checkpoint**: Exact inputs and negative acceptance fixtures exist. No live
enrollment or broad source ownership change is permitted.

## Phase 3: US1 — Follow the selected mutable reference (P1)

**Independent test**: Native CR output retains the declared tag, selects exactly
one Application and uses digest strategy with Argo CD write-back; a selector
change changes the CR while Git source branches remain declarative.

- [x] T004 [US1] Implement native per-Application ImageUpdater CR construction in `IaC/terragrunt-catalog/modules/argocd-application-image-updater/main.tf`, including exact selector, digest strategy, image mappings and native pause fields; validate against the pinned v1.3.0 CRD without introducing committed resolved workload digests.
- [x] T005 [P] [US1] Correct chart-supported controller settings in `clusters/homelab/apps/argocd-image-updater/values.yaml` and `clusters/homelab/apps/argocd-image-updater/paused-config.yaml`; remove Git API commit/write-back assumptions, reuse registry references, and render chart 1.3.1 to prove the settings are effective.
- [x] T006 [US1] Prepare the explicit controller registration in `IaC/homelab/us-west-2/apps/argocd-image-updater/terragrunt.stack.hcl` and update `IaC/homelab/us-west-2/apps/argocd-image-updater/stack.hcl`; permit an idle controller only after existing image/chart/access prerequisites pass, otherwise retain the staged state and record the concrete blocker without enrolling a guessed workload.
- [x] T007 [US1] Complete the CR/schema and controller-render cases in `scripts/ci/argocd-image-updater-test.py`, covering unchanged selector, changed selector and paused state; record source validation versus pending real tag A-to-B acceptance in `specs/20261117-050238-mutable-image-digests/checkpoint.md`.

## Phase 4: US2 — Preserve runtime hashes during registration (P1)

**Independent test**: With actual provider 3.2.1, controller B survives an unrelated
registration apply; a between-plan/apply change either survives or rejects the
apply. Nonimage settings and deliberate selectors continue changing.

- [x] T008 [US2] Add a bounded actual-provider regression in
  `scripts/ci/argocd-image-updater-provider-test.py`, using a controlled local API fixture or disposable test
  cluster, for A→B before refresh, B→C between plan/apply, unrelated metadata/value/source edits, absent
  alternate paths, recreation, single/multi-source forms and paused temporary default-module
  omission/source-edit/reenrollment preserving the live digest without a configured hash, and distinct
  permanent removal with explicit empty/replacement overrides, CR removal and no Application replacement;
  retain seeded-history cases only to explain rejected enrollment and migration semantics; do not substitute a
  copied Python provider model or mutate the live homelab.
- [x] T009 [US2] Implement `kubernetes_manifest.this` in
  `IaC/terragrunt-catalog/modules/argocd-application-image-updater/main.tf` with identical existing state
  identity/encryption/normalization, literal image-collection lifecycle ignores, matching computed fields and
  non-forced conflicts; reject every configured runtime override collection, including empty or image-only
  seeded lists, and unsupported source topology; live controller-only collections remain preserved through
  computed fields.
- [x] T010 [US2] Select the opt-in module only for explicit enrollment in
  `IaC/terragrunt-catalog/units/live/argocd-app/terragrunt.hcl`; default module and historical backend keys
  remain unchanged, and intentional selector changes stay outside ignored collections; seed default `sources`
  only if neither source form is supplied and test actual unit rendering for single-source and unchanged
  default inputs; preserve `image_update_handoff` in rendered inputs for policy while selecting the default
  module, reject active+handoff combinations, require handoff paused=true and absent configured runtime
  collections, and do not pass handoff-only metadata as an undeclared default-module variable.
- [x] T011 [US2] Run the provider regression and native-HCL checks in `scripts/ci/argocd-image-updater-provider-test.py`, `scripts/ci/argocd-image-updater-test.py` and `scripts/ci/argocd-computed-fields-test.py`; prove no Application replacement/default-app drift and preservation-or-conflict for stale plans, repairing any failure before allowing enrollment.

## Phase 5: US3 — Protected delivery and explicit recovery (P1)

**Independent test**: Workflow validation rejects protected-ref writes or bypasses;
legacy candidate validation still runs before normal protected PR delivery.
Documented transitions preserve one owner and distinguish readiness from updates.

- [x] T012 [P] [US3] Add negative workflow-policy fixtures to `scripts/ci/image-automation-promote-test.py` and `scripts/ci/argocd-image-updater-policy-test.py` rejecting direct protected-ref PATCH/push, force/bypass options and dual legacy/runtime enrollment while accepting the intended protected PR route.
- [x] T013 [US3] Replace direct-main promotion and direct-first fallback ordering in `.github/workflows/image-automation.yml` with validated normal PR delivery, preserving existing receipt/signature/scope checks and concurrency; update affected `scripts/ci/image-automation-promote-test.py` expectations without weakening candidate validation.
- [x] T014 [US3] Reconcile the legacy generated enrollment boundary in `scripts/ci/image-automation.py` and its existing tests so historical candidates remain unenrolled and cannot gain conflicting Git/runtime owners; preserve the existing Harbor catalog rather than redesign it.
- [x] T015 [P] [US3] Document exact enrollment, selector changes, pause, declarative removal handoff,
  recreation and recovery in `docs/argocd-image-updater.md` and
  `clusters/homelab/apps/argocd-image-updater/README.md`, including reserved override collections, unsupported
  inputs, provider race behavior and no manual live patching; show exact Renovate package/file rules,
  provenance prerequisites and the three-reconciliation pause/default-omission/reenrollment source-edit
  handoff with `image_update_handoff`, and separate permanent-removal override replacement; existing
  configured arrays require prior ordinary-owner migration, never copying a digest into code for the supported
  temporary handoff.

### Policy ownership completion (US3, appended IDs preserve earlier references)

- [x] T019 [US3] Add an on-demand enrollment reader/validator in `scripts/ci/argocd-image-updater-policy.py`
  using resolved explicit Terragrunt stack inputs as the sole source for mutually exclusive `image_update` or
  paused `image_update_handoff` mappings; validate owned `source_paths` belong to the Application, package
  occurrences are not partly owned, and each exact Docker package/file pair has an `enabled: false` rule in
  `renovate.json`; reject missing or wildcard-only proof, avoid changing unrelated rules, and define
  empty-enrollment behavior without a second registry.
- [x] T020 [US3] Integrate path/repository/tag-bound tag-only acceptance into `scripts/ci/harbor-images-check.py` using the validated enrollment reader, preserving source-file identity and existing provenance/publication requirements; leave all unenrolled and literal-digest checks unchanged and reject an unsupported channel rather than adding mirror behavior.
- [x] T021 [US3] Extend `scripts/ci/argocd-image-updater-policy-test.py` and relevant
  `scripts/ci/harbor-images-check-test.py` fixtures with exact-positive and negative cases for wrong
  path/tag/repository, unproven provenance, broad or missing Renovate rules, duplicate/partial ownership,
  empty enrollment, paused handoff retention, rejected active+handoff/unpaused handoffs, and restored
  ownership after permanent removal; run these before accepting T019/T020.

## Phase 6: Cross-cutting validation and delivery evidence

- [x] T016 Wire focused checks into `scripts/ci/offline-checks.sh` and `scripts/ci/offline-static-checks.sh` as appropriate and update `openwiki/architecture/gitops-flow.md` plus affected validation/source-map notes; explain the explicit opt-in exception to historical committed-digest ownership without weakening unenrolled image policy.
- [x] T017 Run the applicable formatting, native HCL/provider, CR/Helm/Kustomize, legacy image-automation, actionlint, wiki and Spec Kit checks listed in `specs/20261117-050238-mutable-image-digests/quickstart.md`; save exact results and unavailable-check reasons in `specs/20261117-050238-mutable-image-digests/checkpoint.md` and reconcile the quickstart with actual commands.
- [ ] T018 Deliver through protected PR checks/merge and declared registration paths, recording PR/head,
  actual deployment evidence or blockers in `specs/20261117-050238-mutable-image-digests/checkpoint.md`;
  verify idle-controller health if activated, keep actual workload A-to-B acceptance pending until an
  operator-selected mapping exists, and do not close issue #1846 as runtime-complete without that evidence.

## Dependencies and execution order

T001 → T002 → T003 establish shared inputs and fixtures. US1 T004–T007 then
creates controller/CR support. US2 T008–T011 depends on the typed inputs and
integrates the opt-in module; source delivery with enrollment must wait for its
provider acceptance, including omitted-collection history and temporary handoff.
T010 completed after the provider-evidence correction with seven shared-unit
renders and positive/negative default-module handoff cases. US3 T012–T015 can be implemented independently of provider
work after the input contract exists, but shared test-file edits are serialized.
T019 follows T002/T003 and runs before T020; write T021 failing fixtures before
T019/T020 implementation and re-run them after both. T019–T021 complete the
FR-009 ownership correction. These appended IDs are scheduled here by dependency,
not numerical order. T016 follows all story changes including T019–T021; T017 follows wiring/documentation; T018 follows
successful checks and separate convergence, including T023 registration guard correction. A blocked external acceptance is
recorded as pending, not a checked runtime test.

Parallel opportunities: T005 can proceed alongside T004 in different files;
T012 can proceed alongside T008/T009 only if the shared test file has no other
writer; T015 can proceed alongside T013/T014. These are optional schedules, not
instructions to create additional workers. Within US2, keep module edits and
unit integration sequential; independent source-backed review can run in parallel.

## Requirement coverage

| Requirements | Tasks |
| --- | --- |
| FR-001–003, FR-013 | T002–T007, T010 |
| FR-004–006, SC-007 | T003, T008–T011, T015, T019–T021, T023 |
| FR-007 | T012–T014, T018 |
| FR-008 | T005, T007–T008, T015, T017 |
| FR-009 | T003, T009, T012, T014, T016, T019–T021 |
| FR-010 | T004, T008, T015, T021, T023 |
| FR-011 | T001, T006–T008, T011, T017–T018 |
| FR-012 | T002, T005–T006, T013, T017–T021 |

## Implementation strategy

Use bounded completed turns: foundation plus US1 configuration, then US2
ownership/provider acceptance, then US3 and cross-cutting checks. A minimal
source increment may prepare an idle updater without enabling workloads, but
runtime enrollment is not an MVP until ownership preservation passes. Run
read-only analysis before implementation and append-only convergence after
implementation. Route design failures back to planning rather than loosening
requirements. Keep custom checklist markers reviewer-owned.


## Phase 7: Convergence

- [x] T022 Prevent later Renovate `enabled: true` rules using brace or extglob patterns from silently
  re-enabling an enrolled Docker package/file in `scripts/ci/argocd-image-updater-policy.py`; use compatible
  matching or conservatively treat unsupported pattern syntax as a possible match, and add package/file brace
  plus extglob regression cases in `scripts/ci/argocd-image-updater-policy-test.py`, preserving unrelated
  datasource/package/file acceptance per FR-009 and plan: exact single-owner Renovate exclusions (partial,
  HIGH).

- [x] T023 Correct registration handoff guards in `scripts/ci/terragrunt-apply.sh` using
  `scripts/ci/argocd-registration-plan-check.py`, following plan: Registration apply guard correction.
  First add realistic saved-plan fixtures to `scripts/ci/terragrunt-apply-test.py` that execute the real
  guard through the existing apply-script harness. Permit only exact managed native ImageUpdater
  pure deletion whose configured AND refreshed observed state are paused, with a same-unit retained
  same-identity Application; cover temporary omitted-field and permanent explicit-clear transitions.
  In existing-only mode permit only exact native CR pure creation beside that retained Application,
  with concrete planned native identity/mapping; continue blocking all new Applications and unrelated
  creates. Reject observed-unpaused or missing/unknown state, wrong API/kind/address/mapping,
  replacement, absent/renamed/deleted/replaced Application, and cross-plan identity borrowing; assert
  rejection precedes apply. Keep Conftest and saved-plan/current-main checks in their existing order.
  Run the real guard on both handoff and existing-only reenrollment plans in
  `scripts/ci/argocd-image-updater-provider-test.py` to cover actual provider state shapes.
  Run the complete `terragrunt-apply-test.py`, relevant Conftest Terraform regressions, Python/shell
  lint and Spec Kit checks, then update operator validation notes/checkpoint with source-only evidence.
  Depends on completed T008–T011/T015 and accepted guard plan correction; run after separate read-only
  analysis and before final convergence/T018. Existing completed task evidence remains unchanged.

## Phase 8: Convergence

- [x] T024 Extend both pull-request and main-push path filters in
  `.github/workflows/argocd-image-updater.yml` to include
  `scripts/ci/argocd-registration-plan-check.py` and `scripts/ci/terragrunt-apply.sh`,
  so changes to the real registration guard or its integration run the actual-provider
  saved-plan compatibility regression. Add a focused workflow-filter assertion and
  validate workflow syntax per T023 and plan: Registration apply guard correction
  (partial, MEDIUM).

- [x] T025 Remove the unnecessary literal provider token from the isolated API
  fixture in `scripts/ci/argocd-image-updater-provider-test.py`, following plan:
  Loopback fixture credential correction. Run all actual-provider cases and the
  pinned Checkov secret scan; preserve scanner policy and record evidence before
  parent-owned delivery. Depends on completed T023/T024.


- [x] T026 Integrate origin/main 8b37fe41 without losing native updater or
  Uptime Kuma/AdGuard changes. Resolve the feature pointer to this feature,
  retain both validation sections and fixture inputs, and run affected apply,
  offline static, secret and documentation checks. Leave the uncommitted merge
  ready for parent-owned signing and protected delivery.
