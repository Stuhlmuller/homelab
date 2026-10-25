# Feature Specification: Private Tailnet Service DNS

Historical public-cutover scope: the 27-name retirement described below is
superseded by the [26-name app subdomain cutover](../005-retire-public-app-dns/quickstart.md).
The 27-name private resolver scope remains.

**Feature Branch**: `codex/tailnet-service-dns`

**Feature Directory**: `specs/004-tailnet-service-dns`

**Created**: 2026-10-18

**Status**: Draft

**Input**: Private DNS answers for all 27 currently declared `stinkyboi.com` application names on ordinary tailnet clients, with automatic registration from reviewed private exposure declarations, unchanged HTTPS URLs and Traefik routing, and eventual removal of their public address records. Private names fail closed during resolver outages.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reach private apps by their existing names (Priority: P1)

As a tailnet user, I want the existing application names to resolve privately and open their usual HTTPS destinations, so using an app does not depend on a public DNS answer.

**Why this priority**: Private answers are the owner's primary goal.

**Independent Test**: Configure one ordinary tailnet client to use the private resolver, query every approved name through its normal operating-system resolver, and open representative HTTPS apps without changing their URLs.

**Acceptance Scenarios**:

1. **Given** an ordinary tailnet client with the private DNS setting and a healthy resolver, **when** it looks up each of the 27 approved names, **then** each returns the intended private application entry point and no public address.
2. **Given** private resolution works, **when** the user opens an existing application URL, **then** its certificate, host and path routing, authentication, and access restrictions behave as before.
3. **Given** the apex `stinkyboi.com`, `cordium.stinkyboi.com`, and a name matching `*.cordium.stinkyboi.com`, **when** a tailnet client looks them up, **then** each resolves privately and reaches its existing destination.

---

### User Story 2 - Register approved service names automatically (Priority: P2)

As the operator, I want reviewed exposure changes to update private DNS without another record-editing step, so application names remain aligned with the deployed routes.

**Why this priority**: Automatic registration is the condition under which the owner chose to retain Traefik.

**Independent Test**: Exercise add, change, and remove mutations of a paired HTTPS route and private ingress Service hostname annotation in the declaration contract. At first rollout, query all 27 newly registered names directly from the live resolver without a manual DNS record edit. Check convergence at the first later reviewed name change.

**Acceptance Scenarios**:

1. **Given** a reviewed change pairing an HTTPS route with a private ingress Service hostname annotation, **when** the name is deployed, **then** the controller-managed private answer appears automatically and directs the client to its existing HTTPS entry point.
2. **Given** an approved name changes or is retired, **when** the reviewed declaration is deployed, **then** its private answer changes or disappears without a separate DNS record edit.
3. **Given** an unapproved Kubernetes Service, discovery-only Ingress, or public-only route, **when** it is created or changed, **then** it does not acquire a private application answer.

---

### User Story 3 - Retire public answers safely (Priority: P3)

As the operator, I want the 27 private names absent from public DNS after a verified cutover, while unrelated public names continue working, so the private access boundary is clear.

**Why this priority**: Removing public answers is the owner's chosen end state, but it depends on proven private access and explicit treatment of existing off-tailnet callers.

**Independent Test**: Capture the live public baseline; verify private DNS, HTTPS, protected routes, native clients, and accepted off-tailnet impact; then retire the approved public records through the repository-owned workflow and query public resolvers after their prior cache lifetime expires.

**Acceptance Scenarios**:

1. **Given** the owner has added the verified resolver to tailnet DNS, private clients have passed the cutover checks, and the operator has recorded acceptance of any off-tailnet loss for the apex and
   Cordium wildcard, **when** the public record retirement is deployed, **then** public A, AAAA, and CNAME answers for the 27 names, including a concrete Cordium wildcard match, are absent after cache
   expiry.
2. **Given** an unrelated public name under `stinkyboi.com`, **when** a tailnet or public client looks it up while the private resolver is healthy, **then** its public answer remains available.
3. **Given** a private resolver outage after cutover, **when** a tailnet client looks up a private application name, **then** the name fails closed and does not fall back to a public application address.
4. **Given** public records have been retired and a read-only check of the resolver's tailnet address reports failure, **when** the operator executes the reviewed recovery path after the cluster and tailnet path are healthy, **then** private DNS is restored from declared state without republishing retired public address records or relaxing application route restrictions.

### Edge Cases

- The live DNS baseline differs from repository declarations; cutover waits until the difference is reconciled and recorded.
- A stale public answer remains in a client or upstream cache; final public absence is checked only after the prior published cache lifetime has expired.
- The apex or Cordium wildcard has an off-tailnet caller; public retirement waits for recorded migration or explicit acceptance of lost access.
- A public-only name shares the `stinkyboi.com` suffix; tailnet clients still receive its public answer while the private resolver is healthy.
- A private name is missing from the resolver before public retirement; cutover waits until the approved private answer is restored and verified.
- A new ordinary Service or catalog-only Ingress advertises a hostname without approval; it is excluded.
- A private name is removed from the approved set; its private answer disappears without routing another application into that name.
- The resolver or its tailnet path is unavailable after public retirement; private names fail closed, an operator-run check reports failure, and recovery uses declared state.
- An access path outside ordinary tailnet DNS, including node image pulls, native API clients, or restricted public callbacks, is affected by cutover; that check blocks retirement until fixed or explicitly accepted.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide private DNS answers on ordinary tailnet clients for all 27 currently approved application names in `scripts/config/tailscale-private-dns.json`, including `stinkyboi.com`, `cordium.stinkyboi.com`, and `*.cordium.stinkyboi.com`.
- **FR-002**: Each approved private answer MUST lead to the existing shared application entry point; existing HTTPS URLs, certificates, routing, authentication, and route restrictions MUST continue to work.
- **FR-003**: The system MUST automatically add, update, and remove controller-managed private answers when a reviewed change to an HTTPS route and the private ingress Service hostname annotation is deployed, without a separate manual DNS record edit.
- **FR-004**: A name MUST require both an existing HTTPS route and an explicit hostname annotation on the private ingress Service in the same reviewed exposure change. Ordinary Services, discovery-only Ingresses, retired names, and public-only routes MUST NOT be published by default. The 27-name inventory is the migration baseline, not a second record-editing step for future names.
- **FR-005**: The private resolver MUST answer approved names locally and preserve public answers for unrelated names under `stinkyboi.com` while healthy; it MUST NOT use a catch-all private answer for unrelated names. Their public records MUST remain intact.
- **FR-006**: After public retirement, private application names MUST fail closed if the resolver is unavailable; clients MUST NOT receive a public application address as a fallback.
- **FR-007**: The 27 private names' public A, AAAA, and CNAME answers MUST be retired through repository-owned desired state only after the owner adds the verified resolver to tailnet DNS, and a live DNS baseline, normal-client private lookups, HTTPS and access checks, and off-tailnet caller impact have been reviewed and accepted.
- **FR-008**: The cutover MUST verify the absence of the retired public answers after their previous published cache lifetime, without removing unrelated public answers.
- **FR-009**: The repository MUST declare the resolver, approved-name source, intended tailnet DNS setting and address, public-record retirement, validation, recovery, and rollback paths. The owner performs the tailnet DNS setting at the requested handoff; other live changes MUST follow repository-owned delivery paths.
- **FR-010**: The repository MUST provide an operator-executable, read-only check of a known private name through the resolver's tailnet address with a clear failure signal. Documented recovery MUST restore private resolution from declared state once the cluster and tailnet path are healthy, without restoring retired public A, AAAA, or CNAME records or weakening route restrictions.
- **FR-011**: The cutover checks MUST cover the existing special paths: Fleet setup restriction, Harbor image pulls from nodes, native API clients, and restricted public callbacks.
- **FR-012**: The new DNS endpoint MUST be authorized under the tailnet's existing device trust policy before it is offered as a nameserver, so ordinary tailnet clients can reach it.

### Key Entities

- **Approved private name**: A hostname or wildcard in an explicit, reviewed private exposure declaration associated with an existing HTTPS route; includes its intended shared entry point.
- **Private answer**: The address a tailnet client receives for an approved private name and uses to reach the shared application entry point.
- **Public answer**: An A, AAAA, or CNAME record visible through public DNS; the 27 approved private names' records are retired after cutover, while unrelated public names remain.
- **Cutover evidence**: Recorded baseline, private-client checks, route and caller checks, cache-expiry verification, and rollback decision for the DNS migration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A normal tailnet client receives the intended private answer for all 27 current names, including the apex and a Cordium wildcard match, and opens representative existing HTTPS URLs successfully.
- **SC-002**: On the initial live deployment, the resolver returns authoritative private answers for all 27 names from the watched Service without a manual DNS record change. Offline paired
  add/change/remove mutations pass the permanent declaration contract; unapproved names fail it. Observe live convergence on the first later reviewed name change. Public fallthrough and record
  retirement have separate gates.
- **SC-003**: After public retirement and the previous published cache lifetime, public resolvers return no A, AAAA, or CNAME answer for all 27 names, including a concrete Cordium wildcard match, while unrelated public names still resolve.
- **SC-004**: During an induced private resolver outage after public retirement, all sampled private names fail closed; no sampled name resolves to a public application address.
- **SC-005**: Existing HTTPS access, Fleet setup denial, Harbor node pulls, native API clients, and restricted public callbacks pass their documented checks with zero unintended regressions before public retirement.
- **SC-006**: An operator can run the read-only health check against the deployed resolver's tailnet address. It succeeds only for the expected private answer and clearly fails for an unavailable or wrong answer; the documented recovery restores that answer once the underlying cluster and tailnet path are healthy.
- **SC-007**: Before tailnet DNS is changed, an ordinary tailnet client can query the new resolver's assigned tailnet address under the existing device trust policy.

## Assumptions

- The current 27-name list is the migration baseline, not evidence that those answers are already live publicly. Live state must be checked before retirement.
- An HTTPS route paired with an explicit hostname annotation on the private ingress Service is one reviewed exposure change. A future name requires that paired change, after which controller-managed publication converges automatically; the migration inventory does not require another per-name edit.
- The current shared HTTPS entry point and Traefik remain responsible for certificates and host and path routing.
- Public use of the apex and Cordium wildcard may exist. Migration or accepted loss of access must be recorded before their public records are removed.
- The first rollout can use one resolver if fail-closed behavior, the operator check, and declared recovery are verified.
- An ordinary tailnet client means a client using its operating system's configured tailnet DNS. Clients that bypass that setting are outside the private-answer success checks.
- The owner will apply the declared tailnet DNS setting after the resolver's tailnet address and reachability are verified; public record retirement follows the resulting client checks.
- Public names unrelated to the 27-name private set, including a planned Mastodon name if published, remain public.
