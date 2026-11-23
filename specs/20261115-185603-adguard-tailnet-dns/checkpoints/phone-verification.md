# Phone verification follow-up

The owner requested deployment without waiting for Mac testing, with a phone
blocked-domain check or visible queries in the private AdGuard UI afterward.
Direct Mac UDP/TCP filtering and isolated restore were already reported passing;
normal-client testing is now follow-up acceptance rather than a deployment gate.

The workload enables a bounded 1,000-entry in-memory Query Log, keeps client IPs
anonymized, and leaves file logging and statistics disabled. Both secret and pod
configuration revisions advance to v2. Configuration and pinned-image tests
cover visibility, eviction, restart clearing, and absence of query-log files.
The query-log API exposes enabled status but not the storage or buffer settings;
the read-only checker does not claim to verify unexposed fields.

The tailnet DNS source was delivered by PR #1894. Activation remains a separate
operation: ordinary workload CI lacks administrator DNS authority. The connected
cloud's SSM inventory contains only the Kubernetes operator OAuth pair, whose
declared scopes are devices:core, auth_keys, and services. The administrator
credential reference has been requested without asking for secret values in chat.
Do not broaden the operator credential or treat source merge as DNS activation.

Phone check after activation: connect Tailscale, request a domain blocked by the active filter, and
match the blocked query in the authenticated Query Log. A failed page load alone
is inconclusive. Runtime deployment and DNS readback must be reported separately.
