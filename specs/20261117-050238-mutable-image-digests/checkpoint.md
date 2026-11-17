# Workflow checkpoint

## Specification stage — 2026-11-16

- Owner: assigned specification worker, coordinated by the parent task.
- Worktree: `/workspace/homelab-image-updater`.
- Branch/base: `codex/mutable-image-digests` at
  `48e8b9e4627f4a37f30d00f2d28b96d64133996e` before feature edits.
- Canonical artifacts: `spec.md`, `checklists/requirements.md`; active feature
  recorded in `.specify/feature.json`.
- Stage invocation: executed the installed `$speckit-specify` agent workflow;
  resolved its template using `.specify/scripts/python/common.py`'s
  `resolve_template`. There are no before/after specify hooks (`hooks: {}`).
- Installation: Spec Kit 0.15.1, timestamp numbering; local constitution 1.0.0.
  Retained repository desired-state, secret, validation, teaching, and ownership
  principles. No constitution edits.
- Read official `github/spec-kit` revision
  `a227e38315cd38172b04f2fb8f06ce8b69b38331`: `spec-driven.md`,
  `docs/quickstart.md`, `docs/reference/agentic-sdd.md`, and
  `templates/commands/specify.md`. Base source URL:
  <https://github.com/github/spec-kit/tree/a227e38315cd38172b04f2fb8f06ce8b69b38331>.
  The initial combined output was truncated; the quickstart/reference and final
  methodology section were reread separately. Other command definitions remain
  for their respective stages. Upstream examples do not override the local
  constitution or installed resolver: local configuration forbids environment
  variables for feature selection and uses a priority template resolver.
- Source findings: shared Application module has computed fields but no lifecycle
  ignores; updater values declare zero replicas and Git proposal write-back;
  image-automation workflow contains a direct PATCH to the main Git ref; GitOps
  wiki still describes committed digest ownership. These are confirmed source
  facts, not current live-state observations.
- Decisions: separate Git branch resolution from image-tag digest resolution;
  preserve owner-selected references and unrelated declarative fields; replace
  conflicting ownership only for explicitly enrolled images; do not unpin the
  whole repository or invent workload channels.
- Quality review: 16/16 built-in requirements checks passed, no unresolved
  essential questions. Three user stories, twelve requirements, five outcomes.
- Verification: template/state resolution and specification review only. No
  application code changes or runtime claims.
- Outstanding: determine supported concrete override fields, target enrollment,
  controller activation prerequisites, and validation in clarify/plan stages.
- Next stage: a separate `$speckit-clarify` turn, then planning. No implementation
  has begun.
- Tracking card: <https://app.notion.com/p/41be535fc628813fb106d7b9f3d9e150>.
- Checks passed: `python3 -I scripts/ci/speckit-check.py` (Python and Bash
  feature/plan/task/path resolution suites), `git diff --check`.

## Clarification stage — 2026-11-16

- Executed installed `$speckit-clarify` as a separate stage; prerequisite
  `--json --paths-only` resolved the same canonical feature. No hooks registered.
- Read corresponding upstream `templates/commands/clarify.md` completely at
  revision `a227e38315cd38172b04f2fb8f06ce8b69b38331`.
- Primary lifecycle issue: <https://github.com/Stuhlmuller/homelab/issues/1846>.
  Parent coordinator owns GitHub and Notion tracking updates.
- Questions asked/answered: 0. Four evidence-based decisions recorded, explicitly
  attributed to the agent: selector changes remain authoritative; enrollment is
  explicit and no historical candidates activate implicitly; pause retains the
  effective hash and removal requires declarative handoff; provider behavior must
  be tested, not inferred from a lifecycle declaration.
- Source evidence: `image-automation.json` has two not-enrolled candidates;
  shared `argocd-app` unit passes declarative source inputs; Application module
  separates `manifest` from `computed_fields` and uses provider 3.2.1.
- Sections updated: status, Clarifications, Functional Requirements, Success
  Criteria. FR-005/010 refined, FR-013 and SC-006 added.
- Requirements checklist re-evaluated: 16/16 → 16/16, no changed markers,
  regressions, or unchecked items. Checklist file left unchanged.
- Coverage: functional scope, domain lifecycle, edge cases and completion signals
  resolved; interaction, non-functional outcomes, terminology, constraints and
  placeholders clear. Integration implementation (concrete provider field paths,
  supported updater APIs, controller activation prerequisites and test design)
  deferred to planning because these are design choices, not missing user intent.
- No critical ambiguity requires a user question. No tag chosen for the user.
- Next: separate `$speckit-plan` turn. No application implementation changes.
- Coordinator's current read-only runtime evidence: updater Application is
  NotFound, no updater Deployment in `argocd`, ImageUpdater CRD exists. Planning
  must assess safe controller registration even with empty enrollment; do not
  claim active runtime updates or invent a target tag.
- Research handoff for planning: Image Updater v1.3.0 chooses the first matching
  Helm/Kustomize source; supported multi-source scope may need exactly one render
  source plus value refs. Provider v3.2.1 refreshes `object`, not `manifest`;
  computed fields preserve runtime values for unchanged configuration. These
  source-specific findings are design inputs, not a claim that lifecycle ignores
  alone satisfy the required behavior.

## Planning stage — 2026-11-16

- Executed installed `$speckit-plan` and `setup_plan.py --json` for the same
  feature; read upstream plan command completely at the recorded revision.
- Generated `plan.md`, `research.md`, `data-model.md`,
  `contracts/enrollment.md`, and `quickstart.md`. No task list or custom checklist
  generated; no application code edited.
- Design: native digest/Argo CD CRs; explicit opt-in sibling module retaining
  `kubernetes_manifest.this`; exclusively image-owned override collections;
  source zero sole renderer plus refs; paired lifecycle/computed fields;
  selector outside ignored fields; protected PR-only legacy proposal delivery.
- Research findings and alternatives recorded. XERJ tools unavailable; official
  pinned source used instead. Chart values read completely; provider/updater
  relevant implementation excerpts read, not whole repositories.
- Pre/post design constitution checks pass. Provider integration must prove
  normal refresh and between-plan/apply preservation/rejection. Failure keeps
  enrollment disabled and requires an implementation fix, not a weaker claim.
- Controller may be registered idle through existing access if image/chart
  prerequisites work; no operator tag invented or historical consumer enrolled.
- Next: separate custom requirements checklist generation, then explicit review
  before task generation. Coordinator owns issue/Notion updates; no Notion write
  attempted by this worker.
- Checks passed: `git diff --check`; Spec Kit Python/Bash feature, plan, task,
  and path resolution suites. No runtime or provider regression executed in this
  design stage. Available binaries include OpenTofu 1.12.3 and Python with
  PyYAML; Nix activation's sandbox limitation is not a reason to bypass controls.

## Checklist generation stage — 2026-11-16

- Executed installed `$speckit-checklist`; prerequisite command returned the same
  feature and its research/data-model/contracts/quickstart documents. Read the
  installed template and complete upstream checklist command at the recorded
  Spec Kit revision. No before/after hooks registered.
- Created `checklists/ownership.md`, ten new unchecked items CHK001–CHK010.
- Focus: ownership boundaries, concurrency preservation or rejection, protected
  delivery, and enrollment/recovery transitions. Standard depth; coordinator
  reviewer before task generation. No clarification question needed because the
  requested focus and audience were explicit.
- All items have requirement/design traceability and test requirements quality,
  not implementation behavior. No existing checklist marker changed.
- Next: coordinator's separate evidence-based checklist review, then task
  generation. No implementation or review performed in this generation stage.

## Checklist review — coordinator

Reviewed the generated 10-item ownership checklist against spec, plan, data model, enrollment contract and quickstart in a separate review turn. All 10 pass requirement quality. Provider preservation/race behavior and actual controller readiness remain unproven implementation obligations, not waived gates. Next: task generation.

## Task generation stage — 2026-11-16

- Executed installed `$speckit-tasks` and `setup_tasks.py --json` for the same
  feature; read complete official task command at the recorded upstream revision.
  Installed setup returns a template path rather than composed content; used
  that returned template as supported. No before/after hooks registered.
- Generated `tasks.md`: 18 unchecked tasks; setup 1, foundation 2, US1 4, US2 4,
  US3 4, cross-cutting 3. Explicit dependencies, file paths, requirement coverage,
  independent story checks and bounded turn strategy included.
- Independent-file opportunities: controller values versus native CR work,
  workflow fixtures versus provider tests, docs versus protected workflow edits.
  Shared module/test files stay single-writer.
- Real provider preservation/concurrency acceptance remains required; source-only
  assertions cannot satisfy it. External workload acceptance remains pending
  explicit target selection rather than being fabricated as a completed task.
- Next: separate read-only `$speckit-analyze` stage. No analysis or application
  implementation performed in this task generation stage.

## Analysis and plan correction — 2026-11-16

- Prior read-only analysis found C1 (high): FR-009 did not concretely reconcile
  Renovate global pinning and Harbor direct-image digest enforcement; C2
  (medium): removal lacked explicit provider transition coverage; I1 (low):
  spec status text was stale. No artifact changed during analysis.
- This separate planning correction resolves C1/C2 design: exact `source_paths`
  on existing per-app enrollment; resolved Terragrunt inputs remain the sole
  canonical source; exact package/file Renovate exclusion required; tag-only
  allowance bound to path/repository/tag and existing provenance. Empty/default
  policy stays unchanged; no second registry or mirror redesign.
- Removal now requires pause, then default same-address module with explicit
  empty/replacement overrides, native CR removal and restored Renovate ownership.
  The provider transition must demonstrate clearing without Application replacement.
- Updated plan, research, data model, enrollment contract and quickstart only.
  No task, spec, checklist marker or implementation change in this turn.
- Next: separate task correction for C1/C2, then requirements review of changed
  design and repeat read-only analysis. I1 remains for an owning spec turn.
- Coordinator source finding incorporated into plan: shared unit defaults must
  seed `sources` only when no explicit source form exists; actual unit render
  tests must cover single-source input and unchanged ordinary defaults.

## Task correction — 2026-11-16

- Separate task-only turn reconciles C1/C2 design with the executable breakdown.
- Preserved IDs T001–T018; refined uncompleted T002/T003 source-path validation,
  T008 provider removal transition, T010 actual single-source/default unit renders,
  and T015 policy/removal docs.
- Added T019–T021 under US3: resolved-input enrollment/precise Renovate ownership,
  path-bound Harbor policy integration, and positive/negative ownership fixtures.
  Dependencies explicitly schedule fixtures before implementation and these tasks
  before cross-cutting validation despite appended numeric IDs.
- Total 21 unchecked tasks: US1 4, US2 4, US3 7, setup/foundation 3,
  cross-cutting 3. Requirement mapping updated for FR-009/010/012.
- No code, spec, plan, or checklist marker edited. Next: coordinator design review
  and separate read-only reanalysis before implementation.
- Coordinator separately reviewed corrected plan/contract: C1's exact package/file
  exclusions and path/repository/tag allowances preserve unenrolled policy;
  C2's explicit pause/removal handoff and provider test are adequate requirements.
  Existing 10-item ownership checklist remains reviewed/passing; no new checklist
  or repeated checklist generation is needed. Next is read-only reanalysis.

## Read-only reanalysis result (persisted by implementation stage)

- Reanalysis closed C1/C2 at artifact level; all 13 functional requirements and
  six outcomes map to 21 tasks. No new essential gap, dependency contradiction,
  unmapped task or constitution conflict. I1 was stale status wording only.
- No files changed in that completed analysis turn. This implementation turn
  updates the spec status to implementation in progress.

## Implementation increment 1 — T001–T007

- Ran installed `$speckit-implement` prerequisites; requirements checklist 16/16,
  ownership checklist 10/10, zero unchecked items. Hooks remain empty. Existing
  git ignore rules cover provider caches/state/private tfvars and generated
  Terragrunt directories; no new upload/packaging ignore file was necessary.
- Completed T001/T002/T004/T005/T006/T007. T003's native input/source/override
  cases pass; keep its marker open until T019/T021 supply the additional
  file-content occurrence/ownership fixtures. Do not mistake path containment
  validation for complete package-file ownership.
- New opt-in module foundation contains typed inputs, exact native CR generation,
  and semantic resource preconditions. The Application resource and unit routing
  are deliberately deferred to T009/T010. It is not yet an enrollable module.
- Native pause uses v1.3.0 `ignoreTags: ["*"]`; running uses `[]`. The generated
  CR fixes digest strategy, exact application name and Argo CD write-back.
  No workload channel or digest has been selected or committed.
- Corrected chart values to `config.log.level` and `--interval=2m`; removed inert
  camelCase/Git write-back keys. Declared one idle replica with resource requests
  and the existing pinned controller image; added explicit registration stack.
  The status ConfigMap records no workloads enrolled.
- Prerequisite evidence supplied by coordinator: chart 1.3.1 renders; read-only
  registry lookup returns controller digest
  `sha256:cb009167015c6212ea21de55dd5734cf123d8b8e95f40ac09b1f1aa1839fad5b`.
  This is manifest availability, not a full pod pull. Worker read-only query
  found zero native ImageUpdater CRs in `argocd`, so no existing wildcard CR
  becomes active on controller registration. No live state mutated.
- Checks: actual HCL plans for four Helm/Kustomize single/multi forms, unchanged
  and changed selectors, pause, ref values files, full-image Helm mapping, and
  16 negative cases all pass. Test validates generated payload shapes against
  the pinned chart's native CRD and checks effective controller config/args.
  Initial expected failure (missing module implementation) recorded; subsequent
  native HCL validation-cycle and heterogeneous-list errors were corrected.
- `kustomize build`, OpenTofu format check, new stack Terragrunt format check,
  and `git diff --check` passed. Test uses locked `yq` for YAML because Nix Python
  lacks PyYAML. Commands run via sanctioned escalated locked Nix devshell;
  no sandbox workaround or tool reprovisioning used.
- Render artifact: `/tmp/mutable-image-updater-rendered.yaml` (local verification
  output only). Source validation does not prove registry polling/runtime update.
- Coordinator integrated T013 from an isolated worker during this increment;
  those workflow/test files and its task marker were not edited by this worker.
- Next: US2 T009/T010 and integration of independently prepared T008 provider
  fixture, then T011. Provider test needs an explicit cache/offline strategy and
  appropriate premerge online CI placement; it must not silently make offline
  checks network-dependent.

## Implementation increment 2 — Application module and shared unit

- Wrote T009 source: same `kubernetes_manifest.this` address; original required
  provider 3.2.1, encryption block and KMS variable contract; source-specific
  computed image collection with four literal lifecycle ignore paths; exact
  ownership preconditions and `force_conflicts=false`. Native CR depends on the
  Application. T009 remains unchecked pending the provider/atomic-source result.
- Completed T010: unit selects opt-in only for non-null explicit `image_update`;
  normal default module unchanged. Default sources are now seeded only if neither
  source form is explicitly supplied, preventing an accidental second source
  form for single-source input.
- Actual checks passed: four native HCL forms and selector/pause transitions,
  16 invalid enrollments; six real shared Terragrunt unit renders (default,
  single, multi, each opted in/out); pinned chart CR shapes and effective config;
  original eight computed-field cases; provider/encryption/KMS source parity;
  narrow computed image paths; OpenTofu/Terragrunt formatting; diff check.
- Critical implementation evidence: read-only live Application CRD has atomic
  `spec.sources` and Helm parameter arrays (no `x-kubernetes-list-type`). Thus
  non-forced SSA may reject intentional edits inside an updater-owned multisource
  list, not merely stale image updates. Do not weaken conflict handling or claim
  that native per-leaf HCL checks prove SSA behavior.
- Independently assigned T008 worker has been notified and is testing the actual
  provider against the real CRD shape plus bounded API fixture. T011 stays open.
  Coordinator is investigating a paused/default-module handoff that preserves
  controller-only override state without copying a digest into code. No handoff
  assumption has been added to requirements or implementation in this turn.
- Next: await provider evidence, then a separate clarify/plan correction if needed
  for atomic-source edit semantics before dependent implementation or enrollment.
  No live mutation or deployment performed.

## Clarification correction from provider evidence — 2026-11-16

- Separate `$speckit-clarify` turn; paths-only prerequisites resolve the same
  feature. No before/after hooks. No user questions required: this is a routine
  evidence-backed ownership decision preserving the user's no-code-hash rule.
- Independent provider worker reports four actual-provider 3.2.1 cases across
  single/multi source and seeded/absent bootstrap collection histories. Active
  multi-source edits reject under atomic ownership and non-forced apply. With
  never-configured collections, pause → default module (collection still omitted)
  plus intended source edit preserves runtime C, removes only the updater CR,
  keeps Application identity, and reenrollment retains C without a hash input.
  This is real-provider/local API fixture evidence, not live rollout acceptance.
- Updated spec clarifications, FR-005/013, story 2, edge cases, status and SC-007.
  Enrollment now requires runtime override collections absent (not empty/seeded).
  Existing configured collections need reviewed default-owner migration first;
  no automatic migration is implied. Active conflicts fail closed; explicit
  paused handoff supports deliberate multi-source list changes.
- Built-in requirements checklist re-evaluated: 16/16 → 16/16, no marker changes,
  regressions or unchecked items. Custom ownership checklist remains untouched
  pending coordinator review of the reconciled design.
- No plan, tasks, application code, or custom checklist markers changed.
- Next: separate plan correction, then task correction and read-only analysis
  before implementing the revised absence precondition and handoff docs/tests.

## Plan correction after provider evidence — 2026-11-16

- Reconciled plan/research/data-model/contract/quickstart with the clarified
  requirement: runtime collections must be absent, not empty/seeded; bootstrap
  tags stay in workload source. Existing seeded configuration requires prior
  reviewed ordinary-owner migration, not automatic deletion or state changes.
- Active enrollment retains non-forced SSA. Atomic multi-source edits use pause
  → temporary default-module omission with intended source change → reenrollment.
  Permanent removal remains a separate explicit empty/replacement transition.
- Closed the maintenance ownership gap: a mutually exclusive
  `image_update_handoff` mapping with paused true preserves exact policy/Renovate
  ownership during temporary default-module operation but creates no CR. This
  remains the same per-stack source of truth; no hash or second registry added.
- Parent-owned helper names reconciled to `argocd-image-updater-policy.py` and
  `argocd-image-updater-policy-test.py`. No parent-owned source files touched.
- Updated only design artifacts/checkpoint; no task or code edits. Next: task
  reconciliation, coordinator review, and read-only analysis before enforcement.

## Task correction for absent-collection and handoff design — 2026-11-16

- Coordinator reviewed the corrected design, including explicit temporary
  handoff metadata preserving policy/Renovate ownership. No new checklist needed.
- Refined T003/T009 to reject empty and seeded configured runtime collections.
  T008 now covers never-configured omission/source-edit/reenrollment without a
  hash input, retains seeded history as migration evidence, and distinguishes
  permanent removal. T015 documents the separate transitions and prerequisites.
- Reopened T010: original source/default module renders passed; it additionally
  must retain handoff metadata for policy in rendered inputs, select the default
  module, reject active+handoff and unpaused/seeded handoff, and avoid undeclared
  default-module variable warnings. No completed evidence was discarded.
- T019/T021 now use parent-owned policy helper/test filenames and explicitly
  validate active/paused-handoff ownership plus permanent removal. Requirement
  coverage includes SC-007. Task IDs remain T001–T021.
- Only tasks/checkpoint edited; no code or design artifact change this turn.
- Next: separate read-only reanalysis, then bounded implementation correction.

## Read-only correction analysis result (persisted after stage)

- Corrected artifacts passed read-only reanalysis: all 13 requirements/seven
  outcomes map to 21 tasks, no essential gap or constitution conflict. Two minor
  contract wording issues remain for the documentation increment. No files were
  changed during analysis; this implementation turn persists its result.

## Implementation increment 3 — absent overrides and explicit handoff

- Completed T009/T010 correction: runtime override keys must be absent, including
  empty/seeded collections. Opt-in module rejects `image_update_handoff` alongside
  active enrollment. Unit preserves handoff metadata in rendered inputs while
  selecting the default module. The default module declares an optional handoff
  metadata variable, requiring paused=true and absent collections; ordinary
  null/default callers retain unchanged behavior and no undeclared variable
  warning is needed. Active registration stays non-forced.
- Native tests pass: 4 source forms/selector transitions; 21 rejected enrollments;
  7 actual unit renders; 4 valid paused default-module handoffs and 8 rejection
  cases; pinned chart payload/config checks. No unsupported seeded input is
  presented as an accepted enrollment.
- Integrated T008 test independently prepared by the provider worker, applied by
  coordinator, then rerun by this worker against the current canonical modules
  using cached signed provider3.2.1. All single/multi × Helm/Kustomize cases pass:
  54 captured actual apply requests and 6 non-forced conflicts. Includes refreshed
  digest preservation, unchanged plan, selector/pause, temporary omitted-collection
  source-edit handoff and reenrollment, permanent removal and recreation.
- T008/T009/T010/T011 complete at source/provider-fixture level. This is an actual
  provider communicating with a loopback schema/CRUD/conflict fixture; the fixture
  deliberately returns expected conflicts and is NOT live managedFields, registry
  polling, controller behavior or deployed workload acceptance.
- Coordinator independently implemented and validated T019/T020/T021 in the three
  claimed policy files: 11 negative policy cases; exact Harbor path allowance and
  wrong-path/missing-provenance/digest regressions; existing Harbor checks; actual
  all-stack render discovers zero owned pairs. Those results complete T003's
  outstanding file-content ownership coverage as well. Root code review remains
  a delivery step. No policy source file was edited by this worker.
- `git diff --check` passed. No live mutation, credentials change or deployment.
- Next: separate US3 documentation/remaining validation wiring increment, followed
  by final checks and append-only convergence. Runtime acceptance stays open.

## US3 documentation and validation wiring checkpoint

Implemented T012–T016, including integrated T013: protected PR script fixtures
reject direct PATCH/push, force and admin bypasses and moving candidate/base/PR
heads. Existing policy `validate_legacy` owns dual-enrollment rejection; no
second legacy catalog or duplicated ownership algorithm was added. Runtime tags
remain operator-selected and actual enrollment remains empty.

The operator guide and app README now describe exact source occurrence/tag
matching, exact marked Renovate rules, absent runtime collections, the paused
`image_update_handoff` transition, default-module ownership transfer, permanent
removal and recreation. OpenWiki and the quickstart distinguish source/provider
fixture evidence from live controller and managed-field acceptance.

Offline checks now include native HCL/shared-unit and policy fixtures/validation.
The read-only, path-filtered `Argo CD runtime image ownership` PR/push workflow
runs provider initialization and pinned Helm rendering online. The closed static
job inventory and promotion gate checks now match `promote-pr` and the new job.
No credentials, live cluster mutation or required-check bypass were added.

Validation on base 48e8b9e: focused native HCL (four forms/21 negatives), actual
shared-unit (seven forms), default handoff (four positives/eight negatives),
native chart schema/effective configuration, policy (19 rejection cases),
protected PR regression, legacy check/render-check, OpenWiki, Spec Kit,
actionlint and Ruff passed. Full `offline-static-checks.sh` passed exit 0
(`/tmp/mutable-offline-static.log`). Final provider rerun passed all four forms,
54 actual provider apply requests and six deliberate non-forced API conflicts
(`/tmp/mutable-final-focused.log`). These are local API fixture results, not
live Kubernetes SSA/controller acceptance.

Full `offline-checks.sh` remains in flight in tool session 24950, log
`/tmp/mutable-offline-checks.log` (currently tailscale-private-dns tests); parent
can collect completion. No further large suite starts: parent reported upstream
main advanced to 15bfe279 (PR #1845). T017 remains pending applicable refresh
after integration. Parent owns main integration, separate convergence and T018
protected delivery. Tracking remains issue #1846 and the existing Notion card.

## Coordinator integration and convergence repair

Integrated protected main `15bfe27955e755a24617d9dd00bfbd7803da30d6` (PR #1845) by fast-forward plus preserved feature changes. GitOps documentation and offline-static checks merged cleanly; pre-integration changes remain in a local stash backup.

Post-integration Terragrunt apply-stage, plan-stage, apply and stack regressions plus the full offline-static suite passed. Secret/artifact scans passed. The broader offline suite remains owned by the existing worker while its unchanged independent tests finish.

Convergence appended T022 for Renovate minimatch behavior. A regression first reproduced a brace-pattern
bypass. The matcher now conservatively treats regex, negation, braces, extglobs, character classes and escaped
patterns as possible matches, folds simple glob case, and applies the same rules to datasource matching.
Unrelated explicit package/datasource rules remain allowed. The expanded policy suite passes 27 rejection
cases plus positive/handoff/removal/Harbor path-binding checks. Python lint passed; no policy or branch
protection was weakened. T022 implementation complete; separate convergence recheck follows.

## Final source verification

The full offline-checks suite completed with exit 0. After integrating main15bfe279, changed Terragrunt regression families and the full offline-static suite were rerun and passed. The final matcher changes passed focused policy regressions; actual provider, chart/native schema, HCL/unit rendering, workflow lint, Python lint, wiki, formatting and secret/artifact checks passed.

Separate convergence recheck found no remaining buildable source gaps and left tasks unchanged. T017 is
complete. T018 delivery/deployment remains tracked in issue #1846; source readiness does not claim a protected
merge or live controller/workload acceptance. No workload has been selected or enrolled. Detailed Notion
replication was not performed after automatic review rejected that disclosure; repository/issue records remain
authoritative.

## Registration guard plan correction checkpoint

Read-only delivery-path inspection found the real registration apply runner's
blanket manifest delete rejection blocks ImageUpdater removal for both documented
handoffs. Added a bounded plan correction only: exact paused native CR pure
deletion, verified in configured and refreshed state, must accompany the retained
same-identity Application in the same unit's saved plan. Every Application
replacement/deletion and every other manifest deletion stays rejected. Conftest
inspection found no additional blanket deletion blocker. Adjacent existing-only
create protection also needs a narrow native CR creation exception with the same
retained-Application proof; all new Application and unrelated manifest creations
remain prohibited. Native CR create validation uses concrete planned manifest,
not nonexistent observed state. This permits ordinary enrollment/reenrollment
without weakening the no-new-Application intent.

No tasks, source code, policies or tests changed in this stage. Next stage:
append dependency-ordered guard/negative-fixture tasks, then read-only analysis
before implementing the owning guard. The current delivery findings do not
invalidate provider preservation evidence; they show that delivery acceptance
must also exercise the actual saved-plan apply guard.

## Registration guard task correction checkpoint

Coordinator reviewed and accepted the bounded plan correction. Appended T023
without reopening or renumbering completed work: exact per-unit registration
plan guard, real apply-script fixture integration, paused observed-state deletion
for both handoffs, existing-only native CR creation, and fail-closed identity,
replacement and cross-plan negatives. The task preserves Conftest, saved-plan
and current-main sequencing and precedes final convergence/protected delivery.

No implementation or tests changed in this stage. Next: separate read-only
analysis of the corrected plan and task before T023 implementation. Draft PR
PR #1849 remains parent-owned; this stage performs no remote writes or merge.

## T023 implementation checkpoint

Implemented the narrow saved-plan registration validator and replaced both old
blanket create/delete predicates after Conftest and before current-main/saved-plan
apply. Only exact native updater pure deletion with configured and observed pause,
or existing-only native CR creation, can use a same-unit retained Application.
All other protected manifest deletions, replacements and existing-only creations
remain rejected. No remote mutation, protection bypass or Conftest relaxation.

The real apply-script harness now executes the actual Python guard. Positives
cover temporary/permanent handoff and active/paused existing-only enrollment.
Negatives cover observed-unpaused/missing state, wrong identities/mappings,
replacement, missing/changed Application and cross-unit proof. The actual provider
suite additionally passes source-edit, permanent-removal and existing-only
reenrollment saved-plan JSON through the real CLI for all four source forms.
Its first run exposed typed provider null-only nested renderer objects; the guard
now normalizes null dictionary fields/empty optional subtrees while retaining
meaningful overrides and invalid null list entries as failures. Fixtures reflect
that actual output shape.

Validation: complete apply suite passed (34 tests, including parameterized
transition cases); provider suite passed all four forms, 54 captured requests and
six expected conflicts; Ruff and shellcheck with source following passed;
Conftest policy verification passed 147 tests; Spec Kit passed both backends;
repository-configured Markdown lint passed canonical artifacts; full offline
static checks passed exit 0. Logs: `/tmp/image-registration-acceptance.log` and
`/tmp/image-registration-guard-validation.log`. Initial harness missing-live-app
fixture and optional-object normalization failures were corrected and rerun.

T023 complete. Operator docs describe saved-plan enforcement and source-only
acceptance limits. Next: separate convergence review and parent-owned publication
through draft PR 1849; runtime acceptance remains pending operator enrollment.

## T023 convergence review

Separate read-only review found the registration transition boundary consistent
with T023: exact native pure deletion requires configured and refreshed observed
pause; existing-only creation requires concrete native mapping; both require a
same-unit retained same-identity Application. Replacement, unrelated manifests
and cross-plan identity borrowing remain rejected before saved-plan apply.
Conftest and current-main sequencing remain intact. Actual-provider tests pass
source-edit, permanent-removal and reenrollment plans through the real guard.
Reviewed recorded evidence: 34 apply tests, four provider cases with 54 requests
and six expected conflicts, and 147 Conftest tests. No redundant suite rerun.

One MEDIUM partial validation-wiring gap remains: helper-only or apply-runner-only
changes do not match the ownership workflow paths. Appended T024 under Phase 8
to trigger actual-provider compatibility checks for both files on PRs and main.
No application source, spec, plan or existing task markers changed in review.
Complete T024 and run a separate convergence recheck before publication.

Delivery remains blocked independently: current base 15bfe279 Harbor runtime
audit fails validation:remediation, matching the PR failure. Main evidence:
<https://github.com/Stuhlmuller/homelab/actions/runs/44025092775/job/133843387412>.
Private package details remain withheld. No merge or deploy occurred, and T018
remains pending owner remediation and exact-head checks. Live acceptance remains
pending explicit workload enrollment; local fixture evidence is not live proof.

## T024 trigger coverage checkpoint

Added the registration plan helper and actual apply script to both PR and
main-push path filters for the actual-provider workflow. The existing static
suite now asserts both exact paths in both event filters; no separate test
framework or duplicated provider suite was added. Actionlint and the full
static suite passed exit 0 (`/tmp/image-registration-trigger.log`).

T024 complete; separate final convergence and remote publication remain
parent-owned. No remote writes in this increment. Runtime evidence and the
independent Harbor compatibility CI remediation blocker remain unchanged.

## Final T024 convergence

Independent read-only convergence confirmed both workflow event filters include
registration guard and apply runner changes and the static assertion enforces
that coverage. No remaining source findings. Full static checks, actionlint,
Markdown and whitespace checks passed after T024. T018 remains pending the
recorded Harbor remediation blocker, fresh exact-head checks, protected merge
and declared targeted deployment. No runtime acceptance or merge is claimed.
