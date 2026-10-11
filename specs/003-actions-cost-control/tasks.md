# Tasks: Homelab Actions Cost Control

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md)  
**Scope**: Workflow code and documentation in this checkout; the reviewer setting remains blocked by repository admin rights.

## Phase 1: Verify current controls

- [ ] T001 Read the active homelab ruleset `14700233` and `homelab-plan` environment through an authorized settings-capable connection; compare exact contexts and reviewer rules with `../github-iac/Stuhlmuller/repositories/terragrunt.hcl` (FR-001, FR-002).
- [ ] T002 Inventory each `.github/workflows/*.yml` event, condition, required context, production permission, and schedule; identify downstream consumers of `.github/workflows/image-automation.yml` `observe` (FR-003, FR-004, FR-005).

## Phase 2: User Story 1 - Unattended trusted plan (P1)

- [ ] T003 [US1] In `../github-iac/Stuhlmuller/repositories/terragrunt.hcl`, remove only the `homelab-plan` reviewer requirement after verifying `modules/github_repositories/main.tf` empty-list semantics (FR-001, FR-005).
- [ ] T004 [US1] Inspect the github-iac plan and policy output for exactly that environment change; confirm no `homelab-production`, ruleset, credential, OIDC, or other repo change (FR-001, FR-005).
- [ ] T005 [US1] Reconcile github-iac through its declared protected workflow; read the resulting environment settings and trusted plan job state without exposing secret values (FR-001, SC-001, SC-005).

## Phase 3: User Story 2 - Fewer optional runs (P2)

- [ ] T006 [US2] Remove optional PR events from `.github/workflows/nofx-images.yml`, `.github/workflows/openclaw-config.yml`, and `.github/workflows/image-automation.yml` while preserving main push and existing dispatch semantics; add an Image automation main push verifier only if needed for its existing acceptance path (FR-003, FR-004, FR-005).
- [ ] T007 [US2] Remove the five-minute schedule from `.github/workflows/image-automation.yml` and record the loss of automatic `observe` alerts in `docs/argocd-image-updater.md` (FR-004, SC-004).
- [ ] T008 [US2] Keep `.github/workflows/codeql.yml` required PR/main analysis and its weekly security schedule (FR-002, FR-004).
- [ ] T009 [US2] Verify required context producers `.github/workflows/lint.yml`, `validate.yml`, `codeql.yml`, `release.yml`, and `terragrunt-plan.yml` still emit all seven declared required contexts on applicable PRs; preserve external Policy Bot and Python analysis producers (FR-002, SC-002).

## Phase 4: Documentation and acceptance

- [ ] T010 Update `docs/ci-cd.md` and `openwiki/runbooks/ci-cd.md` with event matrix, environment reviewer behavior, security tradeoff, and exact rollback path (FR-006).
- [ ] T011 Verify `.github/workflows/homelab-diagnostics.yml` still provides exact-main-SHA read-only health check with private output withheld (FR-007).
- [ ] T012 Run narrow repository static checks, Spec Kit check, edited workflow parse, github-iac HCL validation, and `git diff --check` in both repositories (FR-005, FR-006).
- [ ] T013 Observe one representative protected PR and matching main push/manual dispatch; confirm all required checks are terminal, plan has no reviewer wait, fork isolation holds, and optional run count drops (SC-001 through SC-005).

## Dependencies

T001 and T002 precede changes. T003–T005 require the authorized github-iac path. T006–T009 can proceed after T002 but must preserve the seven contexts. T010–T013 follow implementation. Do not apply GitHub settings until T004 shows the exact narrow plan.
