# Operations Requirements Checklist: Run Renovate in the Homelab

**Purpose**: Review the quality of requirements for hourly discovery, persistent caching, credentials, and safe cutover before task generation.
**Created**: 2026-10-18
**Feature**: [spec.md](../spec.md)
**Audience**: PR reviewer; standard planning gate.

## Requirement Completeness

- [x] CHK001 Are eligibility rules specified for owned public and private repositories, forks, archived repositories, and repositories inaccessible to the App? [Completeness, Spec §FR-001, Spec §FR-012]
- [x] CHK002 Does the spec define the required outcome when the App cannot access an otherwise eligible owned repository? [Gap, Spec §FR-001, Spec §FR-007]
- [x] CHK003 Is the relationship between the shared policy and repository-specific settings defined consistently for configured and config-free repositories? [Consistency, Spec §FR-002, Spec §FR-013]
- [x] CHK004 Are credentials for private package sources explicitly included or excluded from the migration scope? [Gap, Spec §FR-007]
- [x] CHK005 Are cache-data classes and their retention, protection, and rebuild requirements distinguished from durable repository state? [Completeness, Spec §FR-005, Spec §FR-006]
- [x] CHK006 Are rollback requirements complete for both the cluster schedule and the legacy workflow after a partial cutover? [Coverage, Spec §FR-009, Spec §FR-011]

## Requirement Clarity

- [x] CHK007 Is the hourly schedule precise about its clock boundary, late starts, and missed cycles? [Clarity, Spec §FR-001, Spec §SC-001]
- [x] CHK008 Are an eligible update and an explicit deferral defined well enough to classify outcomes consistently? [Ambiguity, Spec §FR-003, Spec §SC-002]
- [x] CHK009 Are valid, expired, and stale cache entries defined with a maximum acceptable age or a stated upstream freshness rule? [Ambiguity, Spec §FR-005]
- [x] CHK010 Is use of cached data during upstream outages bounded so it cannot conceal newly available versions indefinitely? [Clarity, Spec §Edge Cases, Spec §FR-005]
- [x] CHK011 Does the spec define the minimum actionable failure detail while protecting private repository and package information? [Clarity, Spec §FR-008]
- [x] CHK012 Are the criteria for equivalent proposal behavior explicit, including App author, existing PR continuity, and effective merge policy? [Clarity, Spec §FR-009, Spec §SC-005]

## Requirement Consistency

- [x] CHK013 Are proposal creation and allowed auto-merge described consistently across User Story 1, FR-003, and SC-005? [Consistency, Spec §User Story 1, Spec §FR-003, Spec §SC-005]
- [x] CHK014 Is the all-owned-repositories scope reconciled with the plan's archived and inaccessible exclusions? [Conflict, Spec §FR-001, Plan §Technical Context]
- [x] CHK015 Are repository policy precedence and the preserved global auto-merge policy consistent across spec, plan, and runner contract? [Consistency, Spec §FR-002, Spec §FR-003]
- [x] CHK016 Is the one-writer cutover order specified, including legacy workflow deletion and run drainage, guarded Actions-key retirement before cluster writes, cluster-first rollback, conditional GitHub-hosted Harbor proof before guarded legacy restore, and the allowed no-writer gap? [Consistency, Spec §FR-009, Plan §Design]
- [x] CHK017 Are cache recovery and rollback requirements consistent with the prohibition on ad hoc live mutation? [Consistency, Spec §FR-006, Spec §FR-011, Constitution §I]

## Acceptance Criteria Quality

- [x] CHK018 Is the seven-day healthy-period denominator and the treatment of outages defined for the 95% on-time target? [Measurability, Spec §SC-001]
- [x] CHK019 Are preregistered sampling, upstream visibility bounds, and proposal/deferral timestamps defined for the four-hour latency target? [Measurability, Spec §SC-002]
- [x] CHK020 Is cache reuse objectively distinguishable from a warm run that merely encounters no changed dependencies? [Measurability, Spec §SC-003]
- [x] CHK021 Do failure-visibility criteria also cover a missed cycle that creates no failed run? [Gap, Spec §FR-008, Spec §SC-004]
- [x] CHK022 Is the acceptance criterion for a newly owned repository scoped to App-accessible repositories, with a defined result for access gaps? [Ambiguity, Spec §SC-006]

## Scenario and Edge Case Coverage

- [x] CHK023 Are partial repository failures, GitHub rate limits, and upstream package-source failures assigned distinct outcomes and retry expectations? [Coverage, Spec §Edge Cases, Spec §FR-008]
- [x] CHK024 Are both corrupt cache entries and an unavailable or full cache volume covered by recovery requirements? [Coverage, Spec §FR-006]
- [x] CHK025 Are token minting failure, credential rotation, and a token expiring before a long scan completes covered by requirements? [Coverage, Spec §FR-007, Plan §Technical Context]
- [x] CHK026 Are owner changes and scheduled overlap during a running discovery cycle addressed without duplicate proposals? [Coverage, Spec §FR-004, Spec §FR-012]
- [x] CHK027 Is the recovery path defined when the companion workflow change cannot be completed before the next legacy schedule? [Gap, Spec §FR-009, Plan §Design]

## Non-Functional Requirements

- [x] CHK028 Are confidentiality requirements specified for mounted credentials, private cache contents, logs, and public planning artifacts? [Security, Spec §FR-007, Spec §FR-008, Constitution §II]
- [x] CHK029 Is the runner's required GitHub and cluster permission scope stated in terms a reviewer can evaluate? [Security, Spec §FR-007, Spec §FR-010]
- [x] CHK030 Are run duration, token lifetime, and non-overlap requirements compatible under a slow full-owner scan? [Reliability, Spec §FR-001, Spec §FR-004, Plan §Technical Context]

## Dependencies and Assumptions

- [x] CHK031 Is the assumption that the existing App covers every eligible owned repository explicitly validated before cutover? [Assumption, Spec §FR-001, Spec §FR-009]
- [x] CHK032 Is ownership of the companion Stuhlmuller/renovate workflow change and its ordering with the homelab change documented? [Dependency, Spec §FR-009, Plan §Delivery Order and Gates]
- [x] CHK033 Are the storage, secret source, image publication, and GitOps prerequisites stated without requiring undeclared manual changes? [Dependency, Spec §Assumptions, Constitution §I, Constitution §V]
- [x] CHK034 Is the order of credential transfer, Secret projection, transfer-grant retirement, and the first scheduled Job specified so placeholders cannot be consumed? [Dependency, Spec §FR-007, Plan §Delivery Order and Gates]
- [x] CHK035 Does the one-writer cutover requirement cover both scheduled and manually dispatched legacy workflow runs? [Consistency, Spec §FR-009, Plan §Delivery Order and Gates]

## Notes

- Checked items have direct requirements or design evidence in the current spec, plan, contract, quickstart, or constitution. This review does not claim runtime behavior is implemented.
- CHK014 is checked: the spec, plan, and runner contract now skip archived repositories and treat missing App access to a non-archived owned repository as a cutover-blocking coverage gap.
- CHK029 is checked: the runner contract lists Renovate's required GitHub App permissions and excludes a Pod Kubernetes API credential; the plan requires comparing actual App grants before cutover.
- CHK019 follows the revised conservative upstream visibility bracket and preregistered sample; the spec does not claim an exact upstream publication timestamp.
- CHK034 and CHK035 cover the post-analysis Secret readiness sequence and retirement of the legacy manual trigger.
- CHK016 reflects the revised cutover order: dry-run parity, complete legacy workflow deletion, no requested, pending, queued, waiting, or in-progress legacy run, then cluster writes.
