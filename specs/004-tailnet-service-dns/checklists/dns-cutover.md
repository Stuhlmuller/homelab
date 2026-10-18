# DNS Requirements Checklist: Private Tailnet Service DNS

**Purpose**: Assess DNS publication, trust, and cutover requirements before implementation review
**Created**: 2026-10-18
**Feature**: [spec.md](../spec.md)
**Depth**: Standard PR review

## Requirement Completeness

- [x] CHK001 Are all 27 migration names, the apex, the Cordium base name, and the wildcard included in the required private-answer scope? [Completeness, Spec §FR-001]
- [x] CHK002 Is the approval boundary defined so ordinary services, catalog-only declarations, retired names, and public-only routes cannot publish private answers? [Completeness, Spec §FR-004]
- [x] CHK003 Are requirements stated for preserving existing HTTPS URLs, certificates, routing, authentication, and route restrictions? [Completeness, Spec §FR-002]
- [x] CHK004 Are unrelated public names under the same zone and non-address apex records explicitly protected? [Completeness, Spec §FR-005; Contract §Wire contract]
- [x] CHK005 Are both private DNS reachability and existing tailnet device trust requirements covered before the owner handoff? [Completeness, Spec §FR-012; Spec §SC-007]
- [x] CHK006 Is the 27-name inventory distinguished from the continuing approval source for future names? [Completeness, Spec §FR-004; Plan §Design 1]

## Requirement Clarity

- [x] CHK007 Is it unambiguous that the reviewed route and approval declaration are one exposure change, while DNS records update automatically without a separate record edit? [Ambiguity, Spec §FR-003; Plan §Design 1; Contract §Reviewed Kubernetes input]
- [x] CHK008 Is wildcard matching bounded to one Cordium label, with the apex and Cordium base name declared separately? [Clarity, Contract §Wire contract; Plan §Technical Context]
- [x] CHK009 Is fail-closed defined as no usable public application address rather than requiring a particular DNS error code? [Clarity, Spec §FR-006; Contract §Wire contract]
- [x] CHK010 Is an ordinary tailnet client defined for acceptance, including the boundary for clients that bypass configured DNS? [Clarity, Spec §Assumptions]
- [x] CHK011 Are the resolver address, restricted suffix, and handoff actor identified without treating a direct query as proof of normal client DNS use? [Clarity, Spec §FR-009; Contract §Handoff boundary]

## Requirement Consistency

- [x] CHK012 Do removal criteria distinguish the private authoritative answer disappearing from any public fallback before retirement? [Ambiguity, Spec §SC-002; Contract §Reviewed Kubernetes input]
- [x] CHK013 Is public-record restoration excluded from ordinary resolver-outage recovery, consistent with the owner's fail-closed decision? [Conflict, Spec §FR-006; Contract §Recovery and rollback]
- [x] CHK014 Are the private DNS and existing HTTP authorization responsibilities kept distinct across the spec and plan? [Consistency, Spec §FR-002; Plan §Summary]
- [x] CHK015 Are public-only names and non-address record types preserved consistently across the answer and retirement requirements? [Consistency, Spec §FR-005; Contract §Wire contract; Contract §Retirement preconditions]

## Acceptance Criteria Quality

- [x] CHK016 Can the 27-name private-answer outcome be measured through normal client DNS and representative HTTPS access? [Measurability, Spec §SC-001]
- [x] CHK017 Is the publication convergence target quantified and paired with a criterion for unapproved names? [Measurability, Spec §SC-002]
- [x] CHK018 Is public retirement measurable after the prior cache lifetime for A, AAAA, and CNAME, including a concrete wildcard match and unrelated public names? [Measurability, Spec §SC-003]
- [x] CHK019 Are outage acceptance and recovery targets stated separately from the healthy-path answer checks? [Measurability, Spec §SC-004; Spec §SC-006]
- [x] CHK020 Is the on-demand resolver check specified with a clear invocation context, expected success and failure signals, and a declared recovery boundary? [Clarity, Spec §FR-010; Spec §SC-006]

## Scenario and Edge Case Coverage

- [x] CHK021 Are baseline drift, missing private answers, stale public caches, and off-tailnet apex or Cordium callers addressed as cutover blockers? [Coverage, Spec §Edge Cases]
- [x] CHK022 Are partial public-record retirement and safe resumption requirements documented? [Coverage, Contract §Retirement preconditions]
- [x] CHK023 Are native clients, node image pulls, Fleet restrictions, and public callback paths included in pre-retirement acceptance? [Coverage, Spec §FR-011; Contract §Retirement preconditions]
- [x] CHK024 Are private-name removal and unapproved-name handling defined without silently routing another app into the removed name? [Coverage, Spec §Edge Cases; Spec §FR-004]
- [x] CHK025 Are IPv4-only private targets and approved-name AAAA behavior defined so public IPv6 answers cannot leak into private resolution? [Coverage, Contract §Wire contract]

## Dependencies and Assumptions

- [x] CHK026 Is the owner's tailnet DNS setting a distinct gate before public retirement, with exit-node behavior called out where relevant? [Dependency, Contract §Handoff boundary]
- [x] CHK027 Are the live public baseline, prior TTL, exact retirement target set, and off-tailnet impact decision required before deletion? [Dependency, Contract §Retirement preconditions]
- [x] CHK028 Are tailnet access policy and Tailnet Lock trust documented as prerequisites to offering the DNS endpoint? [Dependency, Spec §FR-012; Plan §Design 3]
- [x] CHK029 Is the rollback source and preservation of unrelated public names/types specified? [Dependency, Contract §Recovery and rollback; Data Model §Public record and cutover evidence]

## Notes

Unchecked items identify wording or policy gaps in the requirements. They are not implementation test failures.
