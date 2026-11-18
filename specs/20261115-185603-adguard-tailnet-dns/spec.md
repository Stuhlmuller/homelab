# Feature Specification: AdGuard Tailnet DNS

**Feature Branch**: `feat/adguard-tailnet-dns`

**Created**: 2026-11-15

**Status**: Deployed; functional acceptance and DNS cutover pending

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

### Endpoint verification

- The owner runs actual Mac checks locally; cloud fixtures do not establish
  normal-client acceptance.
- Match the connected client's peer to the Service-owned proxy using stable
  device ID, numeric NodeID, node key, expected tailnet, hostname, tag, addresses,
  online state and Kubernetes ownership. Missing or inconsistent observations
  are rejected. Repeat checks around collection and before DNS application.
- Changed identity observations invalidate previous acceptance evidence. The
  final observation is not an atomic guarantee across machines.
- Restoring captured prior DNS policy remains independent of AdGuard health.

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

### Endpoint identity acceptance

1. **Given** a connected client and a ready Service-owned proxy with matching
   stable identity, **When** acceptance runs, **Then** all DNS, administration,
   health and revision checks run against the observed endpoint.
2. **Given** missing, malformed, mismatched or changing identity observations,
   **When** acceptance or cutover is evaluated, **Then** it fails before DNS changes.
3. **Given** a failed filtering resolver, **When** prior DNS policy is restored,
   **Then** rollback does not depend on the failed resolver's health.

### Edge Cases

- An ad domain is absent from the selected lists or shares its domain with
  wanted content; DNS filtering cannot promise removal of every visible ad.
- A browser uses its own encrypted DNS, a device declines Tailscale DNS, or the
  device is disconnected; those lookups are outside this feature's enforcement.
- DNS cache entries predate cutover; acceptance uses fresh or cleared lookups.
- Queries require TCP, concern IPv6 records, or use an exit node.
- A filter download or upstream resolver fails; the last usable configuration
  remains intact and the service does not silently disable filtering.
- Resolver address or tailnet identity changes, or a peer becomes unreachable;
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

- **FR-020**: Verify the connected client and declared proxy against the expected
  tailnet, online state, stable device ID, numeric NodeID, public key, hostname,
  tag, published addresses and Kubernetes resource ownership. Reject missing,
  malformed, inconsistent or changing observations.
- **FR-021**: Bind acceptance and cutover evidence to the full verified proxy
  identity. Changes observed during acceptance or final pre-apply checks
  invalidate previous evidence. Preserve independent rollback and all direct
  DNS, administration, recovery, source-revision and normal-client requirements.

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

- **SC-007**: A matching online client/proxy identity passes verification; every
  tested missing, malformed, mismatched or changed identity is rejected before
  DNS mutation, while functional DNS and administration checks remain mandatory.

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
- Existing enrollment, secret handling, image publication, storage and protected
  delivery mechanisms are reused. Missing runtime or administrator access is
  recorded as an execution dependency; source or fixture success cannot replace
  required owner-run acceptance.
