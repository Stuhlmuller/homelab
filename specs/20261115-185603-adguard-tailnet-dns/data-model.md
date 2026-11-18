# Data and state contracts

| Entity | Fields / identity | Validation and ownership |
| --- | --- | --- |
| Desired config | schema 34, admin user, hash, DNS binds/upstreams, filter URL/ID, privacy flags, revision | Repository template plus protected ESO output; exactly one nonempty bcrypt user; no plaintext password |
| Credential | SSM parameter name/version, generated password, ESO revision | 32 characters, <=72 UTF-8 bytes; exact reader grant; never output values |
| Work cache | PVC identity, filter IDs, cached files, successful update time | One writer; retained claim; failed refresh preserves usable cache |
| DNS endpoint | Service UID/address, operator owner labels, peer key/name/tag, Lock mode and applicable signature | Exactly expected Service and online identity-verified peer with mode-appropriate signature; observed tailnet IPv4; no stale/guessed IP |
| DNS policy | global servers, override, MagicDNS, split domain/server, exit-node flag | Existing single provider resource owns whole config; only approved global fields change |
| Acceptance receipt | source/deployed/config revisions, Service UID/IP, peer key/name/tag, Lock mode and applicable signature, UTC and monotonic timings, plan SHA-256, before/after DNS policies, query results | Audit only; cutover reruns all checks in invocation; 300-second full-check and 60-second completion-to-apply bounds; reject future/negative time and changed bindings |
| Recovery sources | pre-cutover Git revision, captured prior DNS policy, recorded activated policy, protected SSM version, retained work cache | Prior policy must agree with reviewed source; fresh live policy must match activated or already-restored policy; rollback eligibility excludes AdGuard health |

Lifecycle: source prepared -> image published -> app registered -> ESO/config
ready -> workload healthy -> peer identity/mode verified (signed when locked) -> direct checks pass -> observed-IP
cutover source merged -> exact DNS saved plan applied -> client acceptance ->
complete. Failure before cutover leaves prior policy unchanged. Endpoint changes
invalidate receipts. Rollback restores prior DNS through reviewed source/saved
plan; it never deletes the PVC or claims automatic filtered availability.

Rollback is a distinct transition: activated or failed service -> validated prior
policy restoration -> policy readback -> independent client checks. AdGuard health
is not a precondition. A lost apply response enters outcome-unknown: inspect live
policy and state before selecting no-op, retry with fresh validation, or drift
reconciliation. Do not reuse successful receipts to skip new checks.

## Mode-aware peer evidence

`lock_enabled` is an explicit boolean, never inferred from missing fields.
Unlocked records have `signed: false` and bind stable device ID, numeric NodeID,
node key, expected name/tags, sorted tailnet addresses and Pod UID. They omit
rotation keys. Locked records retain signing evidence with `lock_enabled: true`
and `signed: true`. Missing mode invalidates a new acceptance snapshot. Historical
receipts remain audit records and cannot authorize cutover. Any observed mode or
identity change requires fresh checks; rollback policy records remain independent.
