# Data and state contracts

| Entity | Fields / identity | Validation and ownership |
| --- | --- | --- |
| Desired config | schema 34, admin user, hash, DNS binds/upstreams, filter URL/ID, privacy flags, revision | Repository template plus protected ESO output; exactly one nonempty bcrypt user; no plaintext password |
| Credential | SSM parameter name/version, generated password, ESO revision | 32 characters, <=72 UTF-8 bytes; exact reader grant; never output values |
| Work cache | PVC identity, filter IDs, cached files, successful update time | One writer; retained claim; failed refresh preserves usable cache |
| DNS endpoint | Service UID/address, operator owner labels, peer key/name/tag | Exactly expected Service and online identity-verified peer ; observed tailnet IPv4; no stale/guessed IP |
| DNS policy | global servers, override, MagicDNS, split domain/server, exit-node flag | Existing single provider resource owns whole config; only approved global fields change |
| Acceptance receipt | Source/deployed/config revisions; full Service/peer identity; UTC/monotonic timings; plan digest; before/after policies; query results | Audit only. Rerun checks before cutover; enforce 300-second validation and 60-second final bounds. Reject stale or changed bindings. |
| Recovery sources | pre-cutover Git revision, captured prior DNS policy, recorded activated policy, protected SSM version, retained work cache | Prior policy must agree with reviewed source; fresh live policy must match activated or already-restored policy; rollback eligibility excludes AdGuard health |

Lifecycle: source prepared -> image published -> app registered -> ESO/config
ready -> workload healthy -> peer identity verified -> direct checks pass -> observed-IP
cutover source merged -> exact DNS saved plan applied -> client acceptance ->
complete. Failure before cutover leaves prior policy unchanged. Endpoint changes
invalidate receipts. Rollback restores prior DNS through reviewed source/saved
plan; it never deletes the PVC or claims automatic filtered availability.

Rollback is a distinct transition: activated or failed service -> validated prior
policy restoration -> policy readback -> independent client checks. AdGuard health
is not a precondition. A lost apply response enters outcome-unknown: inspect live
policy and state before selecting no-op, retry with fresh validation, or drift
reconciliation. Do not reuse successful receipts to skip new checks.


## Verified endpoint evidence

Match the Service-owned Pod and proxy device to the connected client's network
map. Evidence includes stable device ID, numeric NodeID, public key, hostname,
tag, addresses and Pod UID. Require online, unexpired identity and exact
Kubernetes ownership. Capture the complete observed peer in before/after direct
snapshots and fresh pre-apply checks; observed identity changes invalidate prior
acceptance. Receipts are audit records and cannot replace fresh checks. Rollback
uses its independent captured-policy record.
