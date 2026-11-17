# Requirements-quality review

Date: 2026-11-15. Reviewer: current goal coordinator in a separate review turn,
under the track-homelab-changes workflow's explicit review stage. This review
assesses requirement quality only; it is not a PR approval or runtime acceptance.

Result: **22 PASS / 2 OPEN**. Task generation waits for a narrow plan amendment
and a follow-up review. No additional user decision is required for these routine
consistency corrections. Spec, plan and source code were not changed in this turn.

## Findings

### R1 — Acceptance freshness is not sufficiently defined (CHK015, medium)

Plan §Delivery sequence says “freshness immediately before applying” and contract
requires “fresh acceptance”, but neither defines the allowed receipt age, clock
handling or what is rerun. An implementer could accept an hours-old receipt while
rechecking only IP equality. The data model invalidates changed source/config/
identity but does not bound unchanged-yet-old observations.

Owning stage: plan. Define the exact fresh-check sequence, receipt age and binding
requirements, plan-file identity and invalidation conditions. Include a negative
acceptance case for stale/future-dated evidence. Prefer rerunning required checks
in the same invocation and binding their result to the exact saved-plan digest,
source/config revisions and current Service/peer identity. No new user policy
choice is necessary: this makes FR-008/013 executable rather than expanding scope.

### R2 — Rollback could depend on the failed resolver (CHK017, high)

Plan §Rollback requires restoring prior DNS after an outage, but contract says
rollback uses “equivalent plan guards” while the apply path requires fresh
AdGuard endpoint/DNS success. Quickstart supplies no explicit rollback mode or
separate failure-tolerant validation. Implementing the same mandatory healthy
AdGuard preflight for rollback would prevent recovery during the very outage
US4 describes.

Owning stage: plan. Define an explicit rollback path that validates reviewed
source, the captured prior policy, current live policy, exact saved-plan changes
and administrator identity, without requiring the unavailable AdGuard endpoint
or admin UI to pass. Retain unrelated-policy drift protection and storage/secret
preservation. Specify a concrete regression case: restore previous DNS while
AdGuard is unreachable. Normal cutover must still require healthy AdGuard.

## Item evidence

| Item | Result | Written evidence |
| --- | --- | --- |
| CHK001 | PASS | Spec US1/US2/US3 distinguish server, client policy and admin access |
| CHK002 | PASS | FR-002/004/010 and contract DNS name types and both transports |
| CHK003 | PASS | FR-005/006; contract auth, setup closure and no Funnel |
| CHK004 | PASS | FR-007/017; plan differentiates Git/SSM durable settings and replaceable cache |
| CHK005 | PASS | Spec permits configured blocking result; plan/contract select null-IP consistently |
| CHK006 | PASS | Clarifications and FR-002/010 separate record type, transport and MagicDNS |
| CHK007 | PASS | FR-007 and plan explicitly exclude durable undocumented UI edits |
| CHK008 | PASS | FR-011 prohibits silent fallback; plan names deliberate restoration of prior policy |
| CHK009 | PASS | SC-001/002 and contract specify counts, deadline and cache-controlled client checks |
| CHK010 | PASS | FR-014 requires real system resolver and records client metadata |
| CHK011 | PASS | FR-012 conditional coverage; plan/quickstart version >=1.88.1 and unverified reporting |
| CHK012 | PASS | FR-019/SC-006 require deployed revision and actual functional evidence |
| CHK013 | PASS | FR-003 plus contract nonempty enabled list before cutover and last-good retention |
| CHK014 | PASS | FR-004/010 and contract explicitly prohibit private public fallback/loops |
| CHK015 | OPEN | R1: freshness and exact evidence binding need an executable definition |
| CHK016 | PASS | Contract requires inspecting actual policy/state before retry after uncertainty |
| CHK017 | OPEN | R2: outage rollback is intended but its helper guards are contradictory/underspecified |
| CHK018 | PASS | Plan requires one validated bcrypt user, protected source and explicit revision/rollout |
| CHK019 | PASS | FR-016 and plan disable logs/statistics; receipts exclude credentials/history |
| CHK020 | PASS | Plan explicitly says Flannel NetworkPolicy is unenforced; external trust/auth boundary named |
| CHK021 | PASS | Plan keeps existing trusted signer/admin host and rejects broader Codex/CI authority |
| CHK022 | PASS | Plan constitution table distinguishes design from runtime checks; delivery sequence gates prerequisites |
| CHK023 | PASS | Spec edge cases/assumptions exclude bypass, off-tailnet enforcement and universal ad removal |
| CHK024 | PASS | SC-005/006 and guide separate fixture/source, publication, runtime, client and restore evidence |

## Validation and next action

Custom checklist markers match this table: CHK015/017 unchecked, all other items
checked. All 24 IDs retained. Built-in requirements checklist unchanged at 16/16;
this custom design review does not silently alter its historical evaluation.

Next separate goal turn: narrow speckit-plan amendment for R1/R2 across plan,
contract, data model and quickstart; preserve specification intent and completed
work. Then a separate re-review of affected items, then tasks and read-only
analysis. No implementation, live mutation, merge or deployment occurred.
The previous full-spec Notion rejection remains respected; no full copy retried.
