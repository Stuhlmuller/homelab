# Data model: image automation

<!-- markdownlint-configure-file { "MD013": { "tables": false } } -->

Use repository JSON, existing Kubernetes resources and native GitHub deployment
records. No database or new service. Fields below define the implementation
contract; these configuration files do not exist yet.

## 1. Enrollment and assessment

Authoritative file:
`clusters/homelab/apps/harbor/image-automation.json`. Mount its import projection
into the existing Harbor bootstrap ConfigMap. Generate the ImageUpdater resource
from the same file and check generated output for drift. Enrollment changes
always use normal PR review.

| Entity / key | Required fields | Constraints |
| --- | --- | --- |
| Configuration | `schema_version`, `imports_paused`, import schedule, verification interval | Explicit committed defaults; no desired-state environment overrides. |
| Image enrollment / `image_id` | Source registry/repository/track, destination project/repository, access class, required platforms, release recipe | Exact source/destination names; `public` or `restricted`; stable-only; no implicit major cap. |
| Consumer / `consumer_id` | Application/namespace, resource/container identity, desired-state file/field target, image ID, update owner | Cover init/hook/sidecar/generated containers; unique owner and unambiguous source target. |
| Update group / `application_id` | Consumer IDs, preflight/health/recovery recipe IDs, observation deadline | Smallest group requiring coordinated versions; all members validate and promote atomically. Default deadline 30 minutes. |
| Assessment / `consumer_id` | Current source/digest, candidate mapping, migration status, automation status, evidence links, exception reasons, owner, reconsideration conditions | Migration is `candidate`, `migrated` or `exception`; automation is `not-enrolled`, `enrolled` or `exception`. `migrated` requires original-function acceptance. An automation exception cannot excuse a compatible image migration. |

Recipe IDs select fixed checked-in helper functions, not commands from JSON.
Unknown configured recipes block validation. Import enrollment requires an
implemented release-metadata recipe, delivered with US1 verification. Workload
startup, filesystem, health and data recipes are required before enrolling a
consumer for automatic updates in US2/US3. Pending assessments contain no
placeholder executable recipe IDs. Stateful consumers also link their declared
migration and operator restore runbooks.

Non-Argo consumers can be migrated while retaining their existing reviewed
update owner. Record their automation exception separately from migration
status and keep their publication receipt/source mapping in the catalog.

Reject duplicate IDs, ambiguous YAML paths, unsafe path traversal, symlinks,
unrecognized fields, invalid registry names/digests and empty platform sets.
Paths stay within the declared repository targets. Restricted source access
requires a private destination and explicit consumer credentials. Broad app
selectors and arbitrary repository discovery are invalid.

## 2. Verified release and publication receipt

| Field | Meaning |
| --- | --- |
| `image_id`, `source_ref`, `source_digest` | Enrollment and immutable upstream index identity. |
| `version`, `release_evidence` | Stable version/build metadata and successful fixed release recipe. |
| `destination_ref`, `destination_digest`, `retained_tag` | Harbor identity; source and destination index digests must match. |
| `platforms` | Required platform to verified child-manifest digest mapping. |
| `consumer_access`, `verified_at` | Access classification used for complete downloads and verification time. |
| `verification_run`, `policy_revision` | Trusted main-owned workflow/run and enrollment revision that produced evidence. |

A receipt is keyed by image ID and source digest. Store successful pre-promotion
evidence as a workflow artifact associated with the trusted run, then include
the consumed receipt in `scripts/config/image-automation-state.json` in the
candidate commit. The promoter validates producer identity and repeats current
Harbor availability checks; it never trusts proposal-supplied receipt text.

Unchanged digest and policy produce no extra commit. Repeated verification may
emit workflow logs but does not churn committed timestamps. A policy change
requires revalidation. Keep receipts and pullable tags for current and previous
known-good releases. Do not introduce artifact deletion or retention pruning.

## 3. Proposal and validated update

An Image Updater proposal is untrusted input from the fixed proposal branch.
Only explicit enrolled image fields are parsed. Publication identity comes from
the verified Harbor alias/receipt, not the branch's other contents.

| Field | Meaning |
| --- | --- |
| `application_id`, old/new image sets | One coherent application update; every new digest has a verified receipt. |
| `base_sha` B | Main revision whose enrollment, scripts and configuration authorize the operation. |
| `candidate_sha` C | GitHub-verified signed commit with sole parent B. |
| `operation` | `update`, `rollback` or `pause-reject`; each has a precise allowed field set. |
| `failed_deployment_id`, `known_good_deployment_id` | Required recovery bindings: the same application's failed deployment and, for rollback, its retained successful baseline; the journal also identifies the single logical recovery attempt. |
| `checks` | Actual check/run IDs, exact C, expected App/workflow identities and conclusions. |
| `deployment_id` | Native GitHub deployment record for reconciliation after interruption. |

All operations require current main B, a signed C with sole parent B, exact-C
checks and an allowed semantic diff. Image-changing operations also require
publication evidence and current pullability. Operation-specific gates are:

| Operation | Eligibility | Allowed changes |
| --- | --- | --- |
| `update` | App unpaused; no unresolved rollout; candidate digest not rejected; newest eligible stable version/build and workload compatibility pass. | Enrolled image fields and associated receipts. |
| `rollback` | Bound failed deployment still matches this app's desired images; retained known-good target and fresh current-data evidence prove safety; target is not rejected for this app; no other recovery attempt or terminal unsafe/unknown/failed-recovery decision. An unresolved originating failure or failure-owned pause does not block this operation. An operator pause or intervening app edit does. | Exact recorded recovery image set, receipts and rejection of the failed digest; never clear a pause or rejection. The target need not be newest or equal `verified-stable`. |
| `pause-reject` | Bound failure belongs to this app and names the affected digest. Allowed while paused or unresolved, including after failed rollback; does not require image eligibility, registry availability or a health check on the failing workload. | Set the affected app's pause/reason and add its failed digest rejection only; preserve any operator pause origin. No image, policy or unrelated control edits. |

Main already == C is an idempotent success. Any other main revision invalidates
C and requires reconstruction/revalidation; never merge a stale branch or force
push. Serialize operations per application. Persist the recovery attempt bound
to its originating failure before advancing the ref so restarts cannot create
a second attempt. Resuming that same in-progress attempt is idempotent, not a
new attempt; a terminal recovery failure cannot be retried. Exact-commit
validation failures still block every operation;
the journal and alert remain the fallback when even a pause commit cannot pass.

## 4. Recovery controls and known-good state

`scripts/config/image-automation-state.json` also owns:

- Per-application `paused`, pause origin (`operator` or a failed deployment ID),
  reason, failed digest set and evidence/run link.
- Rejected digests with failure stage, reason and originating deployment.
- Publication receipts required by current or retained known-good references.
- A reviewed `resolved_deployment_id` when an operator clears an earlier
  failed rollout after recovery and a newly verified healthy baseline.

Only scoped automation may add a failure rejection, pause the affected app,
or include a validated recovery image change. Clearing a pause/rejection,
changing policy or expanding enrollment requires a normal reviewed change.
An import-wide pause is enrollment configuration, not a bot-editable field.
The observer reconciles an explicit reviewed resolution into the deployment
journal before accepting a new update. Clearing a Boolean alone cannot erase
an unresolved failure or its evidence.

Native GitHub Deployments/statuses hold application ID, operation, candidate
revision, desired image set, prior successful deployment ID, observation
deadline, evidence URLs and outcome. A success includes Argo reconciliation,
actual image identity and functional acceptance. It is the known-good record;
Argo Healthy alone is insufficient. Pending/in-progress/failed unresolved
records block routine updates even if a pause commit could not be written;
bound recovery/control operations use the separate gates above. A successful
rollback links to and resolves its originating failure, becomes known-good and
retains the failed digest rejection. It does not clear any persisted pause;
paused apps still require reviewed resolution before routine updates resume.

Before initial source migration, seed a known-good record for the existing
image and verify its retained Harbor copy using the existing catalog. The first
rollback may use that prior upstream-origin image, but only the recorded exact
digest for the same consumer; it is not permission to select arbitrary sources.

Before rollback, the fixed recipe evaluates compatibility of the old image
with **current** stored data. Evidence predating the failed rollout is not
sufficient if that rollout could migrate data. Results are `safe`, `unsafe`
or `unknown`; only `safe` permits an automatic image revert. Backups establish
an operator restore option, not image rollback safety.

## 5. State transitions

```text
discovered -> imported -> verified -> proposed -> validating -> committed
                                                               |
                                                           observing
                                                          /         \
                                                     healthy        failed
                                                                       |
                                                     evaluate current data
                                                          /         \
                                                        safe     unsafe/unknown
                                                          |           |
                                                   validate revert    paused + alert
                                                          |
                                                 commit -> observe recovery
                                                       /         \
                                                  recovered     paused + alert
```

- Discovery/import/verification/validation failures leave main unchanged and
  expose the failed stage. No unverified alias advancement or workload update.
- Persist rejection with a recovery commit, or pause/rejection alone for an
  unsafe/unknown case. Failed Git writes also leave a failed deployment journal
  record; later runs cannot silently start a new update.
- Permit at most one recovery attempt per failed deployment. Failed recovery
  never oscillates between versions. Other applications continue independently.
- A restarted run reconciles the journal with main and live declared image
  identity before acting. A pending deployment created before ref advancement
  is not proof that the candidate deployed.
- Human changes to the app or data assumptions invalidate stale recovery;
  preserve those changes, pause and alert. Human main changes unrelated to the
  app still require rebuilding any pending commit on the new base.
