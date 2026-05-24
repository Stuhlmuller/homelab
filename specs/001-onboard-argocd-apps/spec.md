# Feature Specification: Argo CD Application Onboarding

**Feature Branch**: `001-onboard-argocd-apps`
**Created**: 2026-05-24
**Status**: Draft
**Input**: User description: "Onboard Istio, external-secrets, certificates-manager, grafana, prometheus, openclaw, tines, radarr, sonarr, deluge. All should be onboarded using argocd, and added to argocd using modules from the terragrunt catalog. dependencies must be explicitly stated in the terragrunt. Plan input also adds descheduler, tailscale, and litellm to Argo CD onboarding. Follow-up input enables autosync by default and adds Argo CD Image Updater."

## Clarifications

### Session 2026-05-24

- Q: What ingress exposure policy should the first rollout enforce? → A: All apps are tailnet-only by default, with future explicitly documented webhook paths as the only public exception.
- Q: Which component should provide reverse-proxy ingress, and what DNS constraint matters most? → A: Use Istio as the reverse proxy; do not require DNS record changes after initial configuration.
- Q: How should internal and public routes be reachable without DNS churn? → A: Internal routes must be reachable on the Tailscale tailnet; public webhook paths must be exposed through Tailscale Funnel.
- Q: Which Tailscale Funnel paths are in scope for the first rollout? → A: No public Funnel paths in the first rollout.
- Q: Which backend should External Secrets use for runtime secret material? → A: AWS SSM Parameter Store.
- Q: Which persistent storage class should stateful apps use? → A: Add an NFS-backed StorageClass and make it the default.
- Q: Should this feature install the NFS provisioner or use an existing one? → A: Use the existing NFS provisioner and add the default StorageClass only.
- Q: How should the implementation determine the existing NFS provisioner details? → A: Use read-only cluster inspection, then commit the observed provisioner details into desired state.
- Q: What backup readiness is required before stateful apps are considered ready? → A: Require documented NFS backup coverage before relying on stateful app data.
- Q: What sync policy should Argo CD applications use by default? → A: Enable automated prune and self-heal by default; readiness gates remain documented operational checks.
- Q: How should image updates be automated? → A: Install Argo CD Image Updater through Argo CD and keep updates opt-in through Application labels and annotations.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Register platform add-ons through GitOps (Priority: P1)

As the homelab operator, I want the shared platform add-ons registered through
Argo CD from repository-owned desired state so the cluster can be rebuilt and
reviewed without manual application creation.

**Why this priority**: Istio, external secrets, certificate management,
Prometheus, Grafana, descheduler, Tailscale, and Argo CD Image Updater are shared foundations for
traffic, credentials, certificates, visibility, scheduling hygiene, ingress,
reachability, image maintenance, and later application delivery.

**Independent Test**: Review the planned repository state and confirm that each
platform add-on has an Argo CD registration, a declared owning path, and an
explicit dependency relationship before rollout.

**Acceptance Scenarios**:

1. **Given** a clean checkout and the documented homelab prerequisites, **When**
   an operator reviews the app onboarding plan, **Then** Istio,
   external-secrets, certificates-manager, prometheus, grafana, descheduler,
   tailscale, and argocd-image-updater are all present as Argo CD managed
   applications.
2. **Given** the platform add-on registrations, **When** their Terragrunt
   entries are reviewed, **Then** dependencies are stated explicitly so
   consumers cannot be introduced before required secret, certificate,
   observability, Istio reverse-proxy, Tailscale reachability, or storage
   foundations.

---

### User Story 2 - Register homelab services consistently (Priority: P2)

As the homelab operator, I want OpenClaw, Tines, Radarr, Sonarr, Deluge, and
LiteLLM registered through the same Argo CD and Terragrunt catalog pattern so
services use one reviewable delivery model.

**Why this priority**: The user-facing and automation workloads should not
drift into one-off deployment paths once the platform foundation exists.

**Independent Test**: Review the service registrations independently from live
rollout and confirm that each service has a stable application identity,
non-secret configuration inputs, and documented runtime implications.

**Acceptance Scenarios**:

1. **Given** the platform add-ons are represented in desired state, **When** the
   service app registrations are reviewed, **Then** OpenClaw, Tines, Radarr,
   Sonarr, Deluge, and LiteLLM are all represented as Argo CD managed
   applications.
2. **Given** a service requires credentials, persistent data, tailnet ingress,
   future Funnel webhook exposure, or shared media paths, **When** its desired
   state is reviewed, **Then** those requirements are documented as safe
   references, non-secret defaults, or explicit public path decisions rather
   than committed private material.

---

### User Story 3 - Operate, validate, and recover the onboarding (Priority: P3)

As a future operator or learner, I want the onboarding to explain validation,
rollback, storage, and failure behavior so I can apply or revert the change
without guessing at live cluster state.

**Why this priority**: These applications include stateful and security-sensitive
components; the repository must teach the operational pattern, not just declare
objects.

**Independent Test**: Follow the documented validation and rollback guidance
without applying live changes and confirm it covers every onboarded app.

**Acceptance Scenarios**:

1. **Given** a reviewer has no live cluster access, **When** they read the
   feature documentation, **Then** they can identify the validation commands,
   expected review outputs, rollback order, and known storage or secret risks.
2. **Given** a rollout must be backed out, **When** the operator follows the
   documented rollback path, **Then** shared foundations are removed or disabled
   only after dependent applications are handled and persistent data handling is
   explicit.

### Edge Cases

- A requested application has no suitable catalog module available at planning
  time.
- A dependency would create a cycle, such as observability depending on an app
  that itself requires observability to become healthy.
- Secret references exist before the external secret backend is reachable.
- AWS SSM Parameter Store parameters are missing, named incorrectly, or
  inaccessible to the External Secrets controller.
- Certificate or ingress resources are declared before the certificate manager
  or Istio reverse-proxy entry point is ready.
- A future webhook route needs public reachability while the rest of the
  application UI and API remain tailnet-only.
- Tailnet routing or Tailscale Funnel is unavailable while Argo CD reports the
  underlying application healthy.
- Descheduler policy is too aggressive and would evict critical or
  storage-sensitive pods.
- LiteLLM provider credentials or model routing configuration are missing from
  AWS SSM Parameter Store.
- Prometheus or Grafana persistent data cannot bind to the expected storage
  class.
- The NFS-backed default StorageClass is missing, not marked default, or cannot
  provision volumes for stateful applications.
- The existing NFS provisioner is absent, renamed, or incompatible with the
  default StorageClass this feature adds.
- Read-only inspection discovers provisioner details that are unsafe for a
  public repository, such as private hostnames or sensitive export paths.
- NFS backup coverage is undocumented, unverified, or excludes application data
  before stateful applications are ready to roll out.
- Radarr, Sonarr, and Deluge need shared download or media paths but the storage
  and backup behavior is not yet documented.
- An app already exists in the cluster outside Argo CD ownership.
- A live rollout leaves one application unhealthy while its dependencies remain
  healthy.
- Argo CD Image Updater is enabled for an application without the required
  image annotations or without a documented write-back method.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The onboarding MUST include exactly these requested applications:
  Istio, external-secrets, certificates-manager, grafana, prometheus, openclaw,
  tines, radarr, sonarr, deluge, descheduler, tailscale, litellm, and
  argocd-image-updater.
- **FR-002**: Each requested application MUST be represented as an Argo CD
  managed application with a stable application name, target namespace, owning
  repository path, and non-secret inputs sufficient for review.
- **FR-003**: Each requested application MUST be added to Argo CD through a
  reusable module sourced from the Terragrunt catalog.
- **FR-003a**: Supporting Kubernetes platform desired state required by the
  requested applications, including the default NFS StorageClass, MAY be
  registered as a supporting Argo CD Application and MUST NOT be counted as one
  of the 14 requested applications.
- **FR-004**: Each Terragrunt application entry MUST state its dependencies
  explicitly; implicit ordering based on file names, directory order, or manual
  operator memory is not acceptable.
- **FR-005**: The dependency graph MUST ensure external-secrets and
  certificates-manager are available before applications that require runtime
  secrets or certificates.
- **FR-006**: The dependency graph MUST ensure Istio is available before any
  application exposure, reverse-proxy route, or mesh behavior that relies on
  Istio.
- **FR-007**: The dependency graph MUST ensure Prometheus is available before
  Grafana integrations that rely on Prometheus data.
- **FR-008**: The dependency graph MUST ensure Deluge availability is explicit
  before Radarr or Sonarr download-client integration is considered enabled.
- **FR-009**: The ingress design MUST avoid requiring DNS record additions or
  edits after the initial DNS configuration is complete.
- **FR-010**: The dependency graph MUST ensure Tailscale is available before
  tailnet-only application reachability or future Tailscale Funnel exceptions
  are considered enabled.
- **FR-011**: Descheduler policy MUST be documented with safeguards that avoid
  evicting critical control-plane, storage, or single-replica stateful
  workloads unintentionally.
- **FR-012**: LiteLLM MUST use AWS SSM Parameter Store references for provider
  credentials and model routing secrets, with no committed plaintext provider
  keys.
- **FR-013**: No requested application may require manual creation in the Argo CD
  UI or one-off live Kubernetes edits for steady-state operation.
- **FR-014**: Secret material MUST NOT be committed; application credentials,
  API keys, tokens, private certificates, and private hostnames must be modeled
  only as safe AWS SSM Parameter Store references or external runtime inputs.
- **FR-015**: The onboarding MUST document whether each requested application
  needs persistent storage, backup coverage, restore instructions, and data
  preservation during rollback.
- **FR-016**: The onboarding MUST add an NFS-backed Kubernetes StorageClass that
  uses the existing NFS provisioner and mark it as the default StorageClass for
  the cluster unless a future change explicitly replaces the default.
- **FR-017**: Stateful applications MUST use the default NFS-backed StorageClass
  unless an app-specific exception documents the reason, storage class, backup
  behavior, and rollback behavior.
- **FR-018**: The onboarding MUST NOT install, replace, or otherwise take
  ownership of the NFS provisioner; if the expected provisioner is unavailable,
  rollout must stop and record the missing prerequisite.
- **FR-019**: The implementation MUST use read-only cluster inspection to
  discover the existing NFS provisioner name and non-secret StorageClass
  parameters before committing the default StorageClass desired state.
- **FR-020**: Observed NFS provisioner details MUST be committed only when safe
  for the public repository; unsafe private values must be replaced with
  documented placeholders or safe references before review.
- **FR-021**: Stateful applications MUST NOT be considered production-ready
  until NFS backup coverage is documented for the default StorageClass and
  mapped to each stateful workload's restore expectations.
- **FR-022**: Each requested application MUST be tailnet-only in the first
  rollout, with zero public Tailscale Funnel paths enabled.
- **FR-023**: Future public reachability MUST be allowed only through Tailscale
  Funnel for explicitly documented webhook paths that name the owning
  application, public path, purpose, and rollback behavior.
- **FR-024**: The onboarding MUST include validation guidance that can be run
  before live mutation, including desired-state planning, rendered Kubernetes
  review, and Argo CD health or sync expectations.
- **FR-025**: The onboarding MUST include rollback guidance that preserves the
  dependency order and calls out persistent data implications.
- **FR-026**: Argo CD Application registrations MUST enable automated prune and
  self-heal by default unless a future exception is explicitly documented in the
  app registration and operations runbook.
- **FR-027**: Argo CD Image Updater MUST be installed through an Argo CD
  Application registered by Terragrunt, and image automation MUST require
  explicit per-Application opt-in labels and annotations.

### Infrastructure and Delivery Requirements *(mandatory for homelab changes)*

- **IAC-001**: Every persistent infrastructure or cluster change MUST identify
  the repository path that owns the desired state for each requested
  application.
- **IAC-002**: External infrastructure changes MUST identify the
  Terragrunt/OpenTofu entry point and how the change preserves the documented
  one-command-from-scratch apply path, or explicitly state that no external
  infrastructure is affected.
- **IAC-003**: Kubernetes runtime changes MUST be delivered through Argo CD
  application desired state that is registered from Terragrunt catalog modules.
- **IAC-004**: Requirements MUST state whether secrets, persistent storage,
  ingress, backup, restore, or rollback behavior are affected for each
  requested application.
- **IAC-005**: Requirements MUST avoid permanent manual live-state changes; any
  break-glass behavior MUST include the repository backfill requirement.
- **IAC-006**: Desired-state inputs MUST be committed as non-secret code or data.
  Environment variables MUST be limited to CI/CD credential or secret injection
  and MUST NOT become normal operator inputs.

### Key Entities

- **Application Onboarding**: A requested homelab application registered for
  Argo CD ownership, including its name, namespace, source, sync expectations,
  and operational notes.
- **Terragrunt Application Entry**: The catalog-backed desired-state entry that
  adds one application to Argo CD and declares the inputs reviewers can inspect.
- **Dependency Edge**: An explicit relationship stating that one application or
  prerequisite must exist before another application is registered, synced, or
  considered ready.
- **Runtime Secret Reference**: A safe AWS SSM Parameter Store parameter
  reference that points to secret material supplied outside the public
  repository.
- **Stateful Workload Profile**: The storage, backup, restore, and rollback data
  expectations for an application that persists cluster data.
- **Default StorageClass**: The NFS-backed Kubernetes StorageClass that uses the
  existing NFS provisioner and is marked as the default target for stateful
  application persistent volumes.
- **Ingress Exposure Policy**: The decision for whether an application has no
  ingress, tailnet-only internal ingress, or an explicitly scoped public webhook
  path exposed through Tailscale Funnel, including the Istio reverse-proxy
  dependency that must satisfy that exposure.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reviewer can identify all 14 requested applications and their
  owning desired-state paths in under 5 minutes from the feature documentation
  and Terragrunt entries.
- **SC-002**: Pre-rollout review shows 14 requested Argo CD application
  registrations plus any explicitly named supporting Argo CD registrations, and
  zero undeclared dependency relationships among them.
- **SC-003**: Secret scanning and repository review find zero committed tokens,
  private keys, raw certificates, kubeconfigs with credentials, or private
  service credentials introduced by this onboarding.
- **SC-004**: 100% of runtime secret references use AWS SSM Parameter Store as
  the External Secrets backend and have documented parameter names or paths.
- **SC-005**: 100% of requested applications have documented tailnet ingress,
  zero first-rollout Tailscale Funnel public paths, and persistent-storage
  decisions before live rollout.
- **SC-006**: Pre-rollout review shows one NFS-backed Kubernetes StorageClass
  using the existing NFS provisioner and marked as default, and 100% of stateful
  application storage profiles either use it or document an approved exception.
- **SC-007**: StorageClass review includes read-only inspection evidence for
  the existing NFS provisioner and zero unsafe private provisioner values
  committed to the public repository.
- **SC-008**: Before any stateful application is considered ready, NFS backup
  coverage is documented and every stateful workload profile maps its
  persistent data to a restore expectation.
- **SC-009**: After rollout, all 14 requested applications reach the documented
  Argo CD sync and health expectation within 30 minutes, or any exception is
  recorded with an operator action and rollback decision.
- **SC-010**: Rollback documentation covers all 14 requested applications and
  preserves dependency order so dependent services are handled before shared
  foundations are removed or disabled.
- **SC-011**: After initial DNS setup, onboarding a new tailnet-only app route
  or Tailscale Funnel public webhook path requires zero DNS record changes.
- **SC-012**: First-rollout review finds zero public Tailscale Funnel paths
  enabled across all requested applications.

## Assumptions

- The request name `certificates-manager` refers to the Kubernetes certificate
  management application commonly operated as cert-manager.
- Argo CD itself is already bootstrapped, or this feature depends on the
  existing Argo CD bootstrap work being completed before these app registrations
  are applied.
- The Terragrunt catalog contains, or will contain before implementation is
  complete, reusable modules suitable for registering Argo CD applications.
- No live cluster mutation is part of the specification phase; rollout happens
  only after planning, implementation, and validation.
- Istio is the reverse proxy for this onboarding, and tailnet-only internal
  exposure is required for all applications in the first rollout.
- Initial DNS configuration is expected to support future application routes
  without per-app DNS record additions or edits.
- Tailscale is the reachability layer for this onboarding: internal application
  access occurs on the tailnet, and any future public webhook exceptions are
  exposed via Tailscale Funnel.
- External Secrets uses AWS SSM Parameter Store as the backend for runtime
  secret material.
- NFS storage is the persistent storage foundation for this onboarding. An NFS
  provisioner already exists outside this feature's ownership and must be
  discovered through read-only inspection and referenced by the default
  Kubernetes StorageClass before stateful applications are considered ready.
- NFS backup coverage exists or will be documented as a prerequisite before
  stateful applications are considered ready.
- Runtime credentials for OpenClaw, Tines, Grafana, Radarr, Sonarr, Deluge,
  LiteLLM, Tailscale, and any integration endpoints are supplied through
  approved secret-management paths rather than committed plaintext.
