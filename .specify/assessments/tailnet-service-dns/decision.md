# Decision: Private DNS for tailnet services

- **Slug**: tailnet-service-dns
- **Decided**: 2026-10-18
- **Verdict**: go
- **Artifacts reviewed**: `intake.md`, `research.md`, `problem.md`, `concept.md`
- **Owner clarification**: Private DNS answers are the priority; retaining Traefik is acceptable if DNS registration is automatic. All 27 current private inventory entries are in scope, their public records should be removed after cutover, and private names should fail closed during resolver outages (2026-10-18).

## Scorecard

| Criterion | Rating | Justification |
| --- | --- | --- |
| Problem validity | adequate | The owner confirmed a preference for private DNS answers; the repository declares a public Cloudflare DNS-only path for private app names. |
| Evidence strength | adequate | Repository source establishes the current 27-name publication model and routing boundaries; cited product documentation supports split DNS and dynamic record publication. The preference is direct owner input, though live behavior and maintenance cost were not measured. |
| Value vs. inaction | adequate | Doing nothing keeps the declared public-DNS approach for private app names, contrary to the owner's clarified priority. Reduced operator work is a possible secondary benefit, not the justification for proceeding. |
| Feasibility / appetite | adequate | Concept Option B has a medium appetite and uses documented capabilities while retaining the existing HTTPS and path-routing owner. Zone coexistence and resolver availability remain specification questions. |
| Strategic fit | strong | Private names and approved publication can follow the repository's declarative, reviewable workflow and preserve existing access boundaries. |
| Risk posture | adequate | The concept retains Traefik and excludes automatic exposure of all Services. The chosen public-record retirement includes the apex and Cordium wildcard, so public-caller impact, zone coexistence, resolver recovery, and name approval require explicit acceptance criteria before rollout. |

## Verdict & Rationale

**Go to specification for Option B.** The owner wants private, automatically registered answers for all 27 current names, accepts keeping Traefik, chose public-record retirement after cutover, and
wants outages to fail closed. The repository's declared public-DNS workflow establishes a concrete gap, and the research shows a credible dynamic-DNS path. The earlier maintenance-savings hypothesis
is secondary. The specification must identify any public callers of the apex or Cordium wildcard before retiring those records and define the resolver recovery and zone-coexistence behavior.

## If go — Handoff to `$speckit-specify`

- **Problem**: The repository declares public DNS answers for 27 private application names; the owner wants tailnet clients to receive private answers for them, including the apex and Cordium wildcard, with automatic registration and familiar HTTPS URLs.
- **Chosen approach**: Option B — dynamic private DNS for approved names while retaining shared Traefik routing.
- **In scope**: Private answers for all 27 current names on tailnet clients; automatic publication from reviewed Kubernetes declarations; verified retirement of public A/AAAA/CNAME answers for those names after cutover; fail-closed private resolution on resolver outage; preservation of unrelated public DNS answers and current HTTPS access.
- **Out of scope**: Removing Traefik, exposing every Service automatically, changing public callbacks or Harbor node pulls, weakening route restrictions or application authentication, and changing unrelated cluster-internal DNS.
- **Success metrics**: All 27 current names return the intended private answer from normal tailnet clients and reach the intended entry point; after cutover and cache expiry, public A/AAAA/CNAME
  answers for those names are absent; private names fail closed during resolver outage; existing HTTPS URLs and protected routes show zero unintended regressions. Measure manual DNS changes as a
  secondary outcome.
- **Carried-forward open questions**: Which declarations qualify future names and who approves them? How will unrelated public answers remain available to tailnet clients? Which public callers currently rely on the apex or Cordium wildcard, and what access change will they experience? What live DNS baseline, recovery target, client checks, and reviewed rollback path are required?
