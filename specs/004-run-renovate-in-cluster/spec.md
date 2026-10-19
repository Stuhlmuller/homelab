<!-- markdownlint-disable MD013 -->
# Feature Specification: Run Renovate in the Homelab

**Feature Branch**: Existing detached checkout; no branch created.
**Created**: 2026-10-18
**Status**: Draft
**Input**: "Add renovate to the homelab. We already run renovate as a github action, but I want to convert it to a kubernetes deployment to run it more often. Cache the package versions as much as possible. Run renovate as often as necessary."

## Clarifications

### Session 2026-10-18

- Q: Which repositories should the cluster Renovate runner scan? → A: Automatically discover all repositories owned by the configured GitHub owner.
- Q: Which GitHub account or organization should Renovate use to discover repositories? → A: Stuhlmuller.
- Q: What should Renovate do when it discovers a repository with no Renovate configuration? → A: Apply a shared policy and start updates immediately.
- Q: How often should Renovate scan all Stuhlmuller repositories? → A: Every hour.
- Q: Should the cluster runner preserve the current auto-merge policy? → A: Yes; preserve it subject to repository protection rules.

## Scope and Outcome Definitions

- An **eligible repository** is a non-archived public or private repository owned by Stuhlmuller, including an owned fork. Archived repositories are recorded as skipped. The existing Renovate GitHub App must have the access needed to propose updates to every eligible repository; missing access is a coverage gap that blocks cutover, not a silent exclusion.
- The App installation must cover all eligible owned repositories and automatically cover newly owned repositories. Inventory parity is checked before cutover and when ownership changes. Removing a repository from Stuhlmuller stops its scans on the next successful discovery cycle.
- An **eligible version** is a release visible from a healthy dependency source that the effective Renovate policy permits proposing. An **explicit deferral** is a recorded policy reason and timestamp for waiting, such as a configured schedule or minimum release age. A registry outage or failed lookup is a failure, not a deferral.
- A **healthy measurement period** excludes documented cluster maintenance and confirmed GitHub or package-source outages; excluded hourly slots and source intervals are reported. A repository scan may succeed, fail, or be skipped with a reason; one repository failure does not erase the outcomes of others.
- The **version cache** includes package-release lookups and other rebuildable Renovate metadata; GitHub repositories, open pull requests, and policy files remain the durable sources of truth. Cache entries follow Renovate's documented refresh and hard-expiry rules, and private cache contents receive the same access protection as restricted logs.
- The release-latency sample is fixed before measurement with a reproducible selection seed. It covers each dependency datasource class in the eligible repository baseline and public/private sources where present. A read-only observer records the last healthy upstream poll without a release and first healthy poll with it; GitHub records proposal or timestamped deferral. Controlled canary releases are reported separately, so they cannot dominate the sampled latency rate. Fewer than ten independently observed eligible releases, zero releases, or ambiguous timing make the seven-day latency result inconclusive rather than passing.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Get frequent dependency proposals (Priority: P1)

As the owner, I want Renovate to discover and scan all repositories owned by Stuhlmuller from the cluster throughout the day so eligible updates reach normal pull-request review promptly.

**Why this priority**: Faster discovery is the reason to move the runner.

**Independent Test**: Complete one cluster scan, verify it discovers the owner's repositories, applies the shared policy plus any repository overrides, records each result, and creates or updates an eligible reviewable proposal. Any merge follows the effective policy and repository protection rules.

**Acceptance Scenarios**:

1. **Given** a healthy cluster and valid repository access, **When** an hourly scan is due, **Then** one discovery cycle scans each eligible owned repository and records its outcome; archived repositories are skipped with a reason.
2. **Given** an eligible new version, **When** the next successful scan completes, **Then** Renovate creates or updates a pull request under the existing policy.
3. **Given** a scan still in progress, **When** another scan is due, **Then** a second scan does not run concurrently.
4. **Given** a newly discovered repository with no Renovate file, **When** its first scan completes, **Then** it receives eligible update pull requests under the shared policy without an onboarding pull request.

---

### User Story 2 - Reuse version data without hiding updates (Priority: P1)

As the operator, I want package version lookups reused between scans, including after runner replacement, so frequent scans avoid needless upstream requests.

**Why this priority**: Repeating cold lookups every hour wastes time and increases rate-limit failures.

**Independent Test**: Compare two scans of unchanged repositories, restart the runner between them, and verify cache reuse while a newly available version remains discoverable after normal refresh.

**Acceptance Scenarios**:

1. **Given** a completed scan, **When** the next scan starts, **Then** it can reuse persisted version lookup data.
2. **Given** a runner restart or replacement, **When** it scans again, **Then** the prior cache remains usable without operator repair.
3. **Given** cached data past its refresh point, **When** the next scan checks it, **Then** the result is revalidated so new releases can be found.
4. **Given** a missing or corrupt cache, **When** a scan starts, **Then** Renovate rebuilds it and still reports the outcome.

---

### User Story 3 - Cut over and operate safely (Priority: P2)

As the operator, I want one write-capable Renovate runner, protected credentials, and visible failures so migration creates neither duplicate proposals nor silent gaps while preserving the current merge policy.

**Why this priority**: The existing review workflow and public-repository secret boundary must survive migration.

**Independent Test**: Identify the current runner, prove a full cluster dry run preserves discovery, planned proposals, App identity, and merge policy, delete the old workflow through its declared configuration, drain its runs, and retire its repository Actions private key before verifying that the cluster runner is the sole write-capable schedule.

**Acceptance Scenarios**:

1. **Given** the current runner remains active, **When** the cluster runner is introduced, **Then** the old schedule is retired only after a successful cluster scan and review-policy check.
2. **Given** a scan failure or expired credential, **When** the run ends, **Then** the operator can see its cause without secret values.
3. **Given** existing open Renovate pull requests, **When** ownership moves, **Then** they remain usable without duplicates and retain the current auto-merge policy subject to repository protection rules.

### Edge Cases

- An upstream registry or repository API is unavailable or rate-limited: the run records the failure, uses cached data only within Renovate's normal freshness/expiry rules, and retries at the next scheduled time. Hard-expired data cannot silently count as a fresh result.
- An individual repository fails while others succeed: retain its failure reason and retry it in the next hourly discovery cycle without discarding the other outcomes.
- The cluster, cache, or credential source is unavailable, the cache is full/corrupt, or App token minting fails: the run fails visibly and can recover without manual state mutation. Credential rotation is verified by a later run.
- A scan reaches its deadline before the one-hour App token expires: it stops without another writer starting and retries at the next hourly slot.
- A discovery cycle exceeds its interval: no overlapping run may write competing proposals or cache data.
- A repository is added to or removed from Stuhlmuller's account: the next successful discovery cycle updates its scan set without manual registration.
- A discovered repository has its own Renovate policy: its repository settings take effect alongside the shared policy under Renovate's normal precedence rules.
- The companion workflow cannot be retired after dry-run parity: keep the cluster runner in dry-run or suspend it through reviewed desired state; do not enable cluster writes.
- The current GitHub Actions runner is not found in this checkout: locate its actual owner before cutover; the separate image-automation workflow is not Renovate.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The homelab MUST schedule Renovate at the start of each UTC hour, with a 15-minute late-start limit, and automatically discover all eligible repositories owned by Stuhlmuller. It MUST expose missed scheduled cycles, including those in which no run starts.
- **FR-002**: Runs MUST apply the committed shared Renovate policy to all repositories, honor each repository's committed overrides under Renovate's normal precedence rules, and process repositories without their own file under the shared policy. The homelab repository's policy includes digest pinning, vulnerability-alert updates, lockfile maintenance, and package exclusions.
- **FR-003**: Runs MUST create or update pull requests for eligible changes and preserve the existing auto-merge policy without bypassing repository validation, approval, or branch protection rules.
- **FR-004**: Runs MUST prevent overlapping discovery cycles and concurrent scans of the same repository, including when an hourly slot arrives during a slow scan.
- **FR-005**: Version lookup data MUST persist across runs and runner replacement; valid entries MUST be reused, entries refreshed or expired under Renovate's documented cache-freshness rules, and hard-expired data MUST NOT hide new releases indefinitely. A confirmed cache hit for an unchanged datasource MUST distinguish reuse from a merely quiet run.
- **FR-006**: Cache loss, corruption, or volume exhaustion MUST be recoverable by a later run without losing repository state or requiring manual cluster changes; an unavailable volume MUST fail visibly.
- **FR-007**: The existing GitHub App identity and any private registry credentials needed for parity with the legacy runner MUST use the homelab's declared secret path, be limited to the owner and required repository/package operations, and remain absent from committed files and ordinary logs. No new private registry integration is required beyond existing-runner parity; access gaps block cutover.
- **FR-008**: Each run MUST expose its scheduled/start/completion times, duration, completion state, per-repository outcome, and actionable failure class (credential, GitHub API, package source, cache/storage, or policy) to the operator. Restricted logs may identify private repositories but MUST NOT reveal tokens, keys, or private package data in public output. A missed cycle in which no run starts MUST also become visible within one hour.
- **FR-009**: Migration MUST identify the existing runner in Stuhlmuller/renovate and retire its entire workflow, including scheduled and manual triggers, only after a successful full cluster dry run verifies owner coverage, equivalent planned changes, App identity, existing PR continuity, and effective auto-merge policy. After the last legacy run finishes, the workflow MUST be deleted through a reviewed companion change; its absence and the absence of every unfinished legacy run MUST be verified. The repository Actions private key MUST then be retired through a guarded procedure; its current-main receipt MUST prove the cluster credential is ready and the old key is absent before cluster writes are enabled through reviewed desired state. If deletion, drainage, or key retirement cannot complete, cluster writes MUST remain disabled. Exactly one writer MUST operate per repository at any time; rollback restores the legacy workflow only after cluster writes and unfinished new-run executions stop, the Actions key is restored through a guarded path, and its receipt is verified.
- **FR-012**: Each successful discovery cycle MUST add newly owned eligible repositories and stop scanning repositories no longer owned by Stuhlmuller. Missing App access for an otherwise eligible owned repository MUST be reported as a coverage gap and block cutover.
- **FR-013**: A discovered repository without its own Renovate policy MUST receive eligible update pull requests under the shared policy without an onboarding pull request.
- **FR-010**: The runner MUST have no public inbound endpoint, cluster API write credential, or GitHub permission outside the existing App installation's required owner-repository operations.
- **FR-011**: Operator documentation MUST explain schedule, cache rebuild, credentials, failure diagnosis, verification, and rollback through declared code paths.

### Key Entities

- **Discovery cycle**: A scheduled attempt to find owned repositories and scan each eligible repository, with timing and outcome per repository.
- **Version cache**: Reusable package and release lookup data with freshness rules; replaceable operational state.
- **Update proposal**: A reviewable change produced or maintained under the existing policy.
- **Runner credential**: Protected access needed to read dependency sources and maintain proposals.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Over seven healthy days, at least 95% of planned hourly UTC slots begin a discovery cycle within 15 minutes, with no overlaps. Report both the planned-slot denominator and excluded outage/maintenance slots.
- **SC-002**: Over seven healthy days, at least 95% of independently observed eligible releases in the preregistered stratified sample appear in a reviewable proposal or timestamped policy deferral within four hours of their conservative last-absent upstream poll. Report the sampled denominator, timing brackets, proposal/deferral times, excluded intervals, and inconclusive cases; do not claim a fleet-wide 95% rate from this sample.
- **SC-003**: Two consecutive scheduled scans by separate runner instances sharing retained cache data show a confirmed version-lookup cache hit for the same unchanged package. A newly published test version becomes discoverable after normal cache refresh.
- **SC-004**: A failed run, per-repository failure, or missed hourly cycle in which no run starts is visible to the operator within one hour; the next scheduled run can succeed after the underlying issue is resolved.
- **SC-005**: After cutover, exactly one writer maintains proposals for each eligible repository; existing open proposals retain the prior App author and follow the prior auto-merge policy and repository protection rules.
- **SC-006**: Before cutover, the runner can access every eligible owned repository and can automatically cover newly owned repositories. A controlled ownership-change test adds a config-free repository and later removes it; each next simulated successful cycle reflects the changed set without an onboarding PR. The first real ownership transition remains an operational follow-up and is not claimed as live acceptance evidence until observed.

## Assumptions

- The owner selected an hourly schedule; any later change to it requires a reviewed desired-state update.
- Scope is all repositories owned by Stuhlmuller, discovered automatically. Repository settings merge with or override the committed shared policy under Renovate's normal precedence rules; the existing auto-merge policy remains in scope.
- The existing runner is in the separate Stuhlmuller/renovate repository; its workflow and global config are the parity baseline. The checked-in image-automation workflow belongs to a separate updater.
- Cache data is replaceable and needs no backup, but it must survive ordinary scheduled runs and runner replacement.
- The cluster's declared deployment, storage, secret-management, and image-publication paths are available. Cache contents, mounted credentials, and restricted logs may contain private metadata; public planning artifacts contain only safe names and contracts.
