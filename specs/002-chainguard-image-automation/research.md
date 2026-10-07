# Research: Chainguard image automation

<!-- markdownlint-configure-file { "MD013": { "tables": false } } -->

Research completed 2026-10-05 local / 2026-10-06 UTC. Repository baseline:
`a13975cca42873f490e105b095981d13ee5837cc`. Read-only GitHub and registry
inspection informed this design; no cluster migration or permissions changed.

## 1. Native scheduled replication, exact repository names

**Decision:** Extend Harbor's existing `bootstrap.py` to reconcile one scheduled
pull rule per enrolled Chainguard repository. Use the generic Docker Registry
adapter, an exact name such as `chainguard/python`, exact tag `latest`, override
enabled, deletion disabled, and no namespace flattening. Start with hourly
replication. Public sources map to
`harbor.stinkyboi.com/mirror/cgr.dev/chainguard/<image>`.

**Rationale:** Current Harbor chart 1.19.2 runs Harbor 2.15.2. Its native adapter
skips catalog enumeration for literal repository names and lists that
repository's tags. Anonymous Chainguard tag listing worked for Python and
BusyBox; registry-wide catalog scope returned HTTP 400. Broad `chainguard/**`
discovery therefore cannot be assumed to work. Existing bootstrap already
reconciles Harbor resources and protects credential handling.

**Alternatives considered:** A second scheduled copy service duplicates Harbor.
Proxy caching does not provide scheduled publication. Broad namespace rules
depend on unsupported catalog discovery. Do not loosen the existing manual
publisher's reviewed-catalog and current-main restrictions.

Sources: [Chainguard Harbor integration](https://edu.chainguard.dev/chainguard/containers/registry/pull-through-guides/harbor/),
[Harbor 2.15.2 adapter](https://github.com/goharbor/harbor/blob/v2.15.2/src/pkg/reg/adapter/native/adapter.go#L172-L212),
[replication settings](https://goharbor.io/docs/2.14.0/administration/configuring-replication/create-replication-rules/).

## 2. Verify publication before advertising a candidate

**Decision:** Reuse the publisher's Skopeo verification approach in the existing
CI lane: capture the source index digest, compare destination raw content,
check required child platforms, and download all content with intended consumer
access. Retain an immutable `sha256-<hex>` tag. Only then advance a verifier-owned
Harbor `verified-stable` alias and retain a verification receipt. Recheck that
receipt and Harbor availability when preparing a consuming commit.

**Rationale:** Replication success does not prove complete consumer downloads or
that a mutable tag still identifies the observed source. Separate the native
imported `latest` alias from the verified alias read by Image Updater. A source
moving during verification causes a retry; it cannot relabel the captured digest.
The consuming commit includes catalog evidence for its exact digest.

Latest means the verified stable upstream release, including major releases.
An enrollment names a fixed repository-owned metadata/compatibility recipe
that determines release version and stability. Unknown metadata, prereleases,
development variants and older releases fail eligibility. A same-version new
digest is a rebuild; a previously rejected digest remains rejected. Public
`latest` is the initial supported track. An entitled versioned track requires
an explicit tested tag selector and version recipe before enrollment.

The initial release recipe and metadata tests ship with US1 verification,
before import enrollment and acceptance. US2 supplies workload health/data
recipes; imports must not wait for those later consumer-enrollment gates.

**Alternatives considered:** Updater polling raw `latest` would produce proposals
for incomplete imports. Semver alone misses same-tag rebuilds. Native replication
of `latest` does not establish signature, SBOM or referrer copying: make no such
claim, and preserve the separate existing NOFX signing contract.

Repository sources: [publisher](../../scripts/ci/harbor-publish.sh),
[catalog validation](../../scripts/ci/harbor-images-check.py),
[publication runbook](../../docs/harbor-image-mirroring.md).

## 3. Restore Image Updater as a constrained proposal writer

**Decision:** Pin Image Updater chart **1.3.1**, controller **v1.3.0**, with its
controller digest resolved, mirrored and verified before activation. Use the
v1alpha1 ImageUpdater resource, explicit application/image selectors, `digest`
strategy on `verified-stable`, explicit Helm/Kustomize targets, and GitHub API
commit mode (`--git-commit-method=api`). Watch only `argocd`, use namespace RBAC,
and configure `platforms` as an array. Keep the current Argo CD chart 9.5.15
(Argo CD 3.4.2); verify the pairing with the canary.

Write to one inert proposal branch:
`main:codex/image-updater-proposals`. Argo CD continues tracking `main`.
The proposer GitHub App has no main-branch bypass. Its proposal is input data;
the promotion workflow never merges the proposal branch tree.

**Rationale:** v1.3.0 supports GitHub App API commits and expected-head checks.
It lacks a validation-before-main hook, data-aware rollback and durable digest
rejection. Its existing alternate branch is not rebased onto main; reconstruct
each final candidate from current main. Avoid CLI alternate-branch write-back,
which can force push. Avoid per-app template variables that are empty on the
direct-branch path in this release.

Use explicit Harbor runtime references. Image Updater's registry API URL is
not an arbitrary repository-path rewriting facility. This avoids introducing
`cgr.dev` into Talos's existing strict upstream-mirror catalog. Extend coverage
validation for enrolled Harbor references rather than accepting the existing
blanket Harbor exemption. Preserve source provenance in the new receipt catalog.

**Alternatives considered:** Giving the controller a main bypass cannot satisfy
exact-candidate checks. Renovate alone does not meet the requested ownership.
Live Argo parameter overrides do not persist desired state. Upgrading Argo CD
without a demonstrated compatibility need expands scope.

Sources: [controller release](https://github.com/argoproj-labs/argocd-image-updater/releases/tag/v1.3.0),
[chart pin](https://github.com/argoproj/argo-helm/blob/argocd-image-updater-1.3.1/charts/argocd-image-updater/Chart.yaml),
[strategies](https://github.com/argoproj-labs/argocd-image-updater/blob/v1.3.0/docs/basics/update-strategies.md),
[write-back](https://github.com/argoproj-labs/argocd-image-updater/blob/v1.3.0/docs/basics/update-methods.md),
[Git implementation](https://github.com/argoproj-labs/argocd-image-updater/blob/v1.3.0/pkg/argocd/git.go),
[GitHub API commits](https://github.com/argoproj-labs/argocd-image-updater/blob/v1.3.0/pkg/argocd/commit_github.go),
[rollback limitation](https://github.com/argoproj-labs/argocd-image-updater/blob/v1.3.0/docs/basics/update.md),
[resource fields](https://github.com/argoproj-labs/argocd-image-updater/blob/v1.3.0/api/v1alpha1/imageupdater_types.go).

## 4. Direct signed promotion requires a companion governance change

**Decision:** Use a separate CI-only promoter GitHub App and a main-owned
workflow. It constructs a signed, conventional candidate commit C with sole
parent B, the observed main SHA, through `createCommitOnBranch`. Genuine checks
run on C. After verifying their identities/results and main still being B,
advance main to that same C with a non-force ref update. Never validate one
commit and then re-sign or cherry-pick it into another.

Move PR governance into a separate ruleset with only the promoter's explicit
always-bypass. Core signing, linear history, deletion/force-push protection and
validation remain in a ruleset the promoter cannot bypass. Add an independent
`Image Update Gate` for semantic scope, publication and compatibility checks.
Normal PRs also receive a real gate result; automation does not get to edit
enrollment, workflow definitions, credentials or policy through its exception.

**Rationale:** Live ruleset `14700233` requires PRs, signatures, strict checks
and linear history. Its n8n App bypass is PR-only. The installed Argo CD App is
contents-read-only. Both existing plan/production environments require operator
approval. Neither is an unattended credential lane as configured.

Governance belongs to `Stuhlmuller/github-iac`; homelab must not duplicate it.
The companion change must update both declarations and the ruleset validator,
add narrowly scoped main-only unattended environments/credential grants, and
reconcile the observed n8n bypass explicitly (desired configuration currently
declares no bypass). It must not remove reviewers from existing environments.
App registration/installation needs a declared permissions manifest and an
owner bootstrap step; retired SSM values are not evidence of a usable App.

Required existing contexts observed:

| Context | Expected producer | Candidate work needed |
| --- | --- | --- |
| `Lint` | GitHub Actions, App 15368 | Run genuine lint on candidate pushes. |
| `Terragrunt Gate` | GitHub Actions, App 15368 | Adapt base comparison; image-only scope must not require a privileged infrastructure plan. |
| `release-dry-run` | GitHub Actions, App 15368 | Run actual dry-run on candidate pushes. |
| `repo` | GitHub Actions, App 15368 | Extend existing push triggers. |
| `analyze-actions` | GitHub Actions, App 15368 | Extend existing push triggers. |
| `Analyze (python)` | GitHub Actions, App 15368 | Managed Code Quality currently runs on PR/default branch; supply and prove a genuine equivalent candidate CodeQL analysis. |
| `policy-bot: main` | Policy Bot, App 3280987 | Remains required for PRs in PR-governance ruleset. |

Check name alone is insufficient: verify exact SHA, expected App, workflow
identity and workflow definition from the trusted base. Candidate checks have
no promoter secrets. Use an App token for candidate creation so push workflows
run; ordinary `GITHUB_TOKEN` pushes suppress subsequent workflow runs.

**Alternatives considered:** A blanket bypass can skip validation. Synthesized
success statuses are not checks. Native rulesets do not enforce JSON-field
allowlists. If the companion governance change or genuine candidate checks
cannot meet these constraints, use the specified automatically merged PR
fallback, expose approval waits, and retain existing protections. Missing
credentials today alone does not justify discarding the preferred design.

Sources: [current rule](https://github.com/Stuhlmuller/homelab/rules/14700233),
[governance declarations](https://github.com/Stuhlmuller/github-iac/blob/main/Stuhlmuller/repositories/terragrunt.hcl),
[ruleset validator](https://github.com/Stuhlmuller/github-iac/blob/main/Stuhlmuller/repositories/homelab-ruleset-policy.jq),
[ruleset reconciler](https://github.com/Stuhlmuller/github-iac/blob/main/Stuhlmuller/repositories/reconcile-public-rulesets.sh),
[GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets),
[signed API commits](https://docs.github.com/en/graphql/reference/commits#createcommitonbranch),
[non-force reference update](https://docs.github.com/en/rest/git/refs#update-a-reference),
[workflow triggering](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[Code Quality behavior](https://docs.github.com/en/code-security/reference/code-quality/codeql-detection),
[Python quality queries](https://github.com/github/codeql/blob/main/python/ql/src/codeql-suites/python-code-quality.qls).

## 5. Reuse CI for observation and data-safe recovery

**Decision:** One repository-owned workflow and a small stdlib helper coordinate
verification, promotion and recovery. Use native GitHub Deployments/statuses
for the per-application in-flight and known-good journal. Store pause and rejected
digests durably in the repository alongside publication receipts. No database,
new in-cluster supervisor, admission controller or generic plugin framework.

Poll every five minutes for missed work; an active rollout job observes health
and functional checks continuously within its declared deadline (default 30
minutes). On failure, evaluate compatibility of the retained image with current
data using the enrolled recipe. A safe revert passes the same exact-commit
checks; unknown/unsafe or failed recovery pauses and alerts immediately.
Record a failed deployment before attempting the pause commit, so denied Git
writes still block routine updates for that app. Bound rollback and control-only
pause/rejection use their own eligibility predicates with shared signature,
scope and exact-commit validation. A recorded failure does not block its own
safe recovery or pause write. Successful rollback resolves that failure while
preserving digest rejection and any persisted pause; unsafe/unknown decisions,
operator pauses and prior attempts cannot be bypassed. A later invocation
resumes from the journal instead of forgetting an incomplete rollout.

Reuse the existing Discord notification destination through a CI-only grant to
`/homelab/grafana/discord-webhook-url`; keep raw URLs and secrets out of logs.
The five-minute alert target starts at detection and assumes notification
availability. Scheduled-job latency is observable and must be measured in
acceptance; a nominal cron interval alone is not SLO evidence.

**Alternatives considered:** A Git revert without data evidence can corrupt
state. Argo rollback alone neither persists desired state nor stops the updater.
Automatic restore is explicitly out of scope. A new controller or metrics
service duplicates available CI and deployment status facilities.

Source: [GitHub Deployments API](https://docs.github.com/en/rest/deployments/deployments)
supports exact refs, payloads and deployment status records. Disable automatic
ref merging and prior-status inactivation for this journal; deployment events
must not trigger a second runtime delivery path.

## 6. Inventory and migration order

**Decision:** Start with the stateless Harbor vulnerability exporter using public
Chainguard Python. Then assess and migrate every compatible active consumer in
the [migration inventory](migration-inventory.md). Keep justified exceptions
with their existing owner until their concrete compatibility/access gate passes.

Record migration status separately from automation eligibility. A compatible
non-Argo image, including the Cosign signing template if its tests pass, migrates
through its current reviewed delivery path. Keeping that update owner is an
updater-enrollment exception, not a reason to skip the image migration.

**Rationale:** No current catalog image is Chainguard. Public Python matches the
exporter's UID 65532 and stdlib-only command; runtime acceptance is still needed.
BusyBox, Redis, Valkey and PostgreSQL are candidates with consumer-specific
permissions/data gates. Public curl lacks the shell used by the Kiali init
container. Public kubectl currently exceeds the repository's supported version
skew. Paid offerings and custom application bases are not assumed substitutes.

**Alternatives considered:** Blanket repository-name replacement loses startup,
filesystem and data contracts. Migrating databases or Harbor internals first
increases bootstrap/recovery risk. Completing only the pilot would not satisfy
the user's full migration scope.

Sources: [access model](https://edu.chainguard.dev/chainguard/containers/registry/overview/),
[public image build definitions](https://github.com/chainguard-images/images/tree/main/images).

## 7. Independent release and recovery acceptance

**Decision:** T041 activates the stateless pilot after recovery readiness.
T042 explicitly selects and verifies real accessible stable-major and rebuild
digest pairs from the assessed candidates, records their versions/platforms/
receipts and declares isolated replay targets before exercising promotion.
The major pair may use a separate canary; Python is not assumed to supply it.
T050 recovery drills depend on activation, not on T042 sample availability.

**Rationale:** Access to a latest tag does not establish access to two major
versions. Missing samples must remain a visible SC-004 blocker without delaying
independent safety testing. Full feature completion still requires both sets
of acceptance evidence; sample digests are implementation evidence, not invented
values in this design.

**Alternatives considered:** Waiting for a new Python major or requiring
successful major acceptance before recovery drills adds an external dependency
to safety testing. Mock/fabricated releases cannot prove the required live path.

## Resolved design, remaining activation evidence

No unresolved design clarification remains. Implementation must obtain actual
App identities and permissions, companion ruleset/check evidence, complete
rendered/live inventory, any source entitlements, verified image digests, and
per-consumer runtime/migration/recovery results before enabling writes. These
are measurable activation prerequisites, not assumed completed research.
