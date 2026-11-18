# Tasks: Current Tailscale Enrollment Documentation

**Input**: [Specification](spec.md), [plan](plan.md), [research](research.md), [validation guide](quickstart.md).
**Organization**: One writer; documentation-only increments. Existing checks provide verification; no new runtime tests are needed.

## Phase 1: Setup

- [x] T001 Reconfirm the isolated checkout baseline, current scope and approved requirements review in `specs/20261118-045220-current-tailnet-docs/checklists/documentation.md` before editing.

## Phase 2: Foundation

- [x] T002 Inventory tracked authored Markdown including `.agents/skills/`, inspect enrollment helpers for recipe accuracy, and map inbound file/heading references starting from `openwiki/source-map.md`; keep investigation output outside committed prose.

## Phase 3: User Story 1 — Accurate Enrollment Guidance (P1)

**Goal**: Every enrollment guide describes the current setup directly.
**Independent acceptance**: Contextual review of all authored Markdown finds only current prerequisites and supported operational recipes.

- [x] T003 [P] [US1] Rewrite authentication and CI guidance in `IaC/terragrunt-catalog/modules/tailscale-access/README.md`, `docs/secrets-aws-ssm.md`, `docs/harbor-tailscale-production.md` and `clusters/homelab/apps/tailscale/README.md` around the current source-supported contract.
- [x] T004 [P] [US1] Rewrite network and workload enrollment prose in `docs/runtime-isolation.md`, `clusters/homelab/apps/traefik/README.md`,
  `clusters/homelab/apps/traefik/CUTOVER.md`, `clusters/homelab/apps/traefik/canary/README.md`, `clusters/homelab/apps/adguard/README.md`,
  `clusters/homelab/platform/tailnet-dns/README.md` and `clusters/homelab/platform/storage/README.md`; delete irrelevant dedicated enrollment guides under `clusters/homelab/apps/`
  without stubs.
- [x] T005 [P] [US1] Reconcile authored wiki prose in `openwiki/runbooks/tailnet-ingress.md`, `openwiki/runbooks/runtime-isolation.md`, `openwiki/runbooks/ci-cd.md`,
  `openwiki/architecture/gitops-flow.md`, `openwiki/architecture/secrets-and-identity.md`, `openwiki/architecture/storage-and-state.md`, `openwiki/workloads/inventory.md`,
  `openwiki/operations/validation-gates.md` and `openwiki/source-map.md`; preserve generated state.
- [x] T006 [P] [US1] Reconcile earlier authored documentation in `specs/004-tailnet-service-dns/`, `specs/005-retire-public-app-dns/` and `specs/20261115-185603-adguard-tailnet-dns/`; delete irrelevant dedicated enrollment packages under `specs/` without historical stubs and repair any affected `.agents/skills/` prose found by inventory.

## Phase 4: User Story 2 — Usable Current Documentation (P2)

**Goal**: Retained guidance is coherent, source-grounded and navigable.
**Independent acceptance**: Retained mixed-purpose paragraphs preserve independent security and operational facts, and all retained links resolve.

- [x] T007 [US2] Review all changed Markdown against owning source for coherent current guidance and independent credential, access, routing, storage, commit verification and webhook requirements, starting with `docs/secrets-aws-ssm.md` and `openwiki/architecture/secrets-and-identity.md`.
- [x] T008 [US2] Repair inbound references to every deleted file and changed heading throughout authored Markdown, starting with `openwiki/source-map.md` and `openwiki/runbooks/tailnet-ingress.md`, and run `scripts/ci/openwiki-check.py`.

## Phase 5: Cross-Cutting Verification

- [x] T009 Run all validation scenarios in `specs/20261118-045220-current-tailnet-docs/quickstart.md`: contextual whole-documentation search, existing wiki gate, affected Markdown lint, complete diff review and `git diff --check`; preserve exact outcomes and separate pre-existing findings.
- [x] T010 Confirm the complete diff changes only authored documentation and feature records, leave generated wiki state and runtime untouched, update actual completion markers in `specs/20261118-045220-current-tailnet-docs/tasks.md`, and hand exact validation evidence to the delivery owner.

## Dependencies and Execution Order

T001 → T002 → T003–T006 → T007 → T008 → T009 → T010. US2 follows the US1 edits so its cross-document review sees a coherent final set. Analysis must approve this list before implementation; convergence follows implementation as a separate stage.

## Parallel Opportunities

T003–T006 cover independent files and can be partitioned after T002. Example for US1: T003 authentication prose and T004 workload prose do not share files. The assigned worker remains the sole writer unless the coordinator explicitly assigns distinct scopes. US2 tasks are sequential because final link repair follows content review; no parallel task is claimed for that story.

## Implementation Strategy

Deliver US1 as the first coherent documentation increment, then review retained guidance and navigation for US2, then execute the complete validation guide. Keep all artifacts
about current documentation quality; avoid historical narratives. Report source discrepancies privately to the coordinator without introducing runtime changes. The full user
request requires both stories and final verification, even though US1 is the smallest independently reviewable increment.

## Phase 6: Convergence

- [x] T011 Align the CI credential-validation paragraph in `openwiki/operations/validation-gates.md` with the current authentication contract, preserve independent webhook and credential privacy requirements, and rerun the focused terminology, link and whitespace checks per FR-001, FR-002 and FR-004 (partial, HIGH).

- [x] T012 Keep only relevant rollout evidence in `specs/20261116-210437-uptime-kuma/delivery.md`, `specs/20261115-185603-adguard-tailnet-dns/checkpoints/validation.md` and `specs/20261115-185603-adguard-tailnet-dns/checkpoints/image-publication.md`, preserving independent checks and status facts per FR-002 and FR-004 (partial).

## Phase 7: Current Documentation Reconciliation

- [x] T013 Reconcile current AdGuard guidance in `clusters/homelab/apps/adguard/README.md`, `openwiki/workloads/inventory.md` and
  `specs/20261115-185603-adguard-tailnet-dns/` with the current ordinary device identity and administrator workflow. Preserve supported commands and independently useful
  acceptance checks; keep only current requirements and delete dedicated historical procedure notes. Resolve authored-document conflicts, repair links and rerun documentation checks.
