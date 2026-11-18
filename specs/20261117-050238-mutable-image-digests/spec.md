# Feature Specification: Mutable References and Automatic Image Digests

**Feature Branch**: `codex/mutable-image-digests`

**Created**: 2026-11-16

**Status**: Implementation in progress — provider ownership correction verified

**Input**: User description: "/goal Reconfigure the argocd image updater. Do not configure versions in code. Do not bypass branch protection to merge code. I will specify a mutable branch or mutable tag in code, you handle updating the hash. Add ignore_changes to argocd apps in terraform so the deployments to not redeploy old versions."

## Clarifications

### Session 2026-11-16

These are agent decisions from repository evidence and the user's stated scope,
not additional statements attributed to the user.

- **Selector changes**: A reviewed change of tag or branch remains authoritative.
  Once the new selector is reconciled and successfully resolved, its content
  replaces the previous effective value within two successful update intervals.
  Registration must not suppress the selector change or clear unrelated fields.
  Evidence: the shared Application module owns source inputs, while the request
  delegates only hash maintenance.
- **Enrollment boundary**: No fleet-wide enrollment or replacement channels are
  inferred. The current Harbor catalog contains two `not-enrolled` candidate
  consumers, so it supplies no existing enrollment to silently activate. A new
  enrollment requires an explicit application/image/selector mapping in code.
- **Pause versus removal**: Pausing an enrolled image retains its effective hash
  and stops subsequent automatic changes. Removing enrollment transfers control
  back only through a documented declarative change that replaces or clears its
  obsolete override; no ad hoc live patch is an accepted transition.
- **Acceptance scope**: Shared registration behavior must cover both source
  forms and supported image override types. It must be proven against the actual
  provider's state behavior, including an unrelated apply after a digest update,
  rather than inferred from the presence of an `ignore_changes` declaration.
  Controller registration, activation, and target enrollment are separate states;
  planning must identify the exact prerequisites for each without reviving the
  older catalog migration as a prerequisite for this bounded feature.

### Provider-evidence correction — 2026-11-16

These decisions follow actual provider 3.2.1 request/state tests and the live
Application schema; they do not attribute new instructions to the user.

- **Controller-only overrides**: Enrolled Applications must omit their runtime
  image override collections from desired registration configuration entirely.
  An empty or preseeded collection is not equivalent to an absent collection.
  Owners declare mutable tags in workload values/Kustomization and the explicit
  enrollment selector; automation creates the effective override. Existing
  configured overrides require a reviewed transition under their current owner
  before enrollment; this change does not silently migrate them.
- **Intentional multi-source edits**: The Application schema treats a multi-source
  list as one ownership unit. An active registration edit to that list may reject
  safely rather than force an older image. The supported procedure is a paused
  handoff: reconcile pause; temporarily return to ordinary registration with
  runtime overrides still absent and the intended source edit; then reenroll.
  The provider test preserves the effective image through this handoff without
  writing its hash into source, replacing the Application, or weakening active
  conflict protection. Single-source edits outside the image collection, ordinary
  metadata/destination edits, and enrollment selector changes keep their normal
  behavior.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Follow the selected mutable reference (Priority: P1)

As the homelab owner, I declare the branch or image tag I want to follow once.
Automation resolves subsequent image content changes to immutable hashes without
requiring release-number or hash edits in my application configuration.

**Why this priority**: The current paused proposal-based updater does not provide
the requested separation between declared update channel and resolved content.

**Independent Test**: Configure a supported application with a mutable image tag,
change the content behind that tag, and observe a new resolved deployment hash
without a change to the declared tag or a commit containing that hash.

**Acceptance Scenarios**:

1. **Given** an enrolled image tag resolves to digest A, **When** it resolves to
   digest B, **Then** automation updates the effective image to B and leaves the
   declared tag unchanged.
2. **Given** the tag still resolves to A, **When** automation checks again,
   **Then** it does not create a new deployment or source commit.
3. **Given** an application follows a repository branch, **When** that branch
   advances, **Then** the branch remains the declared source reference and the
   reconciler records the resolved commit without requiring a committed SHA.

---

### User Story 2 - Preserve automation-owned content during infrastructure updates (Priority: P1)

As an operator, I can apply application registration or unrelated infrastructure
changes without restoring an older image selected before the updater ran.

**Why this priority**: Competing ownership can undo updates and redeploy old
content even when the automation successfully selected the current digest.

**Independent Test**: Start with a controller-selected digest B and older
registration state A; plan and apply an unrelated application metadata change.
Verify that B survives and the requested metadata change takes effect.

**Acceptance Scenarios**:

1. **Given** an updater-owned image override differs from registration state,
   **When** Terraform/OpenTofu plans or applies the Application, **Then** its
   lifecycle ignores preserve the updater-owned value.
2. **Given** a reviewed change to repository URL, source path, declared branch,
   destination, or synchronization settings, **When** registration reconciles,
   **Then** that change remains effective rather than being hidden by broad
   ignores. Multi-source list edits may require the documented paused ownership
   handoff, preserving the effective image without copying its hash into code.
3. **Given** either a single-source or a multi-source application, **When** its
   supported image overrides change, **Then** the same ownership rule holds.

---

### User Story 3 - Keep source delivery protected and recovery understandable (Priority: P1)

As the owner, I can trust that this automation does not bypass repository branch
protection and can see which content is selected and how to pause or recover it.

**Why this priority**: Hash automation must not depend on privileged writes to
protected branches or silently relax existing delivery protections.

**Independent Test**: Inspect the automation's write destinations and exercise
negative checks for protected-reference writes; verify the documented pause and
recovery procedures through the repository's supported paths.

**Acceptance Scenarios**:

1. **Given** a new digest is available, **When** automation updates an enrolled
   application, **Then** it neither writes directly to protected branches nor
   requires privileged bypass or changes to branch protection.
2. **Given** a configuration change needs merging, **When** it is delivered,
   **Then** normal protected pull-request checks and merge rules apply.
3. **Given** a registry lookup fails or an image is unavailable, **When** an
   update is attempted, **Then** the existing effective image remains intact
   and the failure is visible without exposing credentials.

### Edge Cases

- A tag is deleted, authentication fails, or a registry returns invalid content:
  preserve the last effective image and surface the failure.
- A mutable tag moves backwards to older content: follow the explicitly selected
  tag's content; do not invent semantic version ordering.
- Several sources or images exist: update only enrolled image identities and
  preserve unrelated source fields and image parameters.
- The owner changes the declared branch or tag: the new reference must take
  effect; stale overrides must not permanently defeat that change.
- An enrolled Application already declares an empty or seeded runtime image
  override collection: reject enrollment until a reviewed ordinary-registration
  transition removes that configured collection; do not silently import it.
- An intentional multi-source edit conflicts with controller ownership: reject
  the active apply and use the documented paused handoff, never a forced active
  overwrite or a copied hash in code.
- An Application or updater is recreated: documented reconciliation must restore
  the selected reference's current digest; historical resolved hashes are not
  silently treated as desired versions.
- An application cannot express an image override: reject or leave it explicitly
  unenrolled, rather than claiming it is updated.
- An immutable dependency outside the enrolled workload scope remains necessary
  for reproducible tooling: do not turn this into an unrelated repository-wide
  dependency unpinning exercise.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Owners MUST declare mutable workload channels, not recurring release
  versions or resolved image hashes, for applications enrolled by this change.
- **FR-002**: Automation MUST resolve each selected image tag to its current
  immutable digest and update the effective application image without committing
  each digest to application source.
- **FR-003**: Git branch references MUST remain owner-declared branches; ordinary
  source reconciliation owns resolved commit identification. Image updates MUST
  NOT substitute Git commit hashes for image digests or change branches.
- **FR-004**: Application registration MUST use lifecycle `ignore_changes` for
  updater-owned image fields so an ordinary apply cannot restore an old digest.
- **FR-005**: The ownership boundary MUST preserve reconciliation of unrelated
  fields and intentional owner changes, including declared source references.
  Intentional multi-source list edits MAY require a documented paused ownership
  handoff; that handoff MUST preserve the effective image and Application identity
  without requiring a resolved hash in committed configuration. Active conflicting
  applies MUST fail without forcing old image values.
  A changed selector MUST replace its previous effective content within two
  successful update intervals after the new selector is reconciled and resolved.
- **FR-006**: Both supported single-source and multi-source Application forms
  MUST be covered, including their supported image override forms.
- **FR-007**: Image automation MUST NOT directly update protected Git references,
  bypass branch protections, force-push, or weaken required checks. Configuration
  delivery MUST use the normal protected pull-request process.
- **FR-008**: Failed or unchanged resolutions MUST leave the current effective
  image intact without unnecessary deployment changes; failures MUST be visible.
- **FR-009**: Enrolled targets MUST have one image-update owner. Existing image
  update automation and policy MUST not revert the selected runtime digest or
  require a conflicting committed version for those targets.
- **FR-010**: The change MUST document enrollment, pause, reference changes,
  recreation, verification, and recovery through declared repository paths.
  Pause MUST retain the last effective digest. Removal MUST define a declarative
  handoff that removes or replaces stale overrides without manual live mutation.
- **FR-011**: The deliverable MUST distinguish source validation, controller
  registration and activation, and verified runtime behavior. Missing runtime
  prerequisites MUST be recorded as specific blockers rather than reported as
  working automation.
- **FR-012**: Existing credentials and secret references MUST remain protected;
  this change MUST NOT commit secrets or bypass deployment access controls.
- **FR-013**: Enrollment MUST require an explicit application, image identity,
  and owner-selected mutable tag in committed configuration; an absent mapping
  MUST NOT enroll unrelated applications or historical migration candidates.
  Runtime image override collections MUST be absent from desired Application
  registration at enrollment; reject empty or seeded collections. Owner-selected
  tags remain in workload source and the enrollment input. Existing configured
  overrides require an explicit reviewed transition before enrollment.

### Key Entities

- **Declared reference**: An owner-selected Git branch or container image tag.
- **Resolved content**: The immutable commit or image digest identified from a
  declared reference; each belongs to its corresponding resolver.
- **Enrollment**: The explicit relationship between an Application, an image,
  its declared tag, and the fields delegated to image automation.
- **Ownership boundary**: Fields retained by registration versus image values
  maintained by the updater.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A controlled A-to-B image publication results in B becoming the
  effective image within two successful configured update intervals, with zero
  application source commits and no change to the owner-selected tag.
- **SC-002**: An unrelated registration change after that update preserves B in
  both supported source forms, with zero reversions to A.
- **SC-003**: Negative checks reject every tested protected-reference write or
  bypass path; existing branch protection remains unchanged.
- **SC-004**: Unchanged and failed registry resolutions produce zero unnecessary
  image changes; failed resolution remains observable.
- **SC-005**: The owner can identify the declared reference, current resolved
  image, and pause/recovery procedure for every enrolled target from maintained
  configuration and operating documentation.
- **SC-006**: A declared selector change takes effect within two successful
  update intervals after reconciliation and resolution, and a paused enrollment
  produces zero automatic digest changes until resumed.
- **SC-007**: A paused multi-source edit handoff preserves the current effective
  image and Application identity across temporary ordinary registration and
  reenrollment, with zero resolved hashes added to source. Active conflicting
  source-list edits fail without changing the effective image.

## Assumptions

- Scope is Image Updater and the Application ownership needed to support mutable
  references. Unrelated chart, provider, action, and platform version upgrades
  are excluded. The user has not selected new tags for existing applications;
  implementation must not invent release channels for the entire fleet.
- The phrase "mutable branch or mutable tag" describes source-specific inputs:
  Git sources follow branches; image sources follow registry tags. No custom
  Git-branch-to-image build service is requested.
- Existing Git branch reconciliation already provides commit resolution. The
  missing behavior is image digest ownership and protection from registration
  rollback, not a second Git revision updater.
- Existing registry access and declared deployment paths are reused. New
  credentials or wider access require the existing authorization process.
- A source-only demonstration cannot establish runtime acceptance. If no
  operator-selected compatible target exists, the configuration and validation
  can be completed while enrollment/runtime verification remains explicitly open.
