# DNS, administration and delivery contracts

## DNS

Tailnet-facing UDP/TCP 53 on operator Service `automation/adguard-dns`, hostname
`homelab-adguard`, expected tag `tag:homelab-ingress`. DNS Service exposes no UI.
Both A and AAAA are supported over IPv4 transport. Configured null-IP blocking
returns 0.0.0.0 / :: for the respective blocked address query, with blocked TTL
10 seconds; test the selected release's actual behavior before activation.
Public permitted and nonexistent names use explicit general upstreams. Private
`stinkyboi.com` queries use existing private resolver; private failure must not
reach general upstreams. MagicDNS remains the Tailscale client's responsibility.

Direct test: 10 blocked and 10 permitted fresh queries per transport, explicit
A/AAAA checks, nonexistent-domain response, all approved private-name inventory
and private failure fixture. Each direct query: 3-second deadline, one attempt.
Initial empty cache is not ready for cutover until an enabled nonempty filter
and a contained test domain have been verified.

## Administration

Private `https://adguard.stinkyboi.com` -> Traefik private listener ->
`adguard-admin.automation.svc.cluster.local:3000`. TLS must validate. AdGuard
requires admin login; empty users or first-run setup are invalid. No Funnel
router may match this host or backend. Unauthenticated settings/write calls must
fail. UI inspection is supported; persistent settings change through GitOps.
Credentials are read privately through existing approved custody, never chat.

## Proposed operator helpers (implemented later)

`python3 -I scripts/adguard-check.py --server <observed-ip>` is read-only and
must bind Service UID/address, expected operator ownership, mode-verified online peer,
config/source revisions, active filters and direct DNS results. A separate
client mode records actual system resolver results with OS/client version,
exit-node mode and cache method. Direct queries cannot impersonate client mode.

`python3 -I scripts/tailscale-ingress-sign.py --adguard-only` previews only the
fixed target only when Lock is enabled; `--execute` uses existing
current-main/signing guards. On explicitly unlocked tailnets, skip this command
and run AdGuard acceptance directly. Acceptance independently verifies both
local and proxy mode; no operator override is supported.

`python3 -I scripts/adguard-dns-cutover.py --mode cutover --plan <private-saved-plan>`
previews the exact current-main saved plan. `--execute` additionally reruns all
required direct acceptance in the same invocation: <=300 monotonic seconds for
the full set, <=60 seconds between successful completion and apply. Persisted
receipts cannot authorize execution; reject future/negative times or clock
regression. Bind checks to source/deployed/config revisions, Service UID/IP,
peer identity, explicit Lock mode and applicable signature, plan SHA-256 and complete before/after DNS policy.
Immediately re-read main/config/endpoint/live policy and plan bytes; mismatch
requires a new plan/check run. Native state locks/stale-plan rejection remain.
Permit only the intended DNS singleton update with fully known values, no
unrelated resource changes, replacements or deletions. Check actual policy/state
before any retry following an uncertain outcome.

`python3 -I scripts/adguard-dns-cutover.py --mode rollback --plan <private-saved-plan>`
previews deliberate restoration. `--execute` uses existing administrator access,
clean current-main rollback source and an exact DNS-only saved plan. Validate
captured prior policy against reviewed pre-cutover source; validate fresh live
policy against recorded activated policy and exact plan before/after values.
If live policy already matches the captured previous policy, report no-op without
another write. Re-read current main/live policy/plan digest before applying,
with the same 300-second validation and 60-second final-delay bounds.

Rollback does not require a healthy AdGuard server, admin UI, active filter,
online peer or unchanged failed Service. It must not invoke the normal cutover
health gate. Missing prior-policy record, unrelated drift or administrator
connection failure still blocks apply. Private resolver availability is diagnostic,
not a prerequisite for restoring global DNS. Preserve split DNS/MagicDNS,
volumes, secrets and existing trust. Read back effective policy and separately
report actual client results after restoration.

Tests must reject stale receipts, mismatched IP/identity, failed queries,
invalid config/hash, exposed setup, unsafe plans and incorrect prior policy.
Include rollback with unreachable AdGuard as a passing eligibility case, paired
with unrelated-drift rejection. Expired check windows, future timestamps and
changed plan bytes must be negative cases.
No dry-run, static fixture, synthetic credential or mock peer proves live rollout.
