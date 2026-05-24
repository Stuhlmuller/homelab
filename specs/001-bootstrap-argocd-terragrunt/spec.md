# Feature Specification: Bootstrap Argo CD With Terragrunt

**Feature Branch**: `001-bootstrap-argocd-terragrunt`
**Created**: 2026-05-24
**Status**: Draft
**Input**: User description: "bootstrap argocd into argocd using terragrunt. run `terragrunt catalog` and get the scaffolding for the module from the terragrunt-catalog repo."

## Clarifications

### Session 2026-05-24

- Q: After bootstrap, which system owns Argo CD steady-state configuration? → A: Terragrunt seeds the initial Argo CD install and self-management application; Argo CD owns steady-state Argo CD configuration after handoff.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Bootstrap Argo CD From Repo State (Priority: P1)

As a homelab operator, I need a clean Terragrunt-driven bootstrap path that
installs Argo CD and registers Argo CD's own desired state from this repository,
so the cluster can move from first install to self-management without manual
live configuration.

**Why this priority**: The cluster cannot use Argo CD as the normal delivery
mechanism until Argo CD exists and has a repo-owned application that represents
its own ongoing desired state.

**Independent Test**: Starting from a cluster with documented prerequisites
available, follow the bootstrap runbook and confirm the declared Terragrunt
entry point installs Argo CD, creates the self-management application, and leaves
the repo as the durable source of truth.

**Acceptance Scenarios**:

1. **Given** a clean cluster with the documented Kubernetes access and public
   prerequisites, **When** the operator runs the documented Terragrunt bootstrap
   path, **Then** Argo CD is installed into the declared namespace and a
   repo-owned Argo CD application exists for Argo CD itself.
2. **Given** the bootstrap has completed, **When** the operator inspects Argo CD
   desired state, **Then** the Argo CD self-management application points at this
   repository and has no required operator-supplied environment-variable inputs.

---

### User Story 2 - Continue Managing Argo CD Through Argo CD (Priority: P2)

As a homelab operator, I need Argo CD to own its steady-state configuration
after bootstrap, so future Argo CD changes follow the same GitOps review and
reconciliation workflow as other Kubernetes runtime changes.

**Why this priority**: The bootstrap is only useful if it hands off to the
long-term operating model instead of leaving Argo CD as a one-off installation.

**Independent Test**: Change a safe, visible Argo CD desired-state setting in a
review branch, preview the change, and confirm the resulting application can be
synced back to the declared repo state without manual cluster edits.

**Acceptance Scenarios**:

1. **Given** Argo CD is installed and the self-management application is
   registered, **When** the desired state changes in the repository, **Then**
   Argo CD detects the changed desired state and can reconcile itself from git.
2. **Given** a live Argo CD resource drifts from the repository definition,
   **When** reconciliation runs, **Then** the drift is reported or corrected
   according to the documented sync policy.

---

### User Story 3 - Recover Safely From Bootstrap Problems (Priority: P3)

As a homelab operator, I need clear validation, rollback, and recovery guidance
for the bootstrap handoff, so partial installation or self-management mistakes
can be diagnosed without inventing live fixes.

**Why this priority**: Self-managing delivery systems have sharp edges; the
runbook must make recovery boring before the first real outage.

**Independent Test**: Review the runbook and confirm it names the expected
healthy states, failed states, rollback path, and repository backfill steps for
partial bootstrap or emergency live intervention.

**Acceptance Scenarios**:

1. **Given** the initial Argo CD install succeeds but the self-management
   application fails, **When** the operator follows the recovery section, **Then**
   the operator can identify whether the issue is missing CRDs, bad repo path,
   credentials, or invalid desired state.
2. **Given** a break-glass live change is required, **When** the emergency is
   resolved, **Then** the runbook requires the durable fix to be captured in
   repository code before the work is considered complete.

### Edge Cases

- The Argo CD application resource is applied before Argo CD CRDs are available.
- The pinned catalog module version changes or becomes unavailable.
- An existing manual Argo CD installation is present and differs from the new
  repository-owned desired state.
- Repository access requires credentials or deploy keys that cannot be committed.
- Bootstrap succeeds partially, leaving Argo CD installed but not self-managed.
- A self-management sync policy could delete or overwrite Argo CD resources if
  the declared source path is wrong.
- Re-running the bootstrap after convergence must not create duplicate Argo CD
  resources or require manual cleanup.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST define a Terragrunt-driven bootstrap path that
  installs Argo CD and registers Argo CD's own desired state from this
  repository.
- **FR-002**: The bootstrap path MUST use the configured
  `terragrunt-catalog` repository pinned to version `0.3.0` and MUST NOT depend
  on repository-local OpenTofu modules.
- **FR-003**: The bootstrap path MUST preserve the project goal of standing up
  the homelab from a clean checkout with one documented Terragrunt apply path
  after public prerequisites, provider credentials, and external secret material
  are available.
- **FR-003a**: Terragrunt MUST be limited to the initial seed path for Argo CD
  installation and self-management registration; after successful handoff, Argo
  CD MUST own steady-state Argo CD configuration from repository desired state.
- **FR-004**: The Argo CD installation MUST be created before any Argo CD
  application resource that depends on Argo CD CRDs.
- **FR-005**: The Argo CD self-management application MUST point to a
  repo-owned desired-state path for Argo CD and MUST define the target cluster,
  namespace, sync behavior, and validation expectations.
- **FR-006**: The feature MUST avoid raw secrets in git and MUST keep repository
  credentials, deploy keys, tokens, and private values outside committed files.
- **FR-007**: Desired-state inputs MUST be committed as non-secret code or data;
  environment variables MUST be limited to CI/CD credential or secret injection
  and MUST NOT be required for local operator input.
- **FR-008**: The bootstrap runbook MUST document prerequisites, apply command,
  expected healthy state, verification commands, rollback, and recovery from
  partial bootstrap.
- **FR-009**: The implementation MUST include validation steps for the
  Terragrunt/OpenTofu configuration and the Kubernetes desired state before any
  live rollout.
- **FR-010**: The feature MUST document how emergency live changes are backfilled
  into repository code before the change is complete.

### Infrastructure and Delivery Requirements *(mandatory for homelab changes)*

- **IAC-001**: Persistent desired state MUST be owned by repository paths for the
  Terragrunt bootstrap and the Argo CD-managed Kubernetes configuration.
- **IAC-002**: External infrastructure changes MUST identify the
  Terragrunt/OpenTofu entry point and show how the change preserves the
  documented one-command-from-scratch apply path.
- **IAC-003**: Kubernetes runtime changes MUST start with Terragrunt bootstrap
  only where Argo CD cannot yet manage itself, then hand steady-state ownership
  of Argo CD configuration to Argo CD through repo-owned desired state.
- **IAC-004**: The feature MUST state whether secrets, persistent storage,
  ingress, backup, restore, or rollback behavior are affected; the default
  assumption is no public ingress and no committed secrets.
- **IAC-005**: The feature MUST avoid permanent manual live-state changes; any
  break-glass behavior MUST include the repository backfill requirement.
- **IAC-006**: Requirements MUST define desired-state inputs as committed
  non-secret code or data. Environment variables MUST be limited to CI/CD
  credential or secret injection and MUST NOT be used as normal operator inputs.

### Key Entities

- **Bootstrap Stack**: The repo-owned Terragrunt entry point that performs the
  first Argo CD installation and creates the initial self-management handoff.
- **Argo CD Self-Management Application**: The Argo CD application that points
  back to this repository and owns Argo CD's steady-state configuration.
- **Catalog Module Source**: The catalog-discovered module source selected from
  the configured `terragrunt-catalog` repository and pinned for reproducible
  use.
- **Bootstrap Runbook**: The operator-facing documentation for prerequisites,
  apply, validation, rollback, and recovery.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new operator can identify the single documented Terragrunt
  bootstrap entry point and required prerequisites within 5 minutes of reading
  the runbook.
- **SC-002**: From a cluster meeting the documented prerequisites, the bootstrap
  path can install Argo CD and register the self-management application in one
  operator workflow without manual live resource edits.
- **SC-003**: Within 10 minutes of bootstrap completion, Argo CD reports its
  self-management application as present and reconcilable from repository state.
- **SC-004**: Re-running the bootstrap after convergence produces no duplicate
  Argo CD installation or self-management application resources.
- **SC-005**: Static review of the changed files finds zero raw secrets and zero
  normal operator inputs sourced from environment variables.
- **SC-006**: The rollback and recovery guidance lets an operator identify the
  next action for at least the documented partial-install, missing-CRD,
  credential, and bad-repo-path failure modes.

## Assumptions

- Argo CD will be installed into an `argocd` namespace unless planning discovers
  a repo-local convention that supersedes this default.
- The catalog-selected module for the bootstrap is the Helm release module,
  discovered from the configured catalog as
  `git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/helm-release?ref=0.3.0`.
- Initial installation may require Terragrunt to create Argo CD before Argo CD
  can manage itself; after that handoff, steady-state changes are GitOps-owned.
- Repository access for Argo CD will use safe references or CI/CD-injected
  secrets when credentials are required.
- No public ingress is required for the initial bootstrap unless a later plan
  explicitly adds and documents it.
