# Feature Specification: Homelab uptime monitoring

**Feature Branch**: `codex/uptime-kuma`

**Created**: 2026-11-16

**Status**: Clarified; planning pending

**Input**: User description: "/goal Deploy uptime-kuma to the homelab and configure to track uptime of all homelab apps"

**Issue**: [#1847](https://github.com/Stuhlmuller/homelab/issues/1847)

**Tracking**: [Notion task](https://app.notion.com/p/41be535fc6288136935bf601083debf5?pvs=204)

## Clarifications

### Session 2026-11-16

The following are agent decisions grounded in repository evidence, not answers
attributed to the user. No user questions were necessary.

- **Scope**: Inventory app registrations and their owned services, not every
  individual Pod, transient Job or backup helper as a separate app. Supporting
  controllers may use existing workload-health signals with explicit meaning.
  Evidence: app onboarding inventory and Grafana's existing workload rules.
- **Health semantics**: Reused monitoring signals must identify the expected
  workload and reject absent or stale observations. Monitoring-system uptime or
  a generic healthy registration is not proof of target health. Evidence:
  Grafana README distinguishes scrape availability, workload replicas, database
  probes and scheduled backup freshness.
- **Private access**: Preserve current private mesh ingress and native app
  authentication. Source Traefik README/routes describe the current direct
  private app route; older onboarding prose naming Octelium as the default is
  not the current ordinary-app routing contract. Concrete wiring belongs in plan.
- **Bootstrap**: Initialize the owner account from a generated managed secret
  without exposing a public first-user setup window or printing credentials.
  Existing accounts must not be reset on reconciliation. Evidence: secret
  contracts skill and Grafana's managed admin secret pattern.
- **Lifecycle ownership**: Repository-owned monitors retain stable identities;
  retirement pauses them and preserves history. User-created monitors remain
  untouched. Source updates reconcile owned settings, and fail visibly on an
  ambiguous identity rather than adopt unrelated data.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See homelab availability (Priority: P1)

As the homelab owner, I can open Uptime Kuma through the established private
access path and see which active applications are available and their recent
uptime, without creating each monitor manually.

**Why this priority**: A running monitor with complete coverage is the requested
outcome; installing an empty dashboard does not satisfy it.

**Independent Test**: Sign in, compare the dashboard's configured monitors with
the reviewed inventory, and observe at least three successive checks for every
active monitor.

**Acceptance Scenarios**:

1. **Given** the deployed monitoring service, **When** the owner opens its private
   address, **Then** authentication protects its administration and the owner can
   view monitor status, last observation and uptime history.
2. **Given** an active application inventory, **When** configuration is applied,
   **Then** every active app has a named monitor or an explicitly linked shared
   service monitor that meaningfully represents its availability.
3. **Given** an existing unhealthy app, **When** checks run, **Then** the dashboard
   records its failure without falsely claiming the deployment repaired it.

### User Story 2 - Trust failure and recovery reports (Priority: P1)

As the owner, I can distinguish a working application from an unreachable app,
a login gateway, an intentionally stopped app, and an unobserved interval.

**Why this priority**: A dashboard that treats a login redirect as app health or
hides coverage gaps gives false assurance.

**Independent Test**: Use a controlled disposable target to observe success,
failure and recovery; inspect the definition and observations for protected
applications and non-web services.

**Acceptance Scenarios**:

1. **Given** a healthy controlled target, **When** it becomes unavailable and then
   recovers, **Then** both transitions appear within three minutes each.
2. **Given** a protected application, **When** only its login gateway responds,
   **Then** that response alone does not establish application availability.
3. **Given** a staged, retired or intentionally suspended app, **When** the owner
   reviews coverage, **Then** its exclusion or paused state and reason are visible
   in the inventory; monitoring does not activate it.
4. **Given** a service without a normal web page, **When** its monitor is inspected,
   **Then** the documented check demonstrates the relevant service availability
   and states any limitation compared with a complete user transaction.

### User Story 3 - Keep monitoring reproducible and durable (Priority: P2)

As the owner, I can redeploy and maintain monitoring from the homelab's normal
configuration, preserving history and knowing how to recover it.

**Why this priority**: Repeatable configuration and retained data prevent the
initial setup from becoming an undocumented one-off.

**Independent Test**: Reapply identical configuration and restart the monitoring
service through its declared workflow, verify stable monitor identities and
retained observations, then validate a backup using isolated recovery.

**Acceptance Scenarios**:

1. **Given** existing configured monitors, **When** unchanged desired state is
   reapplied, **Then** no duplicate monitors are created and existing history is
   preserved.
2. **Given** recorded observations, **When** the service is routinely replaced,
   **Then** its account, monitor definitions and available history remain intact.
3. **Given** a backup, **When** recovery is tested in isolation, **Then** the
   restored monitor definitions and history are usable without modifying the
   running service or exposing its credentials.
4. **Given** a newly registered homelab app, **When** the inventory check runs,
   **Then** missing coverage fails validation until a monitor or justified
   lifecycle disposition is added.

### Edge Cases

- Apps deliberately scaled to zero, suspended scheduled jobs, retired resources,
  staged registrations and temporary recovery/canary workloads need explicit
  dispositions; absence is not silently interpreted as healthy.
- Supporting services may share an owning application's monitor only when its
  documented check actually covers that service; an application inventory entry
  must never vanish merely because it has no public URL.
- DNS, TLS, authentication and network failures must appear as failed or unknown
  observations, not success; check limitations must be documented.
- Monitoring cannot observe its own complete cluster outage. Missing intervals
  must not be represented as measured uptime; external independent monitoring is
  outside this deployment's scope.
- Failed configuration reconciliation must be visible and preserve the last
  usable monitor configuration rather than partially deleting unrelated data.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Deploy Uptime Kuma as an operational homelab service with owner
  authentication and the established private access boundary; no new public
  status page or anonymous administrative access.
- **FR-002**: Record a complete coverage inventory reconciling repository app
  registrations, declared app lifecycles and observed live apps. Every entry
  MUST identify its monitor(s), shared coverage justification, or explicit
  staged/retired/suspended disposition and source evidence. Inventory units are
  app registrations and owned services; transient Pods, Jobs and backup helpers
  are not independent apps solely because they are Kubernetes resources.
- **FR-003**: Configure active app monitors automatically from versioned desired
  state, using stable identities and repeatable reconciliation that does not
  duplicate monitors, erase history or overwrite unrelated user-created data.
  Retired owned monitors are paused with history retained; ambiguous identities
  fail visibly instead of adopting an unrelated monitor.
- **FR-004**: Select meaningful app-level health checks where available; otherwise
  document the narrower service signal. Login redirects or generic access-denied
  responses MUST NOT be counted as proof of backend health. Reused support
  health signals MUST select the expected workload, describe what they prove,
  and fail on absent or stale observations; fresh telemetry alone is not proof
  of a healthy target. A signal is stale after two expected observation periods
  unless its explicitly documented scheduled-work threshold applies.
- **FR-005**: Check continuously operating apps at least once per minute and
  reflect sustained failure and recovery within three minutes. Scheduled work
  MUST instead have a documented freshness threshold derived from its schedule.
- **FR-006**: Display current state, last check, response timing where supported,
  and historical uptime. Preserve at least 30 days of observations after that
  much runtime; acceptance need not wait 30 days.
- **FR-007**: Persist accounts, monitor definitions and history across routine
  replacement; document storage ownership, backup frequency, retention,
  recovery limitations and rollback, and prove one isolated backup restore.
- **FR-008**: Use the existing repository delivery and secret-management paths.
  No credential values may enter public source, logs or acceptance receipts.
- **FR-009**: Restrict monitoring access to the targets and permissions needed by
  its checks; do not weaken existing authentication or access boundaries merely
  to make a monitor green.
- **FR-010**: Add a validation check that rejects unclassified app inventory
  entries and invalid/duplicate monitor identities, and document app onboarding
  and intentional retirement behavior.
- **FR-011**: Verify deployed source identity, owner access, configured coverage,
  repeated live observations, controlled failure/recovery, repeat reconciliation
  and retained state. Report existing target failures separately from monitoring
  deployment failures; do not claim all apps healthy without observations.
- **FR-012**: Preserve existing Prometheus/Grafana and alerting behavior. New
  notification channels, public status pages, external probes and unrelated app
  repairs are excluded unless separately requested.

### Key Entities

- **Inventory entry**: Application identity, lifecycle, evidence, owning service,
  monitor relationship and justified exclusions.
- **Monitor**: Stable identity, target, check meaning, cadence, expected healthy
  result, ownership and credential reference when needed.
- **Observation**: Timestamp, availability state, optional response time and
  diagnostic information without secrets.
- **Recovery evidence**: Backup identity, capture time, isolated restore result
  and limits of the recovered data.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of inventoried apps have a verified coverage disposition and
  100% of active apps have an enabled meaningful monitor or justified shared
  coverage; no unexplained gaps remain.
- **SC-002**: The owner can authenticate and see at least three consecutive
  observations for every enabled continuously operating app monitor.
- **SC-003**: A controlled target's outage and recovery each appear within three
  minutes, without interrupting an existing app.
- **SC-004**: Repeated configuration and one routine service replacement create
  zero duplicate monitors and preserve pre-existing observations and access.
- **SC-005**: One isolated restore successfully recovers monitor definitions and
  recorded history; retention is configured for at least 30 days.
- **SC-006**: An intentionally unclassified app fails the coverage validation,
  while the complete committed inventory passes.
- **SC-007**: Unauthorized users cannot administer the service, and the final
  report distinguishes failed targets and unobserved time from measured uptime.

## Assumptions

- The homelab owner is the initial administrator; existing private ingress and
  secret conventions determine the technical design during planning. Initial
  setup uses a generated managed owner credential, closes the first-user setup
  path before user access, and never resets an existing owner on reconciliation.
- “All homelab apps” includes active user applications and supporting services,
  but does not authorize reactivating intentionally stopped/staged deployments.
  Repository and live state will be reconciled rather than trusting dashboard
  health labels alone.
- Monitoring is in the existing homelab and shares its outage domain. No external
  service purchase, new notification recipient or public exposure is implied.
- A 60-second cadence and 30-day history are conservative initial defaults;
  bounded schedule-derived freshness checks cover scheduled services.
- Existing unrelated outages may remain visible as down; fixing those apps is
  not a prerequisite to proving that their monitors report truthfully.
