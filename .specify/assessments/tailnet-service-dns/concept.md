# Concept: Tailnet service names

- **Slug**: tailnet-service-dns
- **Created**: 2026-10-18
- **Recommended option**: Option B — Dynamic private DNS, retain shared routing

## Options

### Option A — Keep the current workflow

- **Sketch**: Keep the declared public-DNS inventory and shared application routing. Verify current client DNS behavior and any privacy concern before changing the access model.
- **Appetite**: small (days for observation; no deployment)
- **Trade-offs**: Preserves declared URL and access boundaries with no new service. It does not meet the owner's priority for private DNS answers or automatic registration.
- **Rabbit holes**: Declared source may differ from live DNS behavior; a short observation period may miss intermittent client failures.

### Option B — Dynamic private DNS, retain shared routing

- **Sketch**: Tailnet clients receive private DNS answers for all 27 currently declared application names, including the apex and Cordium wildcard. Records follow reviewed Kubernetes exposure
  declarations; once private resolution and clients pass acceptance, the public records for those names are retired. The shared application entry point continues to serve familiar HTTPS URLs and
  enforce existing routes.
- **Appetite**: medium (weeks as a budget; actual effort depends on zone coexistence and availability requirements)
- **Trade-offs**: Meets the stated privacy priority without redesigning TLS, callback, or Harbor routing. It adds a resolver and its availability burden; private names fail closed if it is unavailable. Application routes still need explicit review, so service onboarding is not fully automatic.
- **Rabbit holes**: The apex and Cordium wildcard still appear in retained public routing; retiring their public records changes off-tailnet access. Other public answers under `stinkyboi.com`, name approval, DNS recovery, and old DNS caches also require cutover care.

### Option C — Direct tailnet exposure per service

- **Sketch**: Approved applications get their own tailnet destinations and private names, and the shared application routing layer is retired only after each existing URL and access boundary has an equivalent owner. This pursues the requested removal of Traefik as a separate access change.
- **Appetite**: large (months as a budget; uncertain until route and client dependencies are inventoried)
- **Trade-offs**: Could reduce reliance on a shared entry point. It shifts HTTPS, hostname, path, callback, and Harbor protections across many services; DNS alone cannot supply them.
- **Rabbit holes**: Fleet setup denial, public callback paths, Harbor node pulls, certificates for existing custom domains, Cordium workspace names, and native client behavior.

## Recommendation

Option B best matches the owner's clarified priority for private DNS answers and automatic registration while keeping the current routing boundary. Its value does not depend on proving maintenance savings. The owner confirmed all 27 entries, public-record retirement, and fail-closed resolution; specification must define acceptance, public-zone coexistence, and recovery before rollout.

## Out of Scope (for the recommended option)

- Removing the shared application routing layer or changing existing HTTPS URLs.
- Making currently private applications public or publishing every Kubernetes Service automatically.
- Changing public callbacks, Harbor node image pulls, or unrelated cluster-internal discovery.
- Weakening existing path restrictions, application authentication, or approval of tailnet-visible names.

## Assumptions to Validate

- The owner chose public-record retirement for the 27 listed names. Any retained public use of the apex or Cordium wildcard must be identified before that change; those names will otherwise stop resolving off tailnet.
- Existing HTTPS URLs and route protections must remain intact.
- An explicit approval boundary for tailnet-visible names is acceptable.
- Other public answers under `stinkyboi.com` can remain available to tailnet clients without retaining public records for the 27 private names.
- Fail-closed name resolution and an acceptable recovery path are achievable within the chosen appetite.
