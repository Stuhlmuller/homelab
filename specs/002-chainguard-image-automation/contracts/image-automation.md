# Image automation interface contracts

<!-- markdownlint-configure-file { "MD013": { "tables": false } } -->

These are planned interfaces for implementation. Existing production behavior
does not change until the declared resources, permissions and acceptance gates
are delivered. Data fields are defined in [data-model.md](../data-model.md).

## Registry contract

| Operation | Owner / input | Required result |
| --- | --- | --- |
| Reconcile imports | Existing Harbor PostSync bootstrap; committed enrollment | Idempotent exact-name scheduled pull rules; normal project; override enabled, deletion disabled, no flattening. |
| Import | Harbor, hourly by default | `cgr.dev/chainguard/<image>:latest` appears at `mirror/cgr.dev/chainguard/<image>:latest`; no consumer edit. |
| Verify | Main-owned CI; exact source digest and enrollment | Matching index digest, every required platform/child, complete intended-consumer downloads and receipt. |
| Advertise | Verifier only, after verification | Retained `sha256-<hex>` tag and `verified-stable` alias point to that verified index digest. |
| Discover | Image Updater | Read only `verified-stable` in enrolled Harbor repositories. |

The `mirror` project is public. Restricted sources require a separately private
project, scoped publisher/pull robots and declared namespace pull credentials
before enrollment. Never infer redistribution permission from a successful
authenticated pull. No new subscription is assumed. Source replication rules
cannot overwrite verifier-owned aliases. Import errors preserve previous aliases
and retained digests; no cleanup/deletion rule is introduced.

The pilot's release-metadata recipe and its tests ship with US1 verification,
before its import acceptance. Imports do not depend on US2 workload health/data
recipes; automatic consumer enrollment does. Unknown configured recipes fail
validation at either stage.

Use the existing authenticated CI connectivity path for Harbor verification and
the intended public/private consumer identity for download tests. Capture a
digest once; if upstream changes during verification, retry rather than publish
mixed evidence. Latest-tag replication alone does not copy/prove referrers.

## Argo CD and Image Updater contract

- Controller v1.3.0, chart 1.3.1, mirrored digest verified before activation.
- Replace the retirement marker with the existing shared Helm/Git-values/
  Kustomize application pattern; keep Argo target revisions `main`.
- Namespace `argocd`; namespace RBAC, `createClusterRoles: false`, explicit
  `--watch-namespaces=argocd`; only required Secrets and Applications accessible.
- Generate explicit ImageUpdater application/image selectors from enrollment.
  Strategy `digest`, tracked tag `verified-stable`, required `platforms` array.
- Git write-back uses `--git-commit-method=api`, GitHub App credentials and
  `main:codex/image-updater-proposals`. Poll every two minutes by default.
  Neither direct main writes nor CLI force pushes are allowed for this identity.
- Helm targets name exact repository/tag or full-image value keys and explicit
  `helmvalues:/clusters/.../values.yaml`; Kustomize names exact original image
  and `kustomization:/clusters/...` target. Persist `tag@sha256:...` or full
  digest-pinned Harbor references. Render proves the final workload image.
- Multi-source apps require unambiguous target selection. Multiple same-type
  sources that cannot be addressed safely remain an explicit exception until
  the source layout is corrected through review.
- Renovate excludes only enrolled image targets. It retains exception images,
  chart updates and unrelated dependencies; checks reject conflicting owners.

Migration and updater eligibility are separate. A compatible non-Argo consumer
is migrated through its existing reviewed delivery path, with its existing
owner and receipt-backed Harbor reference. Only its updater enrollment is an
exception; lack of an Argo target is not a reason to leave the image unmigrated.

The proposal branch can lag main. On enrollment changes, seed missing/changed
proposal target files from reviewed main using an append-only API commit with
expected-head comparison. Never reset or force the branch. Concurrent proposer
writes retry after a head mismatch. The promoter always reconstructs current
main files and ignores unrelated proposal content.

## Signed promotion and GitHub protection contract

The trusted supervisor runs from main on a five-minute schedule and explicit
operator dispatch. Dispatch accepts an operation/application ID only; never an
arbitrary ref, script, source registry or secret name. Desired state remains
committed configuration. One small helper implements fixed operations:
`check`, `render`, `verify`, `promote`, `observe` and `recover`.

1. Read current main B and its enrollment, control records and scripts. Refuse
   a non-main privileged workflow execution. Read proposal files as bounded
   data; reject executable edits, symlinks and paths outside enrollment.
2. Select the operation-specific eligibility gate in
   [the data model](../data-model.md#3-proposal-and-validated-update).
   Routine updates need an unpaused app without unresolved rollout and a new
   eligible digest. Rollback binds the originating failure and retained
   known-good target, proves current-data safety and does not require the
   target to be newest. Pause/rejection writes bind that failure and change
   controls only; the app's failed/paused state cannot block them. Validate
   publication and complete app rendering for image changes, not control-only
   writes; shared signature, scope, exact-C checks and main-CAS gates remain.
3. Reconstruct only authorized fields on B: enrolled image values and associated
   publication receipts, or the scoped recovery image/pause/rejection changes.
   A parsed semantic diff must match that exact operation; filename alone is
   not an allowlist. No arbitrary YAML or JSON replacement is accepted.
4. Create a fresh candidate branch at B. Use GitHub's API commit method with
   expected head B, a conventional message and sole parent B. Verify GitHub's
   signature status. Retain returned candidate SHA C without rewriting it.
5. Run the existing genuine checks plus `Image Update Gate` on C. Jobs use the
   trusted base's workflow definitions and receive no promoter/source secrets.
   Verify exact SHA, producer App, workflow identity/content and successful
   conclusions. Fake or skipped success contexts do not qualify.
6. Record the pending deployment with exact ref C and `auto_merge: false`,
   verify main is still B, then update its ref
   to C with `force: false`. Non-fast-forward rejection handles a concurrent
   sibling update; re-read main and rebuild/revalidate. Main already C is success.
7. Observe Argo and functional behavior against C's desired image set. A later
   unrelated main commit may be a descendant of C; prove the app fields still
   match rather than requiring every other application to stop changing.

Candidate creation uses an App token so GitHub push events run checks. A trusted
scheduled supervisor polls completed checks; do not execute untrusted artifacts
in a privileged `workflow_run` checkout. Rollout observation is per application;
serialize only main-ref promotion, with CAS as the final race guard. An active
observation must not block unrelated eligible apps or be cancelled by a cron run.

Journal deployments use a stable per-application environment name, separate
from the protected CI credential environment. Deployment API creation must not
merge refs or deploy code itself. Preserve prior successful evidence when adding
new statuses (`auto_inactive: false`); an in-flight record is never a new
known-good version. Use an explicit journal task name with no deployment-event
consumer that mutates runtime state. Argo CD remains the deployment owner.

### Companion configuration in github-iac

- Core ruleset: signatures, linear history, force/deletion protection, the six
  genuine existing validation contexts listed in [research](../research.md),
  and `Image Update Gate`; no promoter bypass.
- PR-governance ruleset: PR requirement and `policy-bot: main`; dedicated
  promoter App alone gets the required direct-write bypass. Preserve human
  and other integration protections. Reconcile the observed n8n bypass explicitly.
- Image Update Gate validates ordinary PR configuration normally; for automated
  candidates it additionally enforces exact operation/enrollment/receipt scope.
  This avoids creating a required check that ordinary PRs cannot obtain.
- Extend genuine workflows to candidate pushes and establish a real equivalent
  `Analyze (python)` CodeQL producer before requiring it on the direct path.
  Prove all required contexts actually run on C; no context fabrication.
- Add separate main-only unattended environment/credential grants. Preserve
  approval requirements on existing `homelab-plan` and `homelab-production`.
- Update github-iac's ruleset validator and saved-plan checks together with
  declarations. Apply through that repository's reviewed path.

If this contract cannot be satisfied, use automatically merged PRs with all
required checks/approvals. Record the precise blocker, expose pending approval
and keep routine image changes scoped. Do not silently enable a broad bypass.

## Secret and permission contract

| Identity | Storage / delivery | Authority |
| --- | --- | --- |
| Harbor bootstrap | Existing mounted admin secret | Reconcile declared registry endpoint/rules/projects/robots; never passed to updater. |
| Chainguard source reader | Anonymous for public baseline; explicit SSM/ESO reference if entitlement requires credentials | Pull only approved source repositories; restricted destination must exist first. |
| Harbor verifier/publisher | Existing scoped mirror publication credential through CI | Read/copy/alias only declared repositories; private destination needs its own scoped robot. |
| Image Updater proposer App | Fresh verified `/homelab/argocd-image-updater/github-app/{id,installation-id,private-key}` via ESO | Homelab-only contents write for proposal branch; no main bypass, administration or checks write. |
| Promoter App | New CI-only `/homelab/image-automation/github-app/{id,installation-id,private-key}` references | Homelab-only contents/deployments write; read checks/actions; bypass PR governance only; no administration or checks write. |
| Observer / notifier | Existing declared cluster connectivity plus narrowly granted CI read access and Discord secret | Read app health/resources and send bounded failure notification; no ad hoc Kubernetes mutation. |

Declare SSM contracts in `IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl`.
Restore proposer tombstones only with fresh verified credentials and exact ESO
reader access. Promoter credentials remain `reader_access = false` for runtime
ESO and are available only to the dedicated CI role. Any credential bootstrap
must use the repository's declared secret workflow. App registration and
installation permissions are a reviewed external prerequisite.

Use file-mounted runtime secrets. CI environment variables may carry credentials
only. Never store tokens/private keys in JSON, logs or artifacts. Notification
grants reuse `/homelab/grafana/discord-webhook-url`; redact its value and send
only app/digests/stage/run URL/action. No source entitlement is assumed or bought.

## Health, recovery and operator controls

Each enrolled app names fixed preflight, health and current-data rollback
recipes. Health requires Argo convergence, ready workload, actual platform
image IDs matching the verified index's children, and original functional
acceptance before the deadline. A missing observer result is unresolved, never
implicitly healthy.

Record failure before recovery. If current data is safe for the retained image,
prepare a signed revert plus digest rejection using the bound rollback gate
and shared exact-commit pipeline. The originating unresolved failure does not
block recovery; an operator pause, changed app, another recovery attempt or
terminal unsafe/unknown/failed-recovery decision does. Resume the same
in-progress attempt idempotently; never start a second one. Observe the revert's
original function.
Resolve the originating failure on successful recovery while retaining its
digest rejection and any persisted pause. Attempt recovery
once; unsafe/unknown data, denied writes or failed rollback cause pause and
alert within five minutes of detection when dependencies are available. Failed
journal records block routine app updates even if persisting the pause in Git
fails; an authorized control-only pause/rejection remains allowed. No automatic
data restoration.

Operators pause imports or resume/clear app controls through normal reviewed
configuration changes. Reject a bad digest durably; it stays ineligible even
when source tags move back or controllers restart. A private recovery runbook
may reference credentials, but public evidence contains safe metadata only.
Resuming a failed app names the resolved deployment and supplies a newly
verified healthy baseline; the journal must reconcile that reviewed resolution
before another promotion.

Cold bootstrap retains the documented upstream/Talos mirror recovery path.
Keep the updater disabled until Harbor, ESO, Argo and verified controller image
are available. Document the source reference for every Harbor pin, so the
reviewed bootstrap/recovery configuration can select upstream copies if Harbor
is unavailable. Source selection changes use repository code, never live patches.

## Acceptance lane contract

After pilot activation, release acceptance T042 and recovery drills T050 run
independently. T042 selects real accessible major/rebuild pairs and records
exact source/index/child identities, stable versions, access/full-pull evidence,
canary targets and functional recipes before any replay. Use a separate isolated
major-version canary where needed; do not depend on a new Python major release.

Only reviewed test enrollment/workflow configuration can select the replay
samples. Production source tracking and eligibility checks stay unchanged.
The replay still uses verified Harbor content, Image Updater, exact signed
commit checks and Argo CD. Missing samples block SC-004 completion, not recovery
safety testing; neither mocks nor a successful recovery drill replace release
acceptance. See [validation order](../quickstart.md#acceptance-order-and-release-samples).
