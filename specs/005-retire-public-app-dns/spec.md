# Feature Specification: Retire Public App Subdomain DNS

**Feature Branch**: `codex/tailnet-subdomain-retirement`

**Feature Directory**: `specs/005-retire-public-app-dns`

**Created**: 2026-10-18

**Status**: Draft

**Input**: Remove public address records for all currently approved private app subdomains under `stinkyboi.com`, while keeping the public zone, the apex, mail and certificate records, and unrelated public names. Tailnet users keep the existing private DNS answers and HTTPS URLs.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Retire public app subdomain answers (Priority: P1)

As the owner, I want the approved private app subdomains to stop publishing public addresses after tailnet access is verified, so their names lead to the private app entry point only for tailnet clients.

**Why this priority**: Removing those public answers is the requested cutover.

**Independent Test**: Check ordinary tailnet client lookups for every approved name and HTTPS access for serving apps; confirm any intentionally stopped app has zero replicas in reviewed source and live state. Retire public address records, then query public DNS for each name and a concrete Cordium wildcard child after the previous cache lifetime.

**Acceptance Scenarios**:

1. **Given** private DNS and HTTPS access have passed for every approved app subdomain, **when** the reviewed public retirement is completed and the previous cache lifetime has expired, **then** public DNS returns no A, AAAA, or CNAME answer for any of the 26 approved non-apex names.
2. **Given** the approved `*.cordium.stinkyboi.com` name, **when** the public wildcard address record is retired, **then** a concrete matching child has no public A, AAAA, or CNAME answer and still resolves privately for a tailnet client.
3. **Given** a retired app subdomain and an unavailable private resolver, **when** an ordinary tailnet client looks it up, **then** it receives no public app address as a fallback.

---

### User Story 2 - Keep intentional public DNS working (Priority: P2)

As the owner, I want the public zone and its unrelated services to remain available, so private app retirement does not interrupt apex DNS, mail, certificate renewal, or intentionally public names.

**Why this priority**: The scope is app subdomain address records, not the public DNS zone.

**Independent Test**: Before and after retirement, compare public answers and representative service behavior for the apex and unrelated public names, and verify private apex resolution on a healthy tailnet client.

**Acceptance Scenarios**:

1. **Given** the public apex `stinkyboi.com`, **when** app subdomain records are retired, **then** its existing public A, MX, TXT, and any CAA records remain unchanged, and a healthy tailnet client still receives the intended private apex address.
2. **Given** an unrelated public name such as the planned public Mastodon name once published, **when** retirement completes, **then** its public answer and intended public access remain available.
3. **Given** certificate renewal depends on public DNS-01 validation, **when** retirement completes, **then** Cloudflare remains the public authoritative DNS provider, the `cert-manager-cloudflare-api-token` ExternalSecret and `letsencrypt-cloudflare` ClusterIssuer report Ready, their DNS-01 solver and secret references still match reviewed source, and application Certificates remain Ready.

---

### User Story 3 - Complete a guarded and recoverable cutover (Priority: P3)

As the operator, I want a precise public-record baseline, evidence of affected callers, and a recovery path, so the cutover can be reviewed and completed without deleting other records or republishing private apps.

**Why this priority**: A mistaken deletion or an untested off-tailnet caller could interrupt unrelated services.

**Independent Test**: Compare the live record inventory with the exact retirement set; review private-client, special-path, and off-tailnet evidence; simulate a changed baseline and a partial retirement; then verify recovery of private DNS without restoring public app addresses.

**Acceptance Scenarios**:

1. **Given** a live public record outside the 26-name retirement set, **when** a retirement preview is reviewed, **then** that record is excluded and remains unchanged after cutover.
2. **Given** live records differ from the approved baseline or required private-client and caller checks are missing, **when** retirement is requested, **then** deletion is blocked until the difference or missing evidence is resolved.
3. **Given** a partial retirement, **when** the operator retries through the reviewed cutover path, **then** only remaining approved records are removed and the completed deletions remain absent.
4. **Given** a later private-resolver outage, **when** the operator follows the reviewed recovery process, **then** private answers are restored without republishing retired public app address records.

### Edge Cases

- An approved subdomain has no current public A, AAAA, or CNAME record; it is already retired for that record type and requires no deletion.
- An approved app is deliberately stopped at zero replicas; its private name remains approved, but its backend HTTP error is accepted only when reviewed source and live state both confirm the suspension.
- A broader public wildcard or delegated NS/child zone could yield an effective public answer after exact parent-zone records are removed; pre-deletion checks block on either source until separately reviewed. A covering wildcard CNAME also blocks. Delegation records are not deleted by default.
- A cached public answer persists after deletion; success is measured after the largest previously published cache lifetime.
- An off-tailnet caller uses a retired app name, including a native client or protected route; it must be migrated or the loss of access explicitly accepted before deletion.
- A new private app name is approved after this baseline; it must not acquire a public address record by default.
- The private resolver or tailnet path fails after cutover; retired subdomains fail closed until private resolution is restored.
- The apex remains public; its behavior during private-resolver failure is outside the retired-subdomain fail-closed guarantee.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The retirement set MUST be the 26 non-apex names in the fixed first 27 entries of `scripts/config/tailscale-private-dns.json`, including `cordium.stinkyboi.com` and the `*.cordium.stinkyboi.com` wildcard. The apex, later private names, the four listed `retired_hostnames`, and the planned public Mastodon name MUST be excluded.
- **FR-002**: The retirement MUST remove only public A, AAAA, and CNAME records for that set. It MUST preserve the public DNS zone, all existing public apex records, other record types, and unrelated public names.
- **FR-003**: Retirement MUST wait for recorded evidence that ordinary tailnet
  clients resolve all current approved names privately through their normal DNS
  path and can use the original 27 migration HTTPS routes and access
  restrictions. Staged private names outside the retirement set have separate
  backend readiness. An intentionally stopped migration app MAY return a backend
  error only when reviewed source and live state both declare zero replicas;
  active migration routes MUST still pass.
- **FR-004**: Retirement MUST wait for a reviewed live public-record baseline, prior maximum cache lifetime, exact proposed changes, and accepted impact on existing off-tailnet callers and special paths.
- **FR-005**: Before deletion, the cutover MUST verify that the selected
  Cloudflare API zone is publicly delegated, inspect complete public-zone
  records, and block on any out-of-set covering wildcard A/AAAA/CNAME or
  relevant child NS delegation. It MUST check effective authoritative A, AAAA,
  and CNAME answers for each selected name and a concrete Cordium wildcard child.
  A changed live baseline, failed or non-authoritative DNS response, unexpected
  answer source, incomplete inspection, or missing required evidence MUST block
  deletion. Records outside the selected names MUST remain untouched. A partial
  retirement MUST be detectable and safely resumable after rechecking live state.
- **FR-006**: After the previous cache lifetime, public A, AAAA, and CNAME answers MUST be absent for every retired name and a concrete Cordium wildcard child, while normal tailnet clients continue to reach the intended private HTTPS destinations.
- **FR-007**: Existing public apex A/MX/TXT records, any CAA records, and
  intentionally public names MUST remain usable; healthy tailnet clients MUST
  continue to resolve the apex privately. Public DNS-01 readiness MUST pass a
  read-only check of Cloudflare authoritative delegation, Ready status for the
  `cert-manager-cloudflare-api-token` ExternalSecret and
  `letsencrypt-cloudflare` ClusterIssuer, and unchanged solver/secret references
  in reviewed source.
- **FR-008**: Retired names MUST NOT be silently republished with public app addresses. Future approved private app names MUST have private answers without public app address publication by default.
- **FR-009**: After retirement, an unavailable private resolver MUST NOT cause retired subdomains to resolve to a public app address. Recovery MUST restore private resolution without restoring those public records or loosening existing route restrictions.
- **FR-010**: The repository MUST document the cutover evidence, verification, recovery, and policy reversal paths. Changes to live desired state MUST be reviewable and represented in repository-owned code before execution.

### Key Entities

- **Approved app subdomain**: One of the 26 non-apex names in the fixed first 27 migration entries, including the Cordium wildcard. Its existing HTTPS destination remains unchanged.
- **Retirement set**: The approved app subdomains whose public A, AAAA, and CNAME records are selected for removal.
- **Preserved public record**: An apex record, another record type, or an unrelated public name that remains available after cutover.
- **Cutover evidence**: The reviewed live baseline, exact proposed record changes, private-client and caller checks, previous cache lifetime, and post-retirement results.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the previous maximum cache lifetime, public DNS gives no A, AAAA, or CNAME answer for 26 of 26 retired names and a concrete Cordium wildcard child.
- **SC-002**: An ordinary tailnet client receives the intended private answer for 29 of 29 current approved names, including the apex and two staged Enterprise names; the original 27 migration HTTPS routes and restrictions pass after retirement.
- **SC-003**: Zero existing public apex records or unrelated public records are removed or unintentionally changed; the public DNS-01 readiness checks in FR-007 pass, existing application Certificates remain Ready, and intentionally public service checks pass.
- **SC-004**: In a private-resolver outage check, sampled retired subdomains return no public app address; restoring private resolution requires no public app record restoration.
- **SC-005**: The operator can review the exact record changes and the required client, caller, and cache evidence before deletion; a changed baseline or missing evidence blocks the cutover.

## Assumptions

- This feature narrows the public-record retirement described in `specs/004-tailnet-service-dns`: the 26 approved app subdomains are retired, while the apex remains public and privately resolvable when the resolver is healthy.
- The existing private resolver, tailnet DNS rule, and Traefik HTTPS routes are available before public retirement. This feature does not replace them.
- The four names listed as `retired_hostnames` in the inventory (`octelium-transport`, `kubernetes-api-ci`, `n8n-webhook`, and `policy-bot-hook`) are intentionally outside this 26-name cutover. Any later change to them is separate work.
- The planned public Mastodon name is intentionally outside this cutover and stays public when published.
- Public certificate validation and mail still rely on the public zone. Keeping the zone and required validation records is intentional.
- An ordinary tailnet client uses its operating system's configured tailnet DNS. Clients that bypass it are outside the private-answer checks.
