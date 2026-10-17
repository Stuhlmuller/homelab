# Feature Specification: Chainguard Image Automation

**Feature Branch**: Not created; no branch hook is configured.

**Feature Directory**: `specs/002-chainguard-image-automation`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "Configure images to auto update from chainguard in
Harbor and use argocd image updater to automatically bump the images to the
latest from harbor."

**Scope clarification**: Migrate compatible workloads to Chainguard; document
exceptions.

## Clarifications

### Session 2026-10-05

- Q: Should routine image-update PRs merge automatically once all required
  checks and approvals pass? → A: Prefer a GitHub bot writing routine image
  updates directly to `main` without PRs; automated PR merge is the fallback.
- Q: Which version changes should the bot deploy automatically? → A: Any stable
  release, including new major versions.
- Q: If an automatic update makes a workload unhealthy, how should recovery
  behave? → A: Automatically revert when data-compatible; otherwise pause
  updates and alert the operator.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Keep selected images available in Harbor (Priority: P1)

As the homelab operator, I want Harbor to receive new Chainguard images
automatically so routine upstream rebuilds need no manual copy operation.

**Why this priority**: Workloads must have a verified, available image before
an update can safely be proposed or deployed.

**Independent Test**: Enroll one accessible Chainguard image, observe an upstream
change to its tracked tag, and verify the complete new image is downloadable
from Harbor without changing any workload.

**Acceptance Scenarios**:

1. **Given** an enrolled source and working credentials, **When** its tracked
   tag points to a new digest, **Then** the next scheduled import copies that
   digest and all required architectures, verifies complete destination pulls,
   and records the result without an operator starting the copy.
2. **Given** a previously verified image, **When** the source is unavailable or
   an import is incomplete, **Then** that candidate remains ineligible for
   deployment and the previous image remains available.
3. **Given** unchanged source content, **When** two further import cycles run,
   **Then** they create no new update commit or duplicate retained release.
4. **Given** an authenticated source, **When** it is enrolled, **Then** its
   destination access is explicitly approved and restricted content cannot
   enter the publicly readable mirror project.

---

### User Story 2 - Migrate compatible workloads (Priority: P1)

As the homelab operator, I want every compatible active workload assessed and
migrated to its Chainguard equivalent, with specific reasons for exceptions,
so adoption is complete and does not silently change application behavior.

**Why this priority**: The current container catalog contains no Chainguard
images; wiring automation alone would leave the requested workloads unchanged.

**Independent Test**: Review the migration inventory, then migrate one eligible
workload using a verified Harbor image and demonstrate its original user action,
health checks, and data access.

**Acceptance Scenarios**:

1. **Given** repository declarations, rendered charts, and read-only runtime
   inventory, **When** migration scope is assessed, **Then** every active image,
   including init containers, hooks, sidecars, and operator-created containers,
   has a Chainguard mapping or a documented exception.
2. **Given** an available equivalent, **When** migration is proposed, **Then**
   compatibility evidence covers startup commands, user/file permissions,
   required utilities and extensions, architecture, probes, and persistent data.
3. **Given** an eligible workload and a published image, **When** its migration
   passes required review and deploys, **Then** it runs the verified digest from
   Harbor and its existing user-facing function succeeds.
4. **Given** no suitable equivalent, missing entitlement, or a failed
   compatibility check, **When** the inventory is reviewed, **Then** the original
   image stays pinned and the exception records its reason, update owner, and
   condition for reconsideration.

---

### User Story 3 - Automatically commit and deploy image bumps (Priority: P2)

As the homelab operator, I want Argo CD Image Updater to detect newer eligible
images in Harbor and prepare persistent image bumps, so I maintain fresh images
without manually reviewing or merging a PR for each routine update.

**Why this priority**: This closes the loop from upstream publication to running
workloads while preserving reproducible desired state.

**Independent Test**: Start with two verified image digests in Harbor, enable one
application, and observe validation of a signed image-update commit, a bot
advancing `main` without a PR, and reconciliation to the selected digest.

**Acceptance Scenarios**:

1. **Given** a newer verified digest in an application's approved track,
   **When** Image Updater checks Harbor, **Then** it prepares a pinned image
   change with publication evidence for the authorized GitHub bot to commit.
2. **Given** a rebuild that keeps the same tag, **When** its digest changes,
   **Then** automation detects it and proposes the new digest even though the
   tag text is unchanged.
3. **Given** an eligible routine update, **When** required validation passes
   for its exact candidate revision, **Then** the bot advances `main` without a
   PR or per-update human approval and Argo CD deploys the committed digest.
   Failed validation keeps `main` and the running version unchanged.
4. **Given** an enrolled image, **When** both update tools run, **Then** only
   Image Updater owns its image bumps; Renovate continues managing other images
   and unrelated dependencies without competing updates for that image.
5. **Given** repeated checks, a newer candidate, or a human edit, **When** an
   update is in progress, **Then** automation avoids duplicate commits,
   preserves unrelated human changes, and revalidates if `main` advances.
6. **Given** an update changes unenrolled images, automation policy definitions,
   credentials, or unrelated files, **When** the bot evaluates it, **Then** it
   cannot use the routine-update exception and normal PR review remains required.
   Recovery pause and digest rejection records follow the authorized recovery
   exception.
7. **Given** a newer stable major release of an enrolled image, **When** it
   passes publication and compatibility validation, **Then** it uses the same
   automatic commit and deployment path without extra approval for the version
   boundary. A failed compatibility check blocks that candidate visibly.

---

### User Story 4 - Diagnose, pause, and recover updates (Priority: P3)

As the homelab operator, I want failed updates to recover automatically when
rollback is data-compatible, and pause with an alert otherwise, so unattended
updates remain recoverable without risking stored data.

**Why this priority**: Registry access, repository permissions, and application
compatibility can fail independently.

**Independent Test**: Make an updated stateless canary fail its health check
and observe an automatic repository revert to its retained working digest.
Exercise an unsafe or unknown stateful rollback case and verify that further
updates pause and an alert is delivered without reverting the image or data.

**Acceptance Scenarios**:

1. **Given** an import, permission, verification, or rollout failure, **When**
   the operator inspects status, **Then** it identifies the affected image,
   failed stage, last success, and required action without revealing credentials.
2. **Given** a paused application or rejected digest, **When** automation runs,
   **Then** it does not reapply that update and other eligible applications can
   continue updating.
3. **Given** an update fails its declared rollout health or functional checks
   and a retained known-good digest is verified compatible with current data,
   **When** rollback validation passes, **Then** the bot automatically commits
   a revert through the authorized delivery path without per-update approval,
   restores the working digest, and blocks the failed digest from reapplication.
4. **Given** an update fails and rollback data compatibility is unsafe or
   unknown, **When** recovery is evaluated, **Then** automation pauses further
   updates to the affected application and alerts the operator without reverting
   its image or restoring data. Other unaffected applications continue updating.
5. **Given** a clean checkout, **When** an operator reviews the implementation
   and runbooks, **Then** all import, update, credential, pause, and recovery
   controls have repository-owned definitions, validation steps, and an updated
   knowledge-base entry; rebuilding follows the documented bootstrap path.
6. **Given** an automatic rollback fails validation, cannot be committed, or
   fails its recovery health checks, **When** that failure is detected, **Then**
   automation pauses further updates and alerts the operator without repeatedly
   switching between image versions.

### Edge Cases

- A mutable tag changes twice during copying; only a completely verified,
  recorded digest can be proposed, and later content waits for another cycle.
- A tag disappears or is repointed to a previously rejected or older release;
  no unapproved downgrade or return to a rejected digest occurs.
- A multi-platform image is missing an architecture needed by its consumers,
  or only part of its content reaches Harbor; it remains ineligible.
- Registry authentication expires, rate limits apply, or the bot lacks direct
  write permission; existing workloads continue and failure is visible.
- `main` advances after candidate validation; the stale update is not force
  pushed, and the candidate must be rebuilt and validated against current state.
- Existing branch protections prevent a safe scoped direct-write path; record
  the limitation and use automatically merged PRs after their required checks
  and approvals, rather than silently relaxing unrelated protections.
- A broadly matching selector includes an unenrolled app or an obsolete version
  constraint; validation rejects that enrollment before activation.
- A tag advances across a stable major release; the version boundary alone
  does not block automatic deployment. Required data migrations or incompatible
  chart/component combinations must pass the declared compatibility and recovery
  checks; candidates needing unimplemented migration or configuration changes
  remain blocked with a documented reason.
- A minimal image lacks a shell, entrypoint behavior, extension, or writable
  path required by an existing workload; record an exception until resolved.
- A restored controller, import job, or Harbor itself needs images that are
  unavailable during cold bootstrap; the documented recovery path still works.
- The current strict node mirrors or catalog coverage rules reject a new
  Chainguard reference; enrollment cannot complete until delivery is validated.
- Available storage is exhausted; import failure cannot delete retained working
  images or cause an unverified digest to reach consumers.
- An update changes stored data so the previous image cannot safely read it, or
  rollback compatibility evidence is missing; pause further updates and alert
  rather than assume an image-only revert or data restore is safe.
- Rollback fails or the application changes during recovery; preserve unrelated
  changes, stop automatic retries for that failed update, and alert the operator.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The feature MUST assess every active workload image and migrate
  every compatible, accessible Chainguard equivalent. Each non-migrated image
  MUST have a specific exception with evidence and a reconsideration condition.
  Lack of an Argo CD target alone MUST NOT exempt a compatible image from
  migration; its existing reviewed update owner may be retained.
- **FR-002**: Each enrolled image MUST have a repository-owned source-to-Harbor
  mapping, consumers, approved release track, required architectures, access
  classification, and update owner. Enrollment MUST be explicit.
- **FR-003**: Harbor MUST receive enrolled Chainguard updates on a declared
  recurring schedule without per-import operator dispatch. Imports MUST detect
  both new allowed versions and changed digests behind an existing tracked tag.
- **FR-004**: "Latest" MUST mean the newest verified stable release, including
  new major versions, or its newest same-tag rebuild. Enrolled images MUST
  permit automatic stable major upgrades without per-upgrade approval. Mutable
  stable tracks follow the current verified tag digest; versioned tracks select
  the newest stable version across major boundaries. Prereleases, development
  variants, and known incompatible candidates MUST remain ineligible. Any
  compatibility pin MUST be a documented exception, not an implicit major cap.
- **FR-005**: An image MUST become eligible only after source/destination digest
  agreement, required-platform coverage, and complete downloads using the
  intended consumer access have succeeded. A manifest lookup alone is
  insufficient. A source change during import MUST NOT alter the recorded
  candidate's identity.
- **FR-006**: Publication evidence and repository catalog coverage MUST exist
  before a consuming reference reaches `main` or deploys. Automation MUST
  preserve this order even when imports and update commits overlap.
- **FR-007**: Argo CD Image Updater MUST be restored as the update owner for
  enrolled applications and MUST discover their deployable candidates from
  Harbor. Its write permissions and selectors MUST be verified before enablement.
- **FR-008**: Routine image bumps MUST persist in repository-owned desired
  state as signed commits with conventional messages, digest pins, source
  provenance, and publication evidence. A dedicated GitHub bot MUST advance
  `main` directly without PRs or per-update human approval for enrolled images.
  Live-only overrides are prohibited.
- **FR-009**: The direct-write exception MUST cover only enrolled image and
  associated catalog updates, including stable major upgrades and validated
  recovery reverts. It MUST also permit affected-application pause and failed
  digest rejection records under the declared recovery policy. Required
  validation MUST pass on the exact candidate revision before `main` advances;
  a changed base requires revalidation and force pushes are prohibited.
  Enrollment, bot permissions, automation policy definitions, and unrelated
  changes retain normal review.
  Argo CD MUST deploy the accepted commit automatically. If planning establishes
  that a scoped direct-write path cannot satisfy these constraints, document the
  reason and use automatically merged PRs after required checks and approvals.
- **FR-010**: Each enrolled image MUST have exactly one update owner. Renovate
  MUST stop proposing bumps for those images while retaining coverage of
  exceptions, charts, and other dependencies.
- **FR-011**: Migration MUST demonstrate existing workload behavior, required
  architectures, startup and filesystem compatibility, and persistent-data
  compatibility before completion. These compatibility checks MUST also gate
  automatic updates, including major upgrades. Coordinated component upgrades
  MUST remain compatible as a group. Required data migration and recovery paths
  MUST exist and pass their declared checks before a candidate can deploy.
- **FR-012**: Authentication MUST use least-privilege managed secret references
  for source reads, destination publication/reads, and repository writes.
  Secrets MUST NOT appear in public configuration, logs, or artifacts. Private
  or restricted images MUST NOT be copied into the public mirror project.
- **FR-013**: Operators MUST be able to pause imports or application updates,
  reject a digest, and revert through repository-owned controls. An update that
  fails its declared rollout health or functional checks MUST automatically
  revert to the retained known-good digest when compatibility with current data
  is verified. The revert MUST pass required validation and use the authorized
  repository delivery path; the failed digest MUST remain blocked until
  explicitly cleared. Unsafe or unknown rollback compatibility, or a failed
  rollback, MUST pause affected-application updates and alert the operator.
  Automation MUST NOT restore data automatically or retry a failed rollback
  indefinitely. Pause and rejection controls MUST survive reconciliation and
  restarts; unaffected applications MUST remain eligible for updates.
  A failed rollout MUST block routine updates while still permitting its
  authorized data-safe recovery and control-only pause/rejection writes.
- **FR-014**: Current and immediately previous known-good image digests MUST
  remain pullable for each enrolled workload. This feature MUST NOT introduce
  deletion of existing artifacts. Recovery guidance MUST cover registry loss,
  cold bootstrap, and stateful data restore limits.
- **FR-015**: Status MUST distinguish discovery, import, verification,
  validation, commit, deployment, rollback, pause, and failure; expose last
  success and actionable failure information; and avoid duplicate commits for an
  unchanged update. Each enrolled workload MUST declare rollout health and
  functional checks with a bounded observation deadline, defaulting to 30
  minutes. Recovery alerts MUST name the affected application, failed and
  known-good digests, recovery outcome, and required operator action without
  secrets. The PR fallback MUST also expose any pending approval.
- **FR-016**: All automation configuration and migrations MUST be reproducible
  through the existing repository delivery model and documented bootstrap path.
  Desired-state environment overrides and ad hoc live repairs are prohibited.
- **FR-017**: Implementation MUST update the image inventory, retirement and
  migration guidance, credential contracts, ownership notes, validation gates,
  and affected knowledge-base notes to match the resulting behavior.

### Key Entities

- **Image enrollment**: An approved source, destination, release track,
  architecture set, consumers, access classification, and update owner.
- **Verified release**: Immutable image identity, upstream provenance,
  destination availability evidence, and verification time.
- **Migration assessment**: Current image, candidate equivalent, compatibility
  evidence, migration status or exception, and reconsideration condition.
- **Image update**: Previous and candidate digests, affected applications,
  publication evidence, validated candidate revision and base revision,
  bot identity, and commit/deployment status.
- **Recovery control**: Persisted pause, rejected digest, retained known-good
  release with successful health/function evidence, compatibility evidence for
  current data, recovery outcome, and any required operator-led restore procedure.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of active workload images have a migration assessment; every
  eligible image is migrated and every exception has a reason and next step.
- **SC-002**: With source and destination services available, an eligible source
  change is imported, verified, and available to consumers within 6 hours,
  without manual copy initiation.
- **SC-003**: A verified eligible candidate is validated and committed to
  `main` within 1 hour without a PR or human action; a healthy canary adopts it
  within 30 minutes afterward. If the documented PR fallback is required, the
  1-hour target applies to PR creation, merge follows required checks and
  approvals automatically, and the deployment target starts at merge.
- **SC-004**: Acceptance demonstrates one stable major-version change and one
  same-tag rebuild end to end without per-update human action on the direct-bot
  path. Two subsequent unchanged checks create zero duplicate commits and zero
  unnecessary workload changes.
  A separate isolated canary with real verified upstream releases may prove
  the major-version case. Missing release samples leave this criterion open
  without preventing independent recovery drills; both remain required for
  feature completion.
- **SC-005**: Incomplete copies, missing required architectures, denied source
  or repository access, and out-of-track releases produce zero deployed image
  changes and identify the failing stage within one scheduled check.
- **SC-006**: Every migrated workload passes its documented functional check.
  A stateless failure drill automatically restores the retained working digest
  within 30 minutes of failure detection without human action on the direct-bot
  path and blocks the failed digest across two further automation checks.
  Unsafe or unknown stateful rollback cases and failed rollback cases pause
  further affected-application
  updates and deliver an operator alert within 5 minutes of detection, with
  zero automatic image reverts or data restores after those conditions arise.
- **SC-007**: Review and acceptance find zero exposed credentials, zero
  restricted images made public, zero writes outside the authorized bot
  exception, and zero enrolled images with competing update owners. Failed
  validation and a stale candidate revision both block direct writes to `main`.

## Assumptions

- This invocation produces the specification only. Catalog assessment, final
  image selection, implementation, and live migration occur in later phases.
- The 6-hour import and 1-hour validated-commit targets are initial defaults.
  Human approval time is excluded only when the documented PR fallback applies.
- Direct bot writes are the user's explicit exception to the repository's
  normal PR workflow for routine image updates. The permission change itself
  remains repository-owned and reviewed; this specification does not change
  GitHub settings or grant the bot authority to expand its own permissions.
- Use available Chainguard access; no new subscription or paid entitlement is
  assumed. Missing access is a documented exception, not an automatic purchase.
- Enrolled workloads follow the newest accessible stable release across major
  boundaries by default. "Routine image update" includes a stable major upgrade
  that passes the declared checks; it does not include unrelated configuration
  changes or an unimplemented data migration. Release stability must be verified
  rather than inferred from the word `latest` alone.
- Automatic recovery covers image reverts with verified data compatibility.
  Data restore and recovery from unsafe or unknown compatibility require an
  operator. The 30-minute recovery and 5-minute alert targets assume repository,
  deployment, registry, and notification services are available; an unavailable
  dependency must appear as the blocking failure when observable.
- Platform components are assessed alongside applications. Coupled release,
  bootstrap, or restore constraints must be evidenced as exceptions rather
  than silently excluded. Rebuilding custom application images is out of scope.
- Existing Harbor, Argo CD, protected repository delivery, and managed secret
  services are dependencies. Restore a working Image Updater credential
  contract; retired credentials are not assumed usable.
- Existing public mirror and private custom-image access boundaries remain
  constraints. Required authenticated destinations and consumer credentials must
  be declared before restricted Chainguard images can be enrolled.
- No ingress redesign, storage backend replacement, cluster-wide admission
  controller, or Talos/Kubernetes upgrade is required by this feature.

### Existing Context and Sources

Repository inspection found manual reviewed digest publication and retired Image
Updater desired state. Live deployment status and Chainguard entitlements were
not inspected during specification.

- [Harbor delivery and publication gate](../../docs/harbor-image-mirroring.md)
  defines current verified-copy and publish-before-consume requirements.
- [Image Updater retirement](../../docs/argocd-image-updater.md) records failed
  write permissions, stale selectors, and current Renovate ownership.
- [Chainguard Harbor integration](https://edu.chainguard.dev/chainguard/containers/registry/pull-through-guides/harbor/)
  documents scheduled registry replication.
- [Image Updater strategies](https://argocd-image-updater.readthedocs.io/en/stable/basics/update-strategies/)
  distinguishes version selection from tracking a mutable tag's digest.
- [Image Updater write-back](https://argocd-image-updater.readthedocs.io/en/stable/basics/update-methods/)
  documents direct Git updates, signing, and a pull-request fallback.
  Planning must verify these capabilities against the selected release.
