# Descheduler Safety

The first policy is intentionally conservative:

- Do not evict system-critical pods.
- Ignore pods with PVCs.
- Require at least two replicas before eviction.
- Start with balancing and anti-affinity cleanup only.

Expand the policy only in a follow-up PR with live validation evidence.

