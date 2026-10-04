# HOME-57 fixed-proposal integration and finite acceptance gaps

**HOLD merge and activation. Repository preparation only.** Integration inputs:

| Input | Exact revision |
| --- | --- |
| SRE custody / #1163 | `afa40cb31f8a8ebb0c2093b00b39394ae0726936` |
| QA oracle and capability fixes / #1172 | `a458b0381b87bd62d782256025a119db7c61de67` |
| Recovery hook-safe stop/readback / #1173 | `1acbe6c9750ef57bb2cb3f59e20d26037173dbc9` |
| Current main, inspected 2026-10-04 UTC | `ee07c79754b10e2a708f45ba50f556102261b4ba` |

All inputs are preserved in ancestry. QA and Recovery behavior and artifacts are retained. Integration fixes inherited
executable modes/lint, binds callback loop values explicitly, and adds the
stop-plan regression suite to the shared static runner. Main contributes Wazuh storage-headroom fixes (#1169)
and the isolated Entra pilot (#1170); both main's and Harbor's CI/KB changes are
retained. Main's Entra work does not establish Harbor or AWS operator identities.

HOME-64 decision `4de27d35-d00d-49dd-9e7e-a9392ad04491` accepts the **direction for
preparation only**, not this integration, authority, risk or execution. HOME-62's
system-issuer rejection remains binding. Workflow `if: false`, unconditional
issuer-helper refusal and all execution/acceptance flags remain unchanged.
Offline planners are not executable recovery/provisioning adapters. No new
execution path is added by integration.

## Delivered source, with evidence limits

- [QA's fixed fixture](harbor-authorization-fixture.md) uses operation-specific
  postconditions and unrelated-state checks; timestamp-only mutations fail its
  regression. [Issuer capability preparation](harbor-issuer-capability-proposal.md)
  describes 54 unexecuted direct-API/session cases. Offline models do not prove
  Harbor authorization or session termination.
- [Custody and reader boundaries](harbor-credential-custody.md) exclude the
  collector parameter from shared module grants, propose a namespaced store and
  exact reader policy, and inventory declaration-level reader/writer exposure.
  They do not prove effective IAM, namespace/controller isolation or sole-writer
  exclusion. SSM has no compare-and-swap; ESO can consume a racing write.
- [Recovery's stop/readback addendum](harbor-hook-safe-stop-and-readback.md)
  models automation pause, exact resource-selective sync and retained pause,
  plus independent readback after interruption/unknown outcomes. Its source
  tests exclude bootstrap/backup hooks from the proposed selection. Existing
  operations, scheduled Jobs, controller behavior and competing writers remain
  separate runtime gates. Never apply the full zero-replica overlay.
- [TLS render implementation](harbor-tls-and-recovery-integration.md) checks
  actual chart configuration and synthetic TLS identities. Python TLS tests
  are not running Envoy/NGINX, CA reload or Harbor evidence. No independent
  all-hop acceptance is implied by integration.

## R1/R5 follow-up

The [materialization/alert proposal](harbor-tls-materialization-and-alerts.md)
delivers public chart overrides, unregistered CA-only generators, client/port
patches, phased reload annotations and metadata-only expiry rules/checks.
HOME-66 owns missing identities, environment records and trusted signing; dependent
R2/R3/R4 stay parked. No speculative execution adapter is added.
Independent source closures apply only to reviewed `afa40cb3`, `a458b038` and
`1acbe6c9`; they do not approve integration `8c666d4b` or this follow-up.
QA #1174 `3569689be77196e3cf0b90af4d96d46d323ad6d4` is separate and not integrated.

## Finite blocker table

These are completion criteria, not requests to execute. Rows distinguish work
that can be prepared in the repository from unavailable inputs and approvals.
Do not create another speculative adapter to hide a missing prerequisite.

| ID / class | Remaining item and accountable domain | Concrete completion evidence / dependency |
| --- | --- | --- |
| R1 — repository deliverable | SRE: TLS GitOps materialization, public trust distribution/rotation, client and port migration | Input-independent materialization, client/port inventory and phased reload deltas now delivered. Remaining: HOME-66 approved public trust/issuer custody, exact signed source revisions and client restart/overlap records; independent review and actual proxy/client proof E1. |
| R2 — repository deliverable | QA: disposable environment provision/checkpoint/teardown and execution adapter | Exact immutable revisions, pinned images/resources, no production routes/data, credential isolation, sentinel-hook controls, reliable cleanup and bounded lifetime. Connect corrected authorization/session/expiry/scan-summary cases to a real pinned topology. Depends on I1/I2; no fixture run now. |
| R3 — repository deliverable, input-blocked | SRE/Recovery: private capture/transfer/publication and protected recovery adapter | Signed repository-owned procedure using an actually supported operator identity/custody mechanism; exact ID/intent/version checks, unknown-response handling, no general-runner management credential, independent reconciliation/termination. Cannot implement an accepted adapter before I1/A1; planners remain disabled. |
| R4 — repository deliverable | Recovery: exact pause/selective-stop/separate-resume plans | Immutable Terragrunt/Argo revisions and source positions; exporter-only resource selection, prune/retry exclusions, verified idle automation and hook exclusion; separately reviewed resume. Source model exists; concrete environment-specific artifacts require I2 and runtime sentinel proof E1. |
| R5 — repository deliverable | SRE/Recovery: expiry/notification and operational acceptance checks | Disabled expiry-only sidecar, ESO metadata projection, four alert rules and nine PromQL acceptance cases delivered. Remaining: HOME-66 named staffed owner/observer and approved deadlines; actual route receipt, server-expiry/version, client and backup/retrieval records E1. No silent interruption or HTTP/admin rollback. |
| I1 — unavailable identities/custody | SRE/security: named person-bound Harbor and AWS identities, independent observer/termination verifier, approved isolated workstation | Named accountable operators and reviewed authentication/custody records; supported private secret delivery; absolute credential and surviving-session bounds. Native admin is broad; static passwords lacking enforced expiry need a verified termination design and new risk decision. No shared bootstrap password. |
| I2 — unavailable environment records | QA/Recovery: exact disposable and operational environment records | Approved environment identifier/topology/capacity/expiry, rendered versions and baseline/checkpoint, independent operator/observer access, cleanup responsibility; existing operations/hooks and scheduled backups identified. No live records were obtained here. |
| I3 — unavailable effective identity evidence | SRE/security: IAM/KMS, ESO/controller and namespace authority, writer/session exclusion | Complete effective policy/grant/RBAC/admission inventory: shared/dedicated readers, Secret readers, Pod/store/policy creators, all workflow/operator/recovery/IaC writers and outstanding sessions. Actual environment reviewer/main/bypass/OIDC rules if Actions is proposed. Unknown or unexcluded writer means HOLD. Source inventory is insufficient. |
| S1 — unavailable signing | Release owner: verified signed integration and operational revisions | Normal trusted signing process produces verifiable commits; rerun checks/review for any changed tree. Connector-created commits remain unsigned. No signing bypass. |
| V1 — tooling/independent review | QA/Adversarial: full repository validation and exact-revision review | Nix/static/policy/provider/plan results and independent disposition of each oracle, reader/writer, hook/recovery and inherited TLS finding. Local full static currently stops at missing Terragrunt; no CI result or reviewer acceptance claimed. |
| A1 — authority/risk decision | Operations Decision Lead then Decision Review / HOME-64 | Consolidated gaps/alternatives and evidence for broad admin authority, static-key custody/rotation, shared-controller/namespace trust, historical-secret exposure and residual writer/session access. Preparation-direction acceptance does not accept these risks or provision identities. HOME-62 issuer remains rejected. |
| A2 — execution approvals | Decision Desk: separately bounded disposable test, then later production operations | Only after concrete artifacts/inputs/signing/review: exact environment/run/checkpoint/teardown request. After evidence/risk acceptance, separate exact cutover, renewal and recovery/resume requests. Proposed interruption windows are not approvals; no request is ready now. |
| E1 — unexecuted operational evidence | QA/Adversarial/Recovery and HOME-3 owner | Under separate approval only: actual Envoy/NGINX all-hop identity/failure/rotation, Harbor positive/negative authorization and old/new credentials/session expiry with skew, reader denials, hook-sentinel/selective-sync and interrupted recovery, alert receipts, and every-node HOME-3 dataplane tests. Unsupported private session baselines stay inconclusive. |

Order: finish bounded repository artifacts and identify inputs → independent
review/signing/full checks → concrete disposable execution approval → collect
server/controller/session evidence → authority/residual-risk disposition →
separate operational approvals. Some identity provisioning may itself need a
prior concrete delegated approval; none is implied here. If I1/I3 cannot be
established, park dependent execution while preserving the repository proposal.
No new broker, revived issuer, general-runner admin or CEO escalation is proposed.

## Overlapping work revalidated

| PR | Inspected head | Integration concern |
| --- | --- | --- |
| HOME-3 #1116, open | `7eaf44c2fa6b6cb7eb2b20e084ba3ed1d70d9a98` | PyYAML/CI/KB overlap; refresh additive traffic and identity matrix with Harbor TLS and Wazuh; no enforcement claim. |
| LiteLLM #1156, open | `b6f332a14dac69861a17a325450fbfbf8096cee6` | Pending caller graph; keep traffic assumptions current before HOME-3 execution. |
| Python catalog #1159, draft | `ffe29338564e4819c370b9e4bd925c2384fd5b16` | Preserve catalog/publication and KB prerequisites; no runtime-image update here. |
| Kubernetes #1162, draft | `1d1caad4305c256201c521442dc98507b0f29b52` | CI/PyYAML/KB overlap; independent upgrade/support/backup gates remain separate. |

This inventory is a point-in-time repository observation. Review any later head
before a future integration or execution request. The baseline source risk
remains unresolved while HOLD is in force; no current deployment or compromise
is established by these repository checks.
