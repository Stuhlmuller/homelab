# DNS Retirement Checklist: Retire Public App Subdomain DNS

**Purpose**: Review the clarity and completeness of requirements for a guarded private-only DNS cutover
**Created**: 2026-10-18
**Feature**: [spec.md](../spec.md)

**Note**: This checklist evaluates the written requirements, not the implementation. It is intended for PR review before the DNS cutover.

## Requirement Completeness

- [x] CHK001 Are the exact private approval and public retirement sets, including their different treatment of the apex, specified? [Completeness, Spec §FR-001]
- [x] CHK002 Are the record types selected for removal and the preserved public record classes explicitly bounded? [Completeness, Spec §FR-002]
- [x] CHK003 Are requirements for ordinary tailnet DNS, HTTPS routes, and access restrictions stated before retirement? [Completeness, Spec §FR-003]
- [x] CHK004 Are required caller decisions, the live record baseline, and the prior cache lifetime documented as pre-deletion evidence? [Completeness, Spec §FR-004]
- [x] CHK005 Are requirements for future private app names and prevention of silent public republication stated? [Completeness, Spec §FR-008]

## Requirement Clarity

- [x] CHK006 Is the meaning of “approved app subdomain” precise enough to distinguish the 26 targets from four legacy endpoint names and the planned Mastodon name? [Clarity, Spec §FR-001]
- [x] CHK007 Is the Cordium wildcard owner distinguished from the concrete child used to judge its effective public and private answers? [Clarity, Spec §FR-001, §FR-006]
- [x] CHK008 Is the condition that blocks deletion for an unexpected selected-name record or a broader wildcard/CNAME answer source explicit? [Clarity, Spec §FR-005]
- [x] CHK009 Is “previous cache lifetime” tied to a recorded maximum and measured from the last deletion for post-cutover acceptance? [Clarity, Spec §FR-004, §SC-001; Plan §Design]

## Requirement Consistency

- [x] CHK010 Do public-record removal and continued private resolution use the same name inventory without treating the public apex as a deletion target? [Consistency, Spec §FR-001, §FR-007]
- [x] CHK011 Are the fail-closed promise and the explicit apex exception consistent across scenarios, requirements, and outcomes? [Consistency, Spec §FR-009, §SC-004]
- [x] CHK012 Do the preservation requirements permit existing public mail, certificate, legacy endpoint, and unrelated-name records while removing the selected app address records? [Consistency, Spec §FR-002, §FR-007]

## Acceptance Criteria Quality

- [x] CHK013 Can public absence be judged for every target record type, all 26 names, and a concrete wildcard child after the prior TTL? [Measurability, Spec §SC-001]
- [x] CHK014 Can continued private service be judged against the 27-name approval set and representative HTTPS restrictions? [Measurability, Spec §SC-002]
- [x] CHK015 Can preservation of apex and unrelated public records be compared against a pre-cutover baseline? [Measurability, Spec §SC-003]
- [x] CHK016 Does the specification define an objective pass criterion for public certificate validation capability, separate from currently usable HTTPS certificates? [Measurability, Spec §FR-007, §SC-003]

## Scenario and Edge Case Coverage

- [x] CHK017 Are already-absent target records, stale caches, off-tailnet callers, and later private app additions addressed? [Coverage, Spec §Edge Cases]
- [x] CHK018 Are changed baselines, partial deletion, and safe retry requirements defined without expanding deletion to other owners? [Coverage, Spec §FR-005]
- [x] CHK019 Are private-resolver failure, private-only recovery, and separately reviewed policy reversal requirements stated? [Coverage, Spec §FR-009, §FR-010]

## Dependencies and Assumptions

- [x] CHK020 Are the existing resolver, tailnet DNS setting, Traefik routes, and public zone dependencies stated for this cutover? [Assumption, Spec §Assumptions]
- [x] CHK021 Is the ordinary operating-system DNS client boundary stated so clients that bypass tailnet DNS are accounted for separately? [Assumption, Spec §Assumptions, §FR-004]

## Notes

- CHK016 passes because FR-007 and SC-003 require read-only Cloudflare delegation, ExternalSecret and ClusterIssuer readiness, unchanged DNS-01 references, and Ready Certificates. This is a readiness criterion, not a forced renewal.
