# Tasks: Centralize State Encryption

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md), [quickstart.md](quickstart.md)

**Prerequisites**: Custom requirements review passed 16/16; built-in checklist 16/16. Execute analysis in a separate turn before implementation.

**Tests**: Required explicitly by FR-007 and compatibility/enforcement acceptance. All work remains source-only; no live apply or state rewrite.

## Phase 1: Setup

- [x] T001 Record baseline root backend render, module policy/input inventory and runtime-key consumers in `specs/20261118-050111-centralize-state-encryption/checkpoint.md`; capture source revision and existing tool versions without reading live state.

## Phase 2: Foundation — Supported Generator

- [x] T002 Narrowly package official Terragrunt v1.2.2 release binaries in `flake.nix` for the existing four platforms using the established archive pattern, verify each artifact SHA256 against the published release checksum manifest before pinning its fixed Nix hash, preserve unchanged `flake.lock`/nixpkgs, and validate actual Nix-supplied binary version using `/workspace/cloud-tools/bin/nix` with approved escalation and no lock update/write. Avoid an unrelated Go 1.27.4 source-build toolchain upgrade.

**Checkpoint**: Supported generator available; source policy remains unchanged.

## Phase 3: User Story 1 — Preserve Encrypted Records (Priority P1)

**Goal**: Establish actual compatibility and fail-closed behavior before centralization.

**Independent Test**: The focused runtime regression creates old-policy encrypted state and saved plans, reads them with actual generated default-label policy using the compatible alias, checks reverse readability, and rejects wrong metadata/plaintext inputs without AWS access.

- [x] T003 [US1] Add `scripts/ci/state-encryption-test.py` using real Terragrunt/OpenTofu, temporary local backend and built-in terraform_data fixtures; capture old main-policy state and saved plan, exercise generated default-label policy with PBKDF2 metadata-preserving alias, read/show/apply old plan, and demonstrate missing/changed alias failures before asserting compatible success.
- [x] T004 [US1] Extend `scripts/ci/state-encryption-test.py` with new-to-old encrypted state and saved-plan readability plus plaintext state/plan rejection; assert fixtures are encrypted and all temporary data/credentials are public-safe and removed.

**Checkpoint**: Actual generator/format/metadata behavior proven offline. This does not prove AWS KMS permissions. Root-production configuration assertions follow in US2 after implementation.

## Phase 4: User Story 2 — Maintain One Shared Policy (Priority P2)

**Goal**: Centralize production policy and remove duplicates without altering resources/backends.

**Independent Test**: Generated production backend has exactly one compatible AWS KMS policy, both enforced targets, unchanged backend identity, and no duplicate module or retirement policy; genuine runtime inputs remain available.

- [x] T005 [US2] Add root-production generation and module-ownership assertions to `scripts/ci/state-encryption-test.py` and change retired-unit expectations in `scripts/ci/terragrunt-stack-test.py`; record expected failure against existing duplication/missing root map before source refactor.
- [x] T006 [US2] Atomically centralize encryption in `IaC/root.hcl` using existing key/region/spec, `encrypted_metadata_alias = "key_provider.aws_kms.main"` and `enforced = true`, remove its policy-only shared inputs, and remove duplicate encryption plus exclusive key variables in all eleven affected modules, including argocd-application-image-updater, under `IaC/terragrunt-catalog/modules/`; preserve resource-facing key inputs and the backend config map.
- [x] T007 [US2] Remove independent encryption synthesis from `scripts/ci/terragrunt-filter-base.sh`, retain root inheritance and unchanged retirement paths, and run `scripts/ci/terragrunt-stack-test.py` including actual generated-backend protection assertions.
- [x] T008 [US2] Remove stale policy-only input assumptions in affected module examples/tests/docs under `IaC/terragrunt-catalog/modules/`, verify remaining key-variable resource consumers, and run focused production generation/ownership/compatibility regressions in `scripts/ci/state-encryption-test.py` against the completed source change.

**Checkpoint**: Root, modules and retired-unit path migrate as one validated increment. Do not initialize or plan an intermediate duplicate policy configuration.

## Phase 5: Cross-Cutting Documentation and Validation

- [x] T009 Register focused encryption regression in `scripts/ci/offline-checks.sh` alongside the stack regression, consumed by the static/Nix check path, respecting current executable-test conventions and ensuring the supported pinned generator is used.
- [x] T010 Publish the coordinator-authorized source-authored `docs/state-encryption.md` and link it from `README.md`; explain single ownership, v1.2.2 requirement, metadata alias, preserved runtime/S3 boundaries, validation limits, plaintext fail-closed behavior and source rollback, including newly covered units after first ciphertext write. Preserve managed wiki/control artifacts because lifecycle tools/CLI are unavailable, and record that limitation without claiming a wiki update or live migration.
- [x] T011 Run the relevant commands from `specs/20261118-050111-centralize-state-encryption/quickstart.md`: Nix-pinned versions, HCL/Tofu formatting, focused encryption and stack regressions, stack generation, HCL validation, static checks and conftest policies; record revision-bound outcomes and exact unavailable checks in `checkpoint.md`, with no unrelated repeated testing after passing.
- [x] T012 Assess authenticated affected-unit planning through `scripts/ci/terragrunt-plan.sh` and its exclusions; run authorized read-only plans if prerequisites exist, otherwise record precise credential/exclusion blockers and owner/next action in `checkpoint.md`. Verify unchanged backend identities, resource inputs and `flake.lock`; run `git diff --check` and prepare bounded final evidence.

**Checkpoint**: Implementation stage ends with verified source scope and recorded limits. Run convergence in a separate turn; protected delivery remains coordinator-owned.

## Dependencies and Execution Order

T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009 → T010 → T011 → T012.

US1 precedes US2 because the generated metadata contract must be proven before removing module protection. Root/module changes in T006 are atomic and must precede retirement validation. T009/T010 require stabilized implementation; final checks follow all source/docs changes. A read-only source comparison may run alongside Nix builds, but no overlapping writers are permitted.

## Parallel Opportunities

No tasks carry [P]: this bounded change shares generator, root, tests and knowledge state, so the planned implementation is serial. Within US1, independent diagnostic inspection of OpenTofu metadata source can accompany a build; within US2, read-only review of runtime key consumers can accompany focused regression execution. These are optional inspections, not additional tasks or ownership transfers.

## Requirement Coverage

| Requirement | Tasks |
| --- | --- |
| FR-001 | T005–T008 |
| FR-002 | T003–T006, T008 |
| FR-003 | T004–T006, T008 |
| FR-004 | T005–T006, T008 |
| FR-005 | T001, T006, T008, T012 |
| FR-006 | T001, T005–T007, T012 |
| FR-007 | T002–T005, T007–T009, T011–T012 |
| FR-008 | T010, T012 |
| FR-009 | T005, T007 |

## Implementation Strategy

MVP evidence is US1's isolated compatibility/enforcement regression, after supported-generator setup. It is a validation milestone, not full delivery. Then complete US2's root/module/retirement refactor as one coherent production-policy increment, integrate CI/docs, validate, and perform separate convergence. Preserve completed task markers and evidence; route requirement/design gaps back to their owning stage instead of silently expanding implementation.

## Final-phase execution notes

T010: Implemented the coordinator-authorized source-authored alternative `docs/state-encryption.md` and README link because OpenWiki lifecycle tools/CLI are unavailable. Managed wiki and control artifacts were not edited; no lifecycle write is claimed. Owning plan/task amendments now reconcile this authorized path; the checkbox is complete after verifying both source artifacts and their required coverage. New docs cover exact pin/metadata identity, newly covered plaintext handling, validation limits and safe rollback distinctions.

T011: Required gates were invoked and their outcomes recorded. Formatting, stack generation, HCL validation, documentation checker and policy gate passed. Full static gate failed in existing Harbor publication tests on 10-second subprocess timeouts and subsequent existing-kubeconfig guard failures; no pass or baseline reproduction is claimed. This blocks broad local acceptance pending established CI evidence or owning fixture investigation.

T012: Authenticated planning unavailable here: default kubeconfig absent and ARM/OIDC credential variables absent. AWS_PROFILE exists but that does not prove usable KMS/backend credentials. No live state was fetched, no cloud mutation or apply occurred. Existing protected/secret/operator planning exclusions remain explicit.


## Phase 6: Convergence

Delivery finding F1: the coordinator's integration inspection found that current main moved module Terraform declarations into `versions.tf` and separated variables/outputs while this migration removed policy from the former locations. The encryption-removal outcome remains unchanged; reconcile the moved declarations without undoing the upstream module layout, resources, outputs or new READMEs.

- [x] T013 Reconcile the encryption migration with the current upstream layout in `IaC/terragrunt-catalog/modules/argocd-application-kubernetes/`, `azuread-family-user/`, `entra-emergency-global-admin/`, `entra-owner-mail/`, `entra-verified-family-user/` and `kubernetes-node-labels/`; preserve upstream resources, outputs, versions and READMEs, remove policy-only encryption blocks/variables from their new locations, and verify all eleven migrated modules still inherit only `IaC/root.hcl` encryption without changing genuine resource-facing KMS inputs or backend identities per FR-001, FR-004, FR-005, FR-006 and SC-002 (partial).
- [x] T014 After T013, validate the reconciled source with the pinned Nix Terragrunt/OpenTofu formatting checks, `scripts/ci/state-encryption-test.py`, `scripts/ci/terragrunt-stack-test.py` and the affected `scripts/ci/argocd-image-updater-provider-test.py` scenarios; check generated backend metadata/enforcement, moved-variable cleanup, module layout/resource preservation and relevant documentation links, then record exact results and remaining execution limits in `specs/20261118-050111-centralize-state-encryption/checkpoint.md` per FR-002, FR-003, FR-006, FR-007 and FR-009 (partial). Do not repeat the unchanged Harbor broad gate without new evidence justifying it; a separate independent convergence turn must assess the completed repair before protected delivery resumes.

Dependency: T013 → T014 → separate independent convergence. Existing task completion markers and historical validation limits remain unchanged.
