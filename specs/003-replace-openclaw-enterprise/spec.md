# Feature Specification: Replace OpenClaw with OpenClaw Enterprise

**Feature Branch**: Existing detached checkout; no branch created.

**Created**: 2026-10-17

**Status**: Revised for fresh replacement during planning.

**Input**: "Replace openclaw with openclaw enterprise."

**Scope clarification, 2026-10-17**: After learning that upstream cannot preserve
Embedded Discord and private LiteLLM without source changes, the owner said:
"That's fine. Just bring down the existing openclaw instance and replace with the
new." This supersedes the original continuity-first draft. Install a fresh stock
Enterprise instance and agent; stop the standalone instance. Preserve old data for
recovery, without importing its personality, history, jobs, channels, or tools.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Use the new Enterprise assistant (Priority: P1)

As the owner, I want to open Enterprise privately and use a fresh managed agent.

**Why this priority**: A healthy management console alone is not a replacement.

**Independent Test**: Sign in, open the new agent's native interface, send a
request using a separately configured supported model credential, and verify the
response and active revision.

**Acceptance Scenarios**:

1. **Given** a ready installation, **When** the owner opens the existing stable
   OpenClaw address, **Then** it leads to the authenticated Enterprise interface.
2. **Given** a configured supported model and credential, **When** the owner sends
   a request, **Then** the fresh agent responds and the operator can identify the
   active revision and any model failure.
3. **Given** an unauthorized identity, **When** it attempts console, native agent,
   workspace, or credential access, **Then** access is denied.

### User Story 2 - Stop the old assistant without losing recovery data (Priority: P1)

As the owner, I want the old instance stopped while retaining the option to
recover its private data or restore service if replacement fails.

**Why this priority**: Replacement does not imply permission to delete personal
history, credentials, or recovery archives.

**Independent Test**: Verify a complete archived copy, stop the old workload
through its declared workflow, and prove it produces no new writes or deliveries.

**Acceptance Scenarios**:

1. **Given** an inventory of local runtime and NAS state, **When** the old instance
   is quiesced, **Then** a verified final archive covers both stores and retained
   historical checkpoints without exposing their contents publicly.
2. **Given** a verified archive, **When** replacement activates, **Then** the old
   gateway, schedules, and delivery integrations remain stopped and the new agent
   starts with fresh state.
3. **Given** replacement failure, **When** reviewed recovery runs, **Then** the old
   instance can resume from compatible retained state after the replacement is
   stopped; new Enterprise state is retained separately.

### User Story 3 - Establish supported platform prerequisites (Priority: P1)

As the operator, I want a supported platform and enforced workload isolation
before deploying Enterprise.

**Why this priority**: Version compatibility and declared policies alone do not
prove safe operation.

**Independent Test**: Verify actual node/component versions, then run positive,
negative, startup, and restart network tests on an isolated canary and each
subsequent rollout stage.

**Acceptance Scenarios**:

1. **Given** a reviewed upgrade sequence and recovery copies, **When** platform
   upgrades finish, **Then** every node and affected platform component meets the
   selected Enterprise version's support requirements.
2. **Given** the enforcing dataplane, **When** allowed and forbidden traffic is
   tested, **Then** required application/recovery paths work and forbidden private
   or cross-agent access fails, including during Pod and enforcer startup/restart.
3. **Given** insufficient capacity or failed policy tests, **When** deployment is
   evaluated, **Then** it stops before activation rather than weakening isolation
   or displacing unrelated workloads.

### User Story 4 - Operate and recover the replacement (Priority: P2)

As the operator, I want installation, upgrades, backups, and retirement to follow
repeatable reviewed workflows.

**Why this priority**: The replacement must remain maintainable after first boot.

**Independent Test**: Repeat setup, deploy one agent revision, restore a backup in
isolation, and verify that a failed upgrade does not start incompatible writers.

**Acceptance Scenarios**:

1. **Given** committed configuration, **When** setup repeats, **Then** it retains
   the same installation, agent identity, and permissions without duplicate grants.
2. **Given** an upgrade requiring data migration, **When** it runs, **Then** old
   writers stop before migration and resume only after successful validation.
3. **Given** successful acceptance and 24 hours of observation, **When** obsolete
   resources are retired, **Then** only Enterprise remains active while retained
   data, shared services, and recovery access remain intact.

### Edge Cases

- Console is healthy but there is no running agent or usable model credential.
- A create/deploy response is lost: recover identity before retrying.
- Backup spans local databases and NAS files: neither alone counts as complete.
- Old writer does not terminate or its node is unreachable: handoff stops.
- Policies become effective on unrelated workloads: audit and stage enforcement.
- Image, database migration, native UI cookie, or WebSocket validation fails:
  keep activation blocked and retain failed-state evidence privately.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Deploy stock Enterprise with one fresh Embedded OpenClaw agent;
  verify a real model response separately from console readiness. Story 1.
- **FR-002**: Preserve the stable private browser entrypoint through an
  authenticated redirect; protect console and per-agent native access. Story 1.
- **FR-003**: Inventory, quiesce, archive, and stop standalone OpenClaw through
  repository-owned workflows before replacement activation. Preserve its retained
  volumes, full archives, and historical checkpoints. Story 2.
- **FR-004**: Do not import old assistant state, schedules, Discord integration,
  LiteLLM routing, or custom tools. Do not transfer old service credentials to the
  new agent automatically. Stories 1 and 2.
- **FR-005**: Configure a supported model using a distinct declared credential
  contract and explicit model selection before inference acceptance. A missing
  credential MUST block that check, not trigger reuse of unrelated credentials.
  Story 1.
- **FR-006**: Upgrade required platform components through a supported, ordered
  repository-owned path with per-stage validation and recovery gates. Story 3.
- **FR-007**: Enforce the selected release's network-policy boundary, audit all
  affected existing policies, and prove required traffic and forbidden access
  during startup, steady state, and restart. Story 3.
- **FR-008**: Validate per-node capacity, storage, private routing, secret delivery,
  and recovery before activation. An existing-node canary may use reviewed,
  source-owned workload relocation or pauses only with verified recovery,
  declared outages, and fresh capacity and placement receipts. Never lower
  security or evict Pods ad hoc to pass a readiness gate. Story 3.
- **FR-009**: Keep installation, agent provisioning, revision changes, cutover,
  upgrades, and retirement in reviewed repository workflows. Retry ambiguous
  operations without duplicating resources. Story 4.
- **FR-010**: Keep secrets, raw backups, and personal data out of public source
  and logs. Separate operator, migration, and agent permissions. Stories 1 and 4.
- **FR-011**: Stop database writers before schema changes; verify a full restore
  before production use. Retain failed/new state before rollback. Story 4.
- **FR-012**: Retire obsolete active resources only after functional acceptance
  and 24 hours of observation. Data deletion needs separate authorization.
  Record updated ownership, operation, and recovery instructions. Story 4.

### Key Entities *(include if feature involves data)*

- **Enterprise installation**: Management, identity, configuration, and audit state.
- **Fresh agent/revision**: New assistant identity and deployed configuration.
- **Legacy recovery archive**: Verified copy of old local/NAS state and metadata.
- **Platform maintenance stage**: Pinned target versions, node order, and receipts.
- **Acceptance receipt**: Revision-bound results without secrets or private content.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Three consecutive authenticated browser/native-agent conversations
  succeed; tested unauthorized console and agent access attempts all fail.
- **SC-002**: Every inventoried old state root is covered by a verified recoverable
  copy; the stopped old instance produces zero new writes or deliveries.
- **SC-003**: All selected-version platform prerequisites and all required network
  positive/negative/lifecycle tests pass before Enterprise activation.
- **SC-004**: A second setup run creates zero duplicate agents, credentials, or
  grants; one staged revision deployment and isolated backup restoration succeed.
- **SC-005**: After 24 hours of successful observation, one authoritative new
  assistant remains active; required shared-service and recovery checks still pass.

## Assumptions

- The owner's clarification accepts a fresh assistant and loss of continuity with
  the old integrations. No Enterprise controller/runtime fork is planned.
- Downtime is acceptable, including stopping the old workload to reclaim its own
  resources after archiving. This does not authorize changes to unrelated apps or
  hardware purchases.
- No old credentials are repurposed. Provider access is an explicit external
  prerequisite; installation can be staged without claiming inference works.
- Private access, IaC/GitOps, secret delivery, storage, and backup infrastructure
  remain dependencies. Broader cluster hardening is outside this replacement.
- The unfilled constitution template adds no policy; repository `AGENTS.md` applies.

### Source Context

- [Enterprise source](https://github.com/openclaw/openclaw-enterprise/tree/33bb74590a749f37934da4502fca6035cd234a55),
  including its stock channel, egress, and upgrade constraints.
- [Current OpenClaw runbook](../../clusters/homelab/apps/openclaw/README.md) and
  [storage](../../clusters/homelab/platform/storage/openclaw-runtime.yaml).
- [Research and dated evidence](research.md) records prerequisites and decisions.
