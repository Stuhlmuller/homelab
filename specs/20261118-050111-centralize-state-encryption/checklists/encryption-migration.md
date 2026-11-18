# Encryption Migration Requirements Checklist

**Purpose**: Review completeness, consistency and measurability of encryption migration requirements before task generation.

**Created**: 2026-11-17

**Feature**: [Specification](../spec.md), [plan](../plan.md)

**Audience/Timing**: PR reviewer, pre-implementation design gate; standard depth focused on state safety and ownership.

## Requirement Completeness

- [x] CHK001 Are both existing state and saved-plan readability explicitly required, without key rotation or record rewriting? [Completeness, Spec §FR-002]
- [x] CHK002 Is mandatory protection specified separately for state and saved plans, with plaintext fallback excluded? [Completeness, Spec §FR-003]
- [x] CHK003 Are all root-including units and retired-unit deletion paths included in shared policy ownership? [Coverage, Spec §FR-001, §FR-009]
- [x] CHK004 Are removals limited to duplicate policy and policy-only inputs, while resource-facing key inputs remain protected? [Completeness, Spec §FR-004, §FR-005]

## Requirement Clarity

- [x] CHK005 Is persisted metadata identity distinguished from key identity and generated block labels? [Clarity, Spec §FR-002, §Clarifications]
- [x] CHK006 Are backend locations, locking, bucket encryption, runtime keys and resource identities explicitly invariant? [Clarity, Spec §FR-006]
- [x] CHK007 Is the boundary between offline compatibility evidence and authenticated key-access evidence clearly stated? [Clarity, Spec §FR-007, Plan §Verification and Rollback]

## Requirement Consistency

- [x] CHK008 Does the design preserve both-target enforcement without contradicting shared-policy-only ownership? [Consistency, Spec §FR-001, §FR-003, Plan §Design]
- [x] CHK009 Are tool-version dependencies and narrow package provenance requirements consistent with the unchanged lock/input constraint? [Consistency, Plan §Technical Context, §Design]
- [x] CHK010 Are normal and retired-unit paths assigned the same compatibility and enforcement requirements? [Consistency, Spec §FR-002, §FR-003, §FR-009]

## Acceptance Criteria Quality

- [x] CHK011 Are compatibility outcomes measurable through old/new encrypted state and saved-plan evidence rather than policy text alone? [Measurability, Spec §SC-003, Plan §Design]
- [x] CHK012 Are completeness criteria quantified for shared ownership and removal of duplicated policy? [Measurability, Spec §SC-001, §SC-002]
- [x] CHK013 Is failure behavior defined for incompatible metadata and plaintext records? [Coverage, Spec §User Story 1, §Edge Cases, Plan §Design]

## Dependencies and Recovery

- [x] CHK014 Are supported release provenance, reproducible artifact hashes and supported-platform preservation documented as tool-upgrade constraints? [Dependency, Plan §Design]
- [x] CHK015 Are unavailable credentials and authenticated-plan exclusions documented without implying unsupported live verification? [Assumption, Spec §FR-007, Plan §Verification and Rollback]
- [x] CHK016 Are source rollback, unchanged persisted records and separation from live state restoration described consistently? [Recovery, Spec §FR-008, Plan §Verification and Rollback]

## Notes

All items were generated unchecked and evaluated in a separate explicit review turn. This checklist evaluates requirement quality, not implementation correctness. Passing this review does not claim any implementation or live test passed.

## Review Evidence

| Items | Evidence and disposition |
| --- | --- |
| CHK001–CHK002 | Spec Story 1 and FR-002/003 explicitly preserve existing state/saved plans without rotation or rewriting, and enforce both targets without plaintext fallback. Complete. |
| CHK003–CHK004 | FR-001/004/005/009 and Clarifications include root users plus retirement and distinguish resource inputs. Plan Design 3/4 names the real runtime-key consumers and retirement generator. Complete. |
| CHK005–CHK007 | FR-002 explicitly names persisted metadata identity; Clarifications distinguish generated names. FR-006 lists invariants. Plan Verification states that PBKDF2 cannot establish AWS access. Clear. |
| CHK008–CHK010 | Plan Design 1 centralizes enforced=true; Design 4 removes retirement duplication. Design 2 requires narrow released v1.2.2 package, verified hashes, unchanged flake.lock and all four systems. Consistent with inspected generator/version evidence in research. |
| CHK011–CHK013 | SC-001/002 quantify complete ownership/removal. SC-003 and Plan Design 5 demand actual old/new state and saved-plan round trips with metadata-dependent analogue and negative missing-alias/plaintext failures. Measurable and bounded. |
| CHK014–CHK016 | Plan Design 2 records release, reproducible hashes and four systems; quickstart records authenticated planning exclusions and missing credentials; Verification and quickstart distinguish source rollback from state restoration. Complete. |

Reviewed against spec.md, plan.md, research.md and data-model.md, with prior source evidence independently grounded in Terragrunt v1.2.2 generation, OpenTofu v1.11.1 metadata lookup/address encoding, locked nixpkgs package, module resource consumers and retired-unit generation. No requirement gap or conflict found; no artifact corrections needed.
