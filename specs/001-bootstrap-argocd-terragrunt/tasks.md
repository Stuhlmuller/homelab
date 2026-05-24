# Tasks: Bootstrap Argo CD With Terragrunt

**Input**: Design documents from `/specs/001-bootstrap-argocd-terragrunt/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: No TDD/unit-test tasks were requested. Validation tasks for Terragrunt/OpenTofu, Helm, Kubernetes, Argo CD, and input/secret handling are included because this feature changes infrastructure delivery.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Terragrunt/OpenTofu**: `IaC/root.hcl`, `IaC/**/terragrunt.hcl`, `*.tf`
- **Kubernetes/GitOps**: `clusters/**`, `**/kustomization.yaml`, `**/values.yaml`, `**/*.yaml`
- **Documentation**: `docs/**`, `ONBOARDING.md`, `AGENTS.md`
- **Feature artifacts**: `specs/001-bootstrap-argocd-terragrunt/**`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the repository layout and catalog source references needed before story work.

- [X] T001 Record remote catalog module constraint in `IaC/bootstrap/argocd/README.md`
- [X] T002 Create bootstrap Terragrunt directory README placeholder in `IaC/bootstrap/argocd/README.md`
- [X] T003 [P] Create Argo CD desired-state directory README placeholder in `clusters/homelab/argocd/self-management/README.md`
- [X] T004 [P] Create operator runbook placeholder in `docs/argocd-bootstrap.md`
- [X] T005 Record catalog source, selected module, and ref in `IaC/bootstrap/argocd/terragrunt.hcl`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Pin the remote catalog module and shared input conventions that block all user stories.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 Source the catalog Helm release module at `ref=0.3.0` in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T007 [P] Verify catalog tag `0.3.0` exists for `terragrunt-catalog`
- [X] T008 [P] Remove repository-local OpenTofu module files from `IaC/modules/`
- [X] T009 [P] Document catalog module usage and chart-version pinning in `IaC/bootstrap/argocd/README.md`
- [X] T010 Confirm the catalog source uses `modules/helm-release` in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T011 [P] Confirm self-management Application is expressed as a Terragrunt `after_hook` in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T012 [P] Confirm no catalog module code is vendored under `IaC/modules/`
- [X] T013 [P] Document CRD ordering through the Terragrunt `after_hook` in `docs/argocd-bootstrap.md`
- [X] T014 Define shared bootstrap input values in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T015 Use catalog module outputs from `helm-release` for handoff verification where needed
- [X] T016 Document committed non-secret input rules and CI/CD-only secret injection in `IaC/bootstrap/argocd/README.md`
- [X] T017 Confirm the root Terragrunt include exposes only committed non-secret inputs in `IaC/root.hcl`

**Checkpoint**: Foundation ready - the remote catalog module and shared inputs are available for user story implementation.

---

## Phase 3: User Story 1 - Bootstrap Argo CD From Repo State (Priority: P1) MVP

**Goal**: A clean Terragrunt-driven path installs Argo CD and registers Argo CD's own desired state from this repository.

**Independent Test**: From documented prerequisites, the operator can run the Terragrunt bootstrap path and see Argo CD installed with a repo-owned self-management Application present.

### Implementation for User Story 1

- [X] T018 [US1] Implement the catalog Helm release call for installing Argo CD in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T019 [US1] Implement the Argo CD self-management Application through a Terragrunt `after_hook` in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T020 [US1] Add explicit CRD wait ordering so Argo CD CRDs exist before the self-management Application in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T021 [US1] Create the single bootstrap Terragrunt entry point in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T022 [US1] Define committed non-secret bootstrap inputs in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T023 [US1] Pin the Argo CD Helm chart version and internal service exposure settings in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T024 [US1] Create initial Argo CD self-management desired-state manifest in `clusters/homelab/argocd/self-management/application.yaml`
- [X] T025 [US1] Add a Kustomize entry point for Argo CD self-management desired state in `clusters/homelab/argocd/self-management/kustomization.yaml`
- [X] T026 [US1] Document the one-command bootstrap workflow in `docs/argocd-bootstrap.md`
- [X] T027 [US1] Link the Argo CD bootstrap runbook from `ONBOARDING.md`

**Checkpoint**: User Story 1 is independently complete when the repo contains the one Terragrunt bootstrap entry point, the initial Argo CD install inputs, and the self-management Application desired state.

---

## Phase 4: User Story 2 - Continue Managing Argo CD Through Argo CD (Priority: P2)

**Goal**: Argo CD owns steady-state Argo CD configuration after the bootstrap handoff.

**Independent Test**: A reviewer can identify which files Argo CD owns after handoff and how a reviewed repo change becomes the steady-state source.

### Implementation for User Story 2

- [X] T028 [US2] Define self-management sync policy handoff rules in `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T029 [US2] Add automated prune/self-heal desired state in `clusters/homelab/argocd/self-management/application.yaml`
- [X] T030 [US2] Document the transition from first-sync validation to automated reconciliation in `docs/argocd-bootstrap.md`
- [X] T031 [US2] Document the Argo CD ownership boundary after handoff in `clusters/homelab/argocd/self-management/README.md`
- [X] T032 [US2] Add drift and reconciliation expectations for Argo CD-owned resources in `docs/argocd-bootstrap.md`

**Checkpoint**: User Story 2 is independently complete when the handoff mode, ownership boundary, and automation-enablement path are unambiguous in repo-owned files.

---

## Phase 5: User Story 3 - Recover Safely From Bootstrap Problems (Priority: P3)

**Goal**: Operators have clear validation, rollback, and recovery guidance for partial bootstrap and emergency live intervention.

**Independent Test**: A reviewer can find the expected healthy states, failed states, rollback path, and repository backfill rules without inventing live fixes.

### Implementation for User Story 3

- [X] T033 [US3] Add missing-CRD recovery guidance to `docs/argocd-bootstrap.md`
- [X] T034 [US3] Add bad repository path recovery guidance to `docs/argocd-bootstrap.md`
- [X] T035 [US3] Add missing credential recovery guidance with CI/CD-only secret injection boundaries to `docs/argocd-bootstrap.md`
- [X] T036 [US3] Add partial-install rollback guidance to `docs/argocd-bootstrap.md`
- [X] T037 [US3] Add break-glass live-change backfill requirements to `docs/argocd-bootstrap.md`
- [X] T038 [US3] Add quick operator recovery summary to `ONBOARDING.md`

**Checkpoint**: User Story 3 is independently complete when each documented failure mode names a diagnosis path, recovery action, and repository backfill expectation.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Tighten docs, consistency, and generated artifacts after user stories are implemented.

- [X] T039 [P] Update feature quickstart with final implementation paths in `specs/001-bootstrap-argocd-terragrunt/quickstart.md`
- [X] T040 [P] Update operator contract with final committed input names in `specs/001-bootstrap-argocd-terragrunt/contracts/bootstrap-operator-contract.md`
- [X] T041 [P] Update data model with final field names and state transitions in `specs/001-bootstrap-argocd-terragrunt/data-model.md`
- [X] T042 Review bootstrap requirements checklist findings in `specs/001-bootstrap-argocd-terragrunt/checklists/bootstrap.md`
- [X] T043 Confirm generated active technology context remains accurate in `AGENTS.md`

---

## Phase 7: IaC, GitOps, and Operations Validation

**Purpose**: Prove the desired state is reviewable, reproducible, and safe to apply.

- [X] T044 Run Terragrunt HCL formatting for affected stacks and record result in `docs/argocd-bootstrap.md`
- [X] T045 Confirm no repository-local OpenTofu module files remain under `IaC/modules/`
- [X] T046 Run OpenTofu validation for the bootstrap stack and record result in `docs/argocd-bootstrap.md`
- [X] T047 Run Terragrunt plan for `IaC/bootstrap/argocd/terragrunt.hcl` and record result in `docs/argocd-bootstrap.md`
- [X] T048 Render or build `clusters/homelab/argocd/self-management/kustomization.yaml` and record result in `docs/argocd-bootstrap.md`
- [X] T049 Run Kubernetes read-only preflight checks for Argo CD namespace and CRD assumptions and record result in `docs/argocd-bootstrap.md`
- [X] T050 Confirm no raw secrets, private kubeconfigs, tokens, keys, or certificate material are committed in `IaC/root.hcl`, `IaC/bootstrap/argocd/terragrunt.hcl`, `clusters/homelab/argocd/self-management/application.yaml`, `docs/argocd-bootstrap.md`, and `specs/001-bootstrap-argocd-terragrunt/quickstart.md`
- [X] T051 Confirm no `get_env`, `TF_VAR_*`, shell-exported values, or process environment lookups are used as normal desired-state inputs in `IaC/root.hcl` and `IaC/bootstrap/argocd/terragrunt.hcl`
- [X] T052 Verify `docs/argocd-bootstrap.md` includes apply, validation, rollback, partial recovery, and storage/backup impact notes

**Apply note**: T047 passed after refreshing AWS SSO credentials. The saved plan
created the Argo CD Helm release, and `terragrunt --log-disable apply -no-color
plan.out` installed Argo CD and applied the self-management Application through
the Terragrunt `after_hook`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion - blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational completion - MVP bootstrap path.
- **User Story 2 (Phase 4)**: Depends on User Story 1 because steady-state handoff requires the bootstrap seed path.
- **User Story 3 (Phase 5)**: Depends on User Story 1 for concrete recovery paths, but can be drafted in parallel with User Story 2 documentation after the bootstrap files exist.
- **Polish (Phase 6)**: Depends on all desired user stories being complete.
- **Validation (Phase 7)**: Depends on concrete desired-state files being complete and blocks live rollout.

### User Story Dependencies

- **User Story 1 (P1)**: Required MVP. Creates the install and self-management seed path.
- **User Story 2 (P2)**: Depends on US1. Defines Argo CD steady-state ownership and automation handoff.
- **User Story 3 (P3)**: Depends on US1. Adds operational recovery and backfill requirements.

### Within Each User Story

- Module/source files before Terragrunt wiring.
- Terragrunt wiring before runbook command examples.
- Desired-state manifests before Kustomize entry points.
- Handoff documentation before automation-enablement documentation.
- Recovery documentation after concrete bootstrap files and expected states exist.

### Parallel Opportunities

- T003 and T004 can run in parallel after T001 and T002 are not required.
- T007, T008, and T009 can run in parallel with T011, T012, and T013 after module directories exist.
- T026 and T027 can run in parallel after T021 through T025 are drafted.
- T030, T031, and T032 can run in parallel after T028 and T029.
- T033 through T036 can run in parallel because they edit distinct recovery subsections in `docs/argocd-bootstrap.md`; coordinate to avoid same-file conflicts.
- T039, T040, and T041 can run in parallel during polish.

---

## Parallel Example: User Story 1

```bash
# After foundational catalog module pinning is complete:
Task: "T024 [US1] Create initial Argo CD self-management desired-state manifest in clusters/homelab/argocd/self-management/application.yaml"
Task: "T026 [US1] Document the one-command bootstrap workflow in docs/argocd-bootstrap.md"
Task: "T027 [US1] Link the Argo CD bootstrap runbook from ONBOARDING.md"
```

## Parallel Example: User Story 2

```bash
# After the bootstrap seed path exists:
Task: "T030 [US2] Document the transition from first-sync validation to automated reconciliation in docs/argocd-bootstrap.md"
Task: "T031 [US2] Document the Argo CD ownership boundary after handoff in clusters/homelab/argocd/self-management/README.md"
```

## Parallel Example: User Story 3

```bash
# After expected bootstrap states are documented:
Task: "T033 [US3] Add missing-CRD recovery guidance to docs/argocd-bootstrap.md"
Task: "T034 [US3] Add bad repository path recovery guidance to docs/argocd-bootstrap.md"
Task: "T035 [US3] Add missing credential recovery guidance with CI/CD-only secret injection boundaries to docs/argocd-bootstrap.md"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Remote catalog module pinning.
3. Complete Phase 3: User Story 1 bootstrap seed path.
4. Stop and validate the Terragrunt plan and desired-state files before any live apply.

### Incremental Delivery

1. Deliver US1 to create the Terragrunt seed path and self-management Application.
2. Deliver US2 to make the Argo CD handoff and steady-state ownership explicit.
3. Deliver US3 to make recovery and rollback operationally safe.
4. Run Phase 7 validation before live rollout.

### Team Strategy

With multiple contributors:

1. One contributor pins and validates the catalog module source in `IaC/bootstrap/argocd/terragrunt.hcl`.
2. One contributor drafts `docs/argocd-bootstrap.md`.
3. One contributor prepares `clusters/homelab/argocd/self-management/`.
4. Coordinate before editing `IaC/bootstrap/argocd/terragrunt.hcl` or `docs/argocd-bootstrap.md`, because those files collect the main integration work.

---

## Notes

- [P] tasks use different files or can be safely split by section.
- [US1], [US2], and [US3] labels map to user stories in `spec.md`.
- Validation tasks are required for this infrastructure change even though no unit-test/TDD workflow was requested.
- Live rollout must wait for Phase 7 validation or a documented exception.
