# Deployment requirements review

Reviewed 2026-11-16 in a separate delegated review turn. Scope: requirements
quality, completeness and cross-artifact consistency; no source implementation
or live validation. Result: **23 PASS / 1 OPEN**.

Read the current AGENTS.md, spec.md, plan.md, research.md, data-model.md,
contracts/native-api.md, quickstart.md and deployment.md. Existing Bazarr local
storage source supports the declared retained hostPath pattern. Cached pinned
Kuma server source confirms `needSetup` and `setup` request handlers; the native
bootstrap contract is not based solely on the unsolicited `setup` event.

## Required correction

**R1 / CHK009 — align the source-freshness threshold (plan stage).**

Spec FR-004 defines stale telemetry as older than two expected observation
periods. Plan “Monitor catalog and coverage” instead permits source age up to
120 seconds, or two scrape periods only when longer. For a 15-second scrape,
the spec permits 30 seconds but the plan permits 120. Thus a stale source could
be classified healthy under the plan while violating the contract.

Use two actual source observation periods consistently, with only the explicit
scheduled-work exception already allowed by the spec. Record a negative test
for a sub-60-second source period so a fixed 120-second allowance cannot recur.
No new user decision or broader research is needed. Re-review CHK009 after the
narrow plan correction; task generation should consume reconciled artifacts.

## Passing evidence

| Items | Evidence and assessment |
| --- | --- |
| CHK001–005 | Spec FR-001/008 and bootstrap clarification; plan Bootstrap/Network/Delivery; native
  contract. Init binds loopback, closes setup before main, waits for graceful server exit, preserves
  existing config/account and fails login without reset. Generated SSM reference, mounted
  credentials, exact consumer scope within app Pod, no logged tokens, private ingress, image-first
  publication and exact-revision delivery are explicit. |
| CHK006–008 | Spec FR-002/004; plan Monitor catalog; data-model Catalog. Source/live union, lifecycle dispositions, configuration-only ownership and partial suspension are defined. Shared checks require actual health meaning. Missing/stale data, zero desired replicas, 401/redirect and query timestamps cannot alone prove target health. The numeric freshness inconsistency is isolated in CHK009. |
| CHK010–011 | Spec FR-010/011/012 and edge cases; data-model Catalog; plan Monitor catalog. Missing coverage fails validation; active support components of stopped apps remain covered; existing outages remain visible and unrelated repairs/external monitoring remain out of scope. |
| CHK012–014 | Data-model Runtime identity; native contract. Stable description markers, duplicates rejected before writes, full-record merge, owned-field projection, unchanged-write suppression, uncertain-add reread, sequential writes, retirement pause and unowned-record preservation are explicit. |
| CHK015 | Data-model Status and plan Bootstrap. Last-success timestamp/catalog hash survive failure, current failed attempt has an error category, and initial readiness requires successful reconciliation. Logs/status expose errors without declaring cached success current. |
| CHK016–017 | Plan Storage/Backup and data-model Backup manifest. Single-writer retained local SQLite, NFS-only backups, online SQLite API, integrity check, atomic checked publication, explicit ancillary inclusion, secret exclusion, retention and failure behavior are specified. HostPath non-quota and non-offsite limits are explicit. |
| CHK018–019 | Spec SC-005; plan Backup; native contract; quickstart. Restore uses isolated emptyDir and loopback with egress denied, checks native login and historical observations, and does not write production state. Schema-compatible image/snapshot rollback, writer fencing and retained PVCs distinguish recovery from a Git revert. |
| CHK020–021 | Spec SC-001/002/007; plan Delivery; quickstart. Source gates, complete image pull/publication, exact deployed revision, private login and unauthenticated denial, complete catalog coverage and three observations are separate measurable milestones. Failed targets are reported honestly. |
| CHK022–023 | Spec SC-003/004; native acceptance interface; quickstart. Disposable localhost test transitions within 180 seconds and ends paused; existing apps are untouched. Two reconciliations require stable IDs/zero second-pass changes; declared GitOps replacement must retain earlier observations. |
| CHK024 | Plan final paragraph, research introduction and quickstart introduction label future commands and unperformed runtime checks explicitly. Requirements-quality passes are not runtime claims. |

## Implementation verification retained

Actual pinned-image rootless startup, graceful shutdown, Socket.IO behavior,
WAL backup on the declared read-only mount, target-specific PromQL/JSONata,
least-privilege network rules, secret bootstrap, publication, rollout and usable
restore remain implementation tests. These are already required by plan and
quickstart; passing this checklist does not waive them or invent another human
approval round.

## R1 re-review

Separate re-review on 2026-11-16: **R1 resolved; CHK009 PASS**. Current result is
**24 PASS / 0 OPEN**; the initial finding above is retained as review history.

Plan Monitor catalog now requires source age no greater than twice each actual
configured source period, explicitly rejects the fixed 120-second allowance and
Kuma polling cadence as substitutes, and preserves only documented scheduled
exceptions. Research and data-model sections agree and require source-cadence
evidence. Quickstart requires the boundary test: with a 15-second scrape, age
30 seconds is eligible and age 31 seconds fails. This satisfies FR-004 without
changing the specification. The test is specified, not claimed executed.

Only deployment.md and this review record were updated during re-review.
