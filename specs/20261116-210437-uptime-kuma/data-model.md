# Monitoring data model

## Catalog

`schemaVersion: 1`; one `apps` array and one `monitors` array. Validate before any
API write. Keys are lowercase hyphenated stable identities; reject duplicates,
unknown fields, credentials in URLs/headers and unresolved references.

An app has `id`, lifecycle (`active`, `staged`, `suspended`, `retired`,
`configuration-only`), `source`, `reason`, and `monitorIds`. Active apps require
at least one enabled meaningful monitor. Shared IDs require a reason describing
what component they cover. Configuration-only entries point to an actual
covered child/service; no synthetic runtime success is invented. Source paths
must exist. Live-only entries carry verified owning evidence. Revalidate new
live-only names during acceptance; review additions explicitly.

A monitor has stable `key`, display `name`, `ownerAppIds`, `kind`, target fields,
expected result, cadence/timeout/retry, `enabled`, and human-readable
`meaning`/`limitations`. Allowed kinds: HTTP, JSON-query and TCP when the
narrow transport signal is justified. Prometheus monitors additionally record
actual source observation/scrape cadence, its configuration evidence, expected
workload identities and freshness predicate. The maximum source age is exactly
two source periods, independently for each required source; missing cadence
evidence is invalid. Kuma check cadence does not determine source freshness.
Scheduled monitors record schedule and success-age threshold. The validator
rejects broad credential-bearing targets and a success rule based only on 401,
redirect or query evaluation timestamp.

## Runtime identity

Each managed monitor description contains an exact marker
`homelab-managed:uptime-kuma:v1:<key>` plus meaning. Keys are unique across all
returned monitors; duplicates stop reconciliation before writes. Preserve Kuma
numeric IDs and all fields outside the owned projection. Never infer ownership
from display name alone. Missing desired managed keys create monitors; changed
owned fields edit; explicit retired entries pause; removals from the catalog
are invalid until represented as retirement. Unowned monitors are ignored.

## Status and observations

Kuma owns users, native monitor records, heartbeat history and aggregates.
No runtime adapter or production SQL mutations. The explicit restore-verification
exception below operates only on a disposable clone. The sidecar's nonsecret
status records catalog SHA,
last-success timestamp, managed/created/changed/paused counts and error category.
Never persist password, login token, full API responses or secret target fields.
A failure preserves last-success evidence but marks the current attempt failed.

## Backup manifest

Archive filename, captured UTC timestamp, source image digest, catalog hash,
archive checksum, database integrity result and sanitized monitor/history
counts. The archive contains database/config/allowed uploads, never mounted
secret files. Store it privately on retained backup storage. Verify checksum
before extraction; reject absolute paths, traversal and symlink escapes.
Restoration verifies the immutable archive before any clone modification and
proves native login and saved observations using the execution fence below.

## Disposable restore execution fence

State transition: verified archive → untouched extracted identity/history
summary → transactionally fenced clone → independently checked fence → loopback
native login/read-only verification → shutdown/discard. Any failed precondition
stops before native startup. Archive, source database and production credentials
are never modified.

Pinned SQLite shape: monitor(id, active, user_id), notification(id, active,
is_default, user_id, config), monitor_notification(id, monitor_id,
notification_id), maintenance(id, active), setting(id, key, value, type), plus
unchanged user and history tables. Assert actual required columns/types and
setting-key uniqueness; reject unexpected schema/version rather than guessing.
Only clone activation fields and notification bindings are altered: all monitor,
notification/default and maintenance flags become 0; bindings become empty.
The settings checkUpdate and nscd are JSON false; cloudflaredTunnelToken is a
JSON empty string. Missing settings may be inserted once by the fence, but the
postcondition requires exactly one correctly decoded row for every key.

Private verification evidence retains the archive hash, original monitor IDs,
all monitor fields other than active, user/auth records, notification definitions
other than activation/default flags, and historical rows/counts/digests. Their
contents never enter logs or public receipts. Pre-start verification proves the
fence changed only its explicit fields/tables; post-start verification proves
identities and saved observations remain usable. Application startup may perform
its own normal maintenance; failure to preserve required history fails the drill,
never rewrites or blesses the archive.

The Job's separate service account and declared deny-all policies are defense
in depth. They do not claim a functioning network sandbox on this cluster.
