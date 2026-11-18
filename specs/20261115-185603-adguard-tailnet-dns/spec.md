# Feature Specification: AdGuard Tailnet DNS

**Feature Branch**: `feat/adguard-tailnet-dns`

**Created**: 2026-11-15

**Status**: Deployed; unlocked-tailnet acceptance amendment in specification; functional acceptance and DNS cutover pending

**Input**: "deploy adguard to the homelab, create a Tailscale ingress for that service, then use that dns server for the Tailscale dns so I don’t get ads while using the tailnet"

[Tracking issue](https://github.com/Stuhlmuller/homelab/issues/1842) ·
[Notion record](https://app.notion.com/p/419e535fc62881a394d0e752ab2a4264)

## Clarifications

### Session 2026-11-15

These are agent-resolved decisions from repository evidence, not new user answers.

- Q: Which DNS behavior must remain compatible? → A: Preserve the existing
  private-domain resolver and MagicDNS. General queries use AdGuard; private
  queries sent directly to AdGuard must still use the private resolution path
  without public fallback. An IPv4 tailnet endpoint may answer both A and AAAA
  queries; a second IPv6 transport endpoint is not required for this scope.
- Q: Which configuration survives replacement and recovery? → A: Repository-owned
  desired state and private credential references govern deployment. The UI is
  for authenticated inspection; persistent changes follow the declared delivery
  path. Restore evidence must recover that effective configuration and usable
  credentials, not merely show that a backup file exists.
- Q: What proves normal client use? → A: At least one authorized connected
  client accepting Tailscale DNS must pass system-resolver acceptance with
  cache effects controlled and its OS, client version and exit-node mode recorded.
  Direct server queries and cloud CI checks alone cannot satisfy this criterion.
  Existing exit-node behavior is additionally tested when accessible; absence
  of access is reported as unverified, never counted as passing.
- Q: How is readiness distinguished from an indefinitely stalled resolver?
  → A: Bound direct DNS acceptance queries to three seconds with no hidden
  retries, matching the existing homelab DNS checker. Record failure and block
  cutover when a required query misses the deadline. This is an acceptance
  bound, not an availability or capacity service-level guarantee.

### Session 2026-11-17: owner correction

- Owner statement: “tailnet lock is disabled on my tailnet by the way”.
- The owner runs Mac checks locally; the cloud agent cannot connect to that Mac.
- AdGuard acceptance must respect the existing Lock mode without changing it.
  An unlocked tailnet still requires verified endpoint identity and access;
  it cannot truthfully produce evidence of a Tailnet Lock signature.

### Session 2026-11-17: amendment clarification

The following decisions are agent-resolved from existing acceptance and cutover
behavior, not additional owner statements.

- Lock mode is an observed prerequisite, not an option to skip verification.
  Neither absent observations nor an operator override can select unlocked mode.
- An unlocked peer is authenticated through the existing tailnet connection and
  matched to the declared Kubernetes proxy; it is not described as signed.
- Mode and identity must remain consistent throughout direct acceptance and the
  final pre-apply check. A changed observation requires fresh acceptance rather
  than reuse of a prior receipt. This does not claim protection against an
  undetectable change after the final observation.
- Existing rollback remains independent of AdGuard health and signing readiness;
  restoring captured prior DNS policy must remain possible during resolver failure.
- This fix changes only AdGuard acceptance and its instructions. Enabling Lock,
  enrolling a signer, migrating OAuth to workload federation, and changing other
  ingress signing workflows are outside this amendment.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Resolve names with ad filtering (Priority: P1)

As the homelab owner, I want AdGuard Home to answer DNS queries from my tailnet
and block domains on its enabled ad-blocking lists while allowing normal browsing.

**Why this priority**: Filtering is the requested benefit and must work before
other clients depend on this resolver.

**Independent Test**: Query AdGuard directly from an authorized tailnet client
using both UDP and TCP. Compare an enabled-list blocked domain, a permitted
public domain, a nonexistent domain, and private homelab names.

**Acceptance Scenarios**:

1. **Given** a healthy resolver with an enabled filter containing the test domain,
   **When** that domain is queried over UDP or TCP, **Then** it receives the
   configured blocking response rather than its public destination address.
2. **Given** a permitted public name, **When** either DNS transport is used,
   **Then** a valid answer is returned without a forwarding loop.
3. **Given** the running service is replaced through the normal delivery path,
   **When** it becomes ready, **Then** its configured filtering and administrator
   access remain available without repeating first-run setup.

### User Story 2 - Filter ordinary tailnet client traffic (Priority: P1)

As a tailnet user, I want my device's normal DNS lookups to use AdGuard while
connected, without entering a resolver address for each application.

**Why this priority**: A working server alone does not change client behavior.

**Independent Test**: Inspect effective tailnet DNS settings, then use a connected
client's normal system resolver to check blocking and successful ordinary,
private homelab, and MagicDNS lookups. Repeat with an existing exit node when
one is available and authorized for testing.

**Acceptance Scenarios**:

1. **Given** AdGuard has passed direct resolver acceptance, **When** tailnet DNS
   is switched, **Then** clients accepting Tailscale DNS use the filtering
   resolver for general DNS even when the local network advertises another one.
2. **Given** the existing private-name routing and MagicDNS configuration,
   **When** the global resolver changes, **Then** approved private names and
   tailnet device names retain their expected answers.
3. **Given** a configured exit-node client, **When** it uses the tailnet DNS
   policy, **Then** general DNS remains filtered and private names resolve.
4. **Given** no application-specific DNS bypass, **When** a known blocked domain
   is resolved through the client's normal resolver, **Then** it is blocked;
   no parallel unfiltered global resolver can silently bypass the policy.

### User Story 3 - Administer AdGuard privately (Priority: P2)

As the homelab owner, I want to open AdGuard's administration interface over
Tailscale to inspect its health and filtering settings.

**Why this priority**: Private administration supports operating the service
without exposing DNS or management to the public internet.

**Independent Test**: Open the declared HTTPS administration URL from an
allowed tailnet client, verify authentication, and confirm an unauthenticated
visitor cannot read protected settings or change configuration.

**Acceptance Scenarios**:

1. **Given** an authorized tailnet connection, **When** the owner visits the
   documented URL and authenticates, **Then** AdGuard status and filtering
   configuration are visible with a valid TLS connection.
2. **Given** an unauthenticated visitor or a client outside permitted access,
   **When** it requests protected administration actions, **Then** access is
   denied; the first-run setup interface is not left open.
3. **Given** an off-tailnet client, **When** it attempts DNS or administration
   access, **Then** this feature supplies no public ingress to either service.

### User Story 4 - Recover predictable DNS service (Priority: P2)

As the owner, I want a repeatable deployment and a documented recovery path
so a failed update does not require reconstructing settings from memory.

**Why this priority**: Tailnet-wide DNS is a dependency for ordinary browsing.

**Independent Test**: Validate the rollback procedure and restore a saved
configuration into an isolated validation instance. Verify equivalent filtering
and access configuration without disrupting the active tailnet.

**Acceptance Scenarios**:

1. **Given** a failed pre-cutover check, **When** deployment is evaluated,
   **Then** the previous tailnet DNS configuration remains in use.
2. **Given** loss of the only filtering resolver after cutover, **When** clients
   query it, **Then** the failure is detectable and there is no automatic
   unfiltered fallback; the documented rollback can restore prior DNS policy.
3. **Given** a retained configuration backup, **When** recovery is tested,
   **Then** filtering rules and administrator access are restored; query history
   is not required for recovery.

### Acceptance amendment: existing Tailnet Lock mode

1. **Given** the authorized client and declared AdGuard proxy both report Lock
   disabled and agree on the proxy identity, **When** direct acceptance runs,
   **Then** identity verification succeeds without requiring a signing authority,
   and all DNS, administration, health and revision checks still run.
2. **Given** Lock is enabled, **When** acceptance runs, **Then** the existing
   signer and proxy signature requirements remain enforced.
3. **Given** missing, malformed, disagreeing or changing Lock observations,
   **When** acceptance or cutover is evaluated, **Then** it fails before changing
   DNS; no missing value is interpreted as disabled.
4. **Given** an unlocked tailnet, **When** the owner follows the runbook,
   **Then** no signing or Lock-policy change is requested, and evidence describes
   an unlocked verified peer without claiming a signature.

### Edge Cases

- An ad domain is absent from the selected lists or shares its domain with
  wanted content; DNS filtering cannot promise removal of every visible ad.
- A browser uses its own encrypted DNS, a device declines Tailscale DNS, or the
  device is disconnected; those lookups are outside this feature's enforcement.
- DNS cache entries predate cutover; acceptance uses fresh or cleared lookups.
- Queries require TCP, concern IPv6 records, or use an exit node.
- A filter download or upstream resolver fails; the last usable configuration
  remains intact and the service does not silently disable filtering.
- Resolver address or tailnet identity changes, or Tailnet Lock rejects a peer;
  dependent settings must not be activated from a guessed or stale address.
- The resolver, its host, or persistent storage is unavailable.
- Private service DNS is unavailable; private names must not fall through to
  public destinations as a side effect of this change.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Deploy AdGuard Home in the homelab through its established
  repository-owned delivery path and verify the running revision and health.
- **FR-002**: Provide DNS over UDP and TCP port 53 to the intended tailnet
  clients, subject to existing access and device-trust controls. An IPv4
  endpoint is sufficient if it correctly answers both A and AAAA queries.
- **FR-003**: Enable an ad-domain blocklist, record its source and update policy,
  and verify a domain actually present in the enabled list is blocked over both
  transports. Failed updates must retain the last usable list.
- **FR-004**: Resolve permitted public names and nonexistent names correctly,
  including A and AAAA queries, without recursive forwarding loops.
- **FR-005**: Provide a documented private HTTPS administration URL reachable
  through Tailscale; protected settings and writes require authentication.
- **FR-006**: Expose neither DNS nor administration publicly and leave no
  unauthenticated first-run setup endpoint available after initialization.
- **FR-007**: Preserve administrator configuration and filtering settings across
  routine service replacement. Keep credentials out of public source and logs.
  Repository-owned desired state is authoritative; durable configuration changes
  use the declared delivery path rather than undocumented UI edits.
- **FR-008**: Record and verify the actual stable tailnet DNS endpoint and its
  trusted identity before referencing it in global DNS settings.
- **FR-009**: Change Tailscale global DNS to use the verified filtering service
  and override local-network DNS for clients accepting Tailscale DNS.
- **FR-010**: Preserve MagicDNS and existing private homelab DNS routing and
  expected answers; private failures must not expose public fallback answers.
  Private-domain queries sent directly to AdGuard must also follow the private
  resolution path. MagicDNS remains a Tailscale client facility, not a zone
  that AdGuard must independently recreate.
- **FR-011**: Do not configure an unfiltered alternate global nameserver or
  automatic unfiltered fallback that defeats ad blocking.
- **FR-012**: Support the filtering and private-name policy for existing
  exit-node users; verify with an authorized existing exit node when available
  and report any untested exit-node behavior explicitly.
- **FR-013**: Require successful direct UDP/TCP DNS, filtering, permitted-name,
  private-name, endpoint-identity and administration checks before global cutover.
  Each direct DNS acceptance query has a three-second deadline and no hidden
  retries; a timeout is a failed gate.
- **FR-014**: Verify normal client resolution after cutover and distinguish
  direct-server checks from actual system-resolver acceptance. Use at least one
  authorized connected client accepting Tailscale DNS; record its OS, client
  version, exit-node mode and cache-control method. CI direct queries alone
  cannot satisfy client acceptance.
- **FR-015**: Retain the previous DNS policy and document its restoration
  through the repository delivery path. A failed pre-cutover check must leave
  the prior policy active.
- **FR-016**: Provide health checks and diagnostics sufficient to distinguish
  unavailable service, upstream failure, list-update failure and policy blocking.
  Retain no per-client query history by default; use aggregate health and bounded
  synthetic acceptance evidence without publishing browsing data.
- **FR-017**: Document persistent state, backup and restoration; demonstrate
  restoration of effective configuration and usable administrator credentials
  in an isolated validation instance. Preserve private credentials through their
  existing protected custody path; a backup-existence check is insufficient.
- **FR-018**: Document client prerequisites, DNS cache effects, application DNS
  bypasses, single-resolver outage behavior, and limits of domain-based blocking.
- **FR-019**: Validate relevant source and deployment checks, update affected
  operational documentation, and retain revision-bound functional evidence.
  Written manifests or a merged PR alone must not be reported as deployment.

- **FR-020**: Support acceptance under the tailnet's existing Lock mode.
  Require explicit, consistent live mode observations from the authorized client
  and proxy. Preserve expected tailnet, online state, stable device identity,
  node key, hostname, tag, published addresses and Kubernetes resource ownership
  checks in either mode. Enabled Lock retains existing trusted-signer and signed
  proxy requirements. Missing, malformed, inconsistent or changing observations
  fail closed. Never change Lock policy or fabricate signature evidence.
- **FR-021**: Bind acceptance and cutover evidence to the verified Lock mode and
  proxy identity so a change observed during acceptance or the final pre-apply
  check invalidates previous evidence. Rollback to captured prior DNS policy
  remains independent of AdGuard health and signing readiness. Existing direct DNS,
  administration, recovery, source-revision and post-cutover client requirements
  remain mandatory. Signing commands remain limited to locked-tailnet signing;
  unrelated ingress and canary workflows retain their current safeguards.

### Key Entities

- **Filtering configuration**: enabled lists, update policy, blocking behavior,
  upstream resolution policy, and administrator settings.
- **Tailnet DNS endpoint**: observed resolver address, trusted device identity,
  availability and allowed client access.
- **Tailnet DNS policy**: global resolvers, local DNS override, private-domain
  routing, MagicDNS and exit-node applicability.
- **Recovery record**: prior DNS policy, retained configuration backup,
  restore procedure and revision-bound acceptance results.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A domain confirmed present in an enabled ad list is blocked in
  every query in a 10-query direct acceptance sample on each supported transport;
  a permitted public domain resolves in every corresponding sample. Each direct
  query completes within three seconds without hidden retries.
- **SC-002**: After cutover, the test client's normal resolver blocks the test
  ad domain and successfully resolves the permitted domain in 10 fresh checks
  each on at least one authorized connected client with OS, client version,
  exit-node mode and cache-control method recorded; no unfiltered alternate is
  present in effective global DNS policy.
- **SC-003**: Every existing approved private homelab name in the repository
  acceptance inventory retains its expected answer, and a known tailnet device
  name resolves through the client's normal resolver.
- **SC-004**: The owner can authenticate at the documented private admin URL;
  unauthenticated protected reads and configuration writes are denied.
- **SC-005**: A routine service replacement and an isolated configuration restore
  both retain or recover the intended filtering and administrator access.
- **SC-006**: Delivery records identify the actual running revision, successful
  direct and client checks, prior DNS policy, rollback procedure and any
  unavailable acceptance condition. Required unverified behavior stays open.

- **SC-007**: An explicitly unlocked, identity-matched client/proxy pair passes
  identity verification; an enabled pair must meet existing signature checks.
  Every tested missing, malformed, mismatched or changed mode/identity is rejected
  before DNS mutation. Evidence distinguishes unsigned unlocked verification
  from signed locked verification.

## Assumptions

- “AdGuard” means AdGuard Home, a self-hosted DNS filtering service. DNS-level
  blocking is requested; browser extensions, traffic interception and enforcing
  application-specific encrypted DNS settings are outside scope.
- Tailnet-wide global DNS filtering is intended, as requested. Existing private
  DNS routing and MagicDNS should remain unchanged in behavior.
- Clients accept Tailscale DNS. Existing exit nodes may be tested within their
  current authorization; this request does not require deploying a new exit node.
- Default ad-domain filtering is sufficient initially. Parental controls,
  per-user policies and custom block/allow rules are not requested.
- One filtering service is sufficient initially; high availability across
  independent failure domains is not requested. Its outage can interrupt general
  tailnet DNS until recovery or deliberate rollback.
- Per-client browsing history is unnecessary for the requested result and is
  disabled by default. Aggregate health and synthetic checks suffice.
- Existing trusted enrollment, secret handling, image publication, storage and
  protected delivery mechanisms are reused. Missing runtime access, or signing
  capability when Lock is enabled, is recorded as an execution dependency, not
  bypassed. The owner confirms Lock is disabled; acceptance must independently
  verify current mode rather than rely only on that statement.
