# HOME-57 hook-safe stop and independent recovery readback

**HOLD; repository-only preparation from `d141fa44a7f5992faf9904afa7f1441d2606f470`.**
This Recovery-owned addendum supersedes the first-cutover sync instructions in
[the recovery proposal](harbor-vulnerability-recovery-proposal.md). It does not
change SRE's lifecycle implementation, QA's fixture or live desired state.
SRE's separate custody proposal at `afa40cb31f8a8ebb0c2093b00b39394ae0726936`
remains an unaccepted dependency, including its unresolved broad operator,
static reader, shared controller and writer/session risks. HOME-62 rejects the
old system issuer; its hard stops must remain intact.

## Why a replica-only diff is insufficient

The Harbor base includes PostSync `harbor-bootstrap` and
`harbor-postgres-backup-initial`. Bootstrap changes project/robot configuration
and submits scans; backup invokes retention deletion in `backup.sh`. A full sync
can run both even if the only changed manifest field is replicas. The existing
zero overlay is **render-only**, not an apply or full-sync artifact.

Proposed operation: an exact **resource-selective Argo sync** for only
`apps/Deployment/harbor/harbor-vulnerability-exporter`, with prune false,
apply strategy (force false), zero retries and no inline manifests. This cannot
select either Job. Do not substitute `ApplyOutOfSyncOnly`, which can run hooks.
Argo's [selective-sync contract](https://argo-cd.readthedocs.io/en/release-3.1/user-guide/selective_sync/)
excludes hooks and does not record normal rollback history; preserve a separate
operation receipt. The [sync-options documentation](https://argo-cd.readthedocs.io/en/latest/user-guide/sync-options/)
distinguishes the out-of-sync-only option.

The repository's bootstrap chart 9.5.15 declares
[Argo CD v3.4.2](https://github.com/argoproj/argo-helm/blob/argo-cd-9.5.15/charts/argo-cd/Chart.yaml).
At that pinned source, [controller/sync.go](https://github.com/argoproj/argo-cd/blob/v3.4.2/controller/sync.go#L315)
sets skip-hooks when apply strategy or a nonempty resource selection is used,
and filters resources against the selection. The
[engine](https://github.com/argoproj/argo-cd/blob/v3.4.2/gitops-engine/pkg/sync/sync_context.go)
uses that setting to omit hooks. This source trace plus exact resource selection
is the conditional proof that **this operation** cannot launch the two PostSync
Jobs. It is not proof of installed controller behavior, other concurrent syncs,
already-running Jobs or independently scheduled CronJobs.

## Three separately approved phases, not one overlay application

1. **Pause and exclude before merging any zero-replica change.** Prepare a
   signed current-main change only to
   `unit argocd_apps_harbor.values.manifest.spec.syncPolicy.automated.enabled`
   in `IaC/terragrunt.stack.hcl`, from true to false. Through the existing
   Terragrunt owner, plan only `IaC/live/argocd-apps/harbor`; reject anything
   except the Application sync-policy delta. This is the concrete required
   declaration, not a committed active change in this proposal. Review/apply
   authority remains separate. Do not patch the live Application or use
   `argocd app set`. Applying this policy does not cancel an existing operation.
   Before continuing, independently verify the actual Application UID/version,
   automated.enabled=false, no queued/running/terminating operation and no active
   bootstrap/backup hook Job or Pod. A running hook means HOLD, not permission
   to terminate it. Confirm no HPA, alternate controller or manual writer can
   restore collector replicas.
2. **One resource-selective stop.** With the pause observed, create the exact
   signed stop-only main SHA changing exporter replicas 1 → 0. Do not promote
   all of #1163 to stop the baseline admin collector. Freeze competing
   Terragrunt/GitOps/workflow/manual writers and sync permissions for the
   supervised window through already approved controls; do not invent authority
   to change RBAC here. If effective exclusion cannot be established, HOLD.
   Render the *actual current* before/after Deployment, including all live
   ownership and drift review; require no template/image/script/mount/strategy
   delta. Resolve all three sources: chart 1.19.2, values git SHA, manifest git
   SHA. Both git sources must resolve to that same approved stop SHA; no moving
   `main` in the operation request. Only the exact Deployment is selected.
3. **Observe and retain pause.** Require the recorded operation resource list
   to contain only that Deployment, no hook results, and no new Job/Pod UID,
   hook event or audit create for either hook. Verify Deployment/ReplicaSets zero
   and all old admin-mounted collector Pods absent as previously specified.
   If another writer, sync or hook appears, fail containment and retain UNKNOWN
   side effects; do not call successful scaling sufficient. Do not automatically
   re-enable auto-sync: it can immediately run a full Harbor sync and hooks.
   Resumption requires a separate exact main plan reviewing every pending diff
   and the explicit bootstrap/backup data effects. Keep alerts and the observer
   active while automation is paused; record that drift correction is reduced.

The maintenance reservation must cover all app-sync callers, root/operator
Terragrunt applies and existing controller operations, not merely the lifecycle
workflow concurrency group. Snapshot checks do not atomically exclude a racing
writer. No adapter or effective exclusion control is supplied here. The proposed
20-minute telemetry and five-minute old-Pod limits start at stop/loss, not at
policy preparation. If pause/exclusion takes too long, do not start the stop.
No automatic extension, alert silence, force deletion, credential or data action.

The scheduled backup CronJob remains unchanged and may run independently. This
proposal does not promise no data activity anywhere in Harbor; it forbids this
operation from launching data hooks. The observer must separately identify
scheduled runs so they cannot mask an unexpected hook. If the approved scope
requires total backup inactivity, an additional declared suspension plan and
approval are prerequisites, not an implicit part of stopping the exporter.

## Offline request validator and unexecuted controller fixture

`scripts/harbor-exporter-stop-plan.py --evidence <metadata.json>` accepts the
exact synthetic shape exercised by its tests: Application snapshot, before and
after Deployment, stop SHA, exclusion and runtime receipt references. It rejects
active/ambiguous automated sync, running operations, wrong source order or ref,
plugins, extra sync options, non-Deployment resources and all changes except
replicas. It prints a **proposal** in the pinned
[ApplicationSyncRequest shape](https://github.com/argoproj/argo-cd/blob/v3.4.2/server/application/application.proto#L114),
including sourcePositions/revisions and `syncOptions.items`. Application UID/
resourceVersion and manifest hashes bind the review record; the sync API offers
no resourceVersion precondition, so these are not a lock or CAS guarantee.
`--execute` refuses before reading inputs. There is no credential reader, client,
network transport, API call or mutation adapter. Receipt names are references,
not signed attestations; supplied JSON cannot prove live exclusion or approval.
`runtime_hook_exclusion_proven` always remains false.

Offline tests use the actual two repository hook declarations, confirm neither
can be selected, and reject full-overlay shapes, image/mount changes, concurrent
operations and `ApplyOutOfSyncOnly`/force/replace alternatives. These are request
and source-contract checks, not an Argo controller execution test.

Before requesting production use, add a separately approved disposable test:
run the exact Argo server/controller digest and harmless synthetic exporter plus
PostSync sentinel Jobs (no credentials, Harbor data or pruning script). First
prove a full-sync positive control creates both sentinels. Reset the environment
through approved teardown/reprovisioning. Pause automation, execute the exact
selective stop and prove replicas zero with no sentinel Job/audit event and no
sentinel state change. Include queued full sync, auto-sync re-enable, racing
writer and process-death negatives; those must block or report UNKNOWN. Capture
version/digest, request, controller operation, UIDs and audit receipts. Exact
provision/checkpoint/teardown, fixture adapter and execution approval are still
missing. No controller fixture ran in this pass.

## Interrupted credential recovery: independent readback contract

`scripts/harbor-vulnerability-recovery.py` remains a metadata-only planner.
It now models process death, cancellation, lost-create response/unknown ID,
lost mutation response, disabled/expired state and readback provenance. An
interruption overrides a caller's claimed success and leaves outcome UNKNOWN.
No finally block, job exit, cancellation or timeout proves cleanup or revocation.
The legacy `issuer_available` metadata field means approved replacement custody
availability only; it never permits the rejected issuer to run.

Readback metadata must come from a different named observer after the event,
with exact ID, observed SSM version, scope/identity check, disabled/expired state,
audit reference and writer-exclusion evidence. Same observer, stale receipt or
invalid types are rejected. Mismatched ID/version/state or absent writer exclusion
cannot unlock even a proposed known-ID mutation. Correlation only prepares a
new approval request; outcome UNKNOWN is retained and execution/resume/revocation
flags never become true. Two strings do not prove independent people or access:
the protected procedure must verify their identities and attach private evidence.

| Failure | Independent evidence and safe next boundary |
| --- | --- |
| Process dies or dispatch is cancelled | Freeze all forward writes; separately inspect Harbor exact ID, audit events, SSM version/provenance and ESO generation. Establish whether management/AWS sessions still exist. Do not assume exception cleanup ran or repeat the operation. |
| Lost create response; no immutable ID | Keep approved/observed ID null and outcome UNKNOWN. Correlate the prior no-collision inventory and exact authorized create intent with actor/time/request/audit event and uniquely persisted ID/name/scopes. A name match, one list result or empty list is insufficient. If audit or uniqueness is missing, HOLD; no second POST, adoption or broad disable. A resolved ID needs a new exact-ID approval record; the planner never promotes a receipt into identity. |
| Known ID; disable PUT response lost | Independently GET the exact ID and verify identity/scopes plus disabled flag. Readback can support a new containment approval but does not prove bearer invalidation. Do not repeat PUT solely because the response was lost. |
| Disabled or expired identity | Preserve disabled state; verify absolute persisted expiry, permissions and custody. Normal renew remains forbidden. Lost secret needs a separately approved fresh rotation/publication operation; no old SSM version restoration. |
| Refresh succeeded, publication uncertain | Freeze publication; independently correlate expected/current SSM versions, envelope ID and write audit. No CAS is claimed; another writer/ESO consumption may already have raced. Unknown content/custody means HOLD and separate rotation, not replay. |
| Enable or ESO outcome uncertain | Keep exporter stopped; compare Harbor, envelope version, controller refresh and mounted credential via private protected verification. No Secret dump, token hash or reusable credential enters metadata. Separate approval is required before enabling or starting. |
| Custodian/authority unavailable | Retain UNKNOWN/stopped state and route HOME-62. No admin fallback, shared bootstrap password, revived issuer or reusable management credential in general CI. |

Independent observation has its own explicit read-only authorization and custody
scope; this task does not authorize obtaining those credentials. The selected
native person-bound admin proposal has broad authority and no established finite
password expiry. The custody workstation, private secret publication adapter,
AWS identity, observer access and termination verifier are unsupported prerequisites.
Record approval-window end, job timeout, AWS session actual expiry and role maximum,
management-credential lifetime, robot absolute expiry and bearer/API/browser
lifetimes separately. Cancellation, logout and workstation disposal are not
server-session revocation. Exclude both new writers and outstanding sessions.

Compromise requires separate exact-ID disable plus old-Basic and previously minted
bearer/session rejection controls, including sessions usable until verified expiry.
An unauthenticated public read or network failure is not a valid revocation test.
If management authority itself may be compromised, target-only recovery cannot
claim containment; return its wider scope to Decision Review. Availability rollback
never restores a suspected credential. QA's issuer-specific extension at #1172
owns the actual capability/session recipes; all are still unexecuted.

Offline validation (repository Nix environment with PyYAML):

```sh
python3 -I scripts/ci/harbor-exporter-stop-plan-test.py
python3 -I scripts/ci/harbor-vulnerability-recovery-test.py
python3 -I scripts/ci/harbor-vulnerability-credential-test.py
```

## Integration and approval boundary

SRE should integrate these Recovery-only changes alongside its custody proposal
and QA #1172, preserving the rejected issuer hard stop. No lifecycle or fixture
file was changed here. Run the two focused suites plus lifecycle regressions and
normal release gates. Then independently review the signed combined revision.

No execution request is ready. Missing are the approved pause/stop/resume SHAs
and single-unit plans, effective sync/writer exclusion, pinned controller fixture
and runtime proof, protected recovery/readback/publication adapter, HOME-62 custody
acceptance, server/session/expiry and all-hop TLS evidence, HOME-3, alert receipt,
full validation/signing and exact disposable provisioning/checkpoint/teardown.
The planner is executable *offline code*, not an executable recovery path.
