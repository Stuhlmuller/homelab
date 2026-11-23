# Version-bound native configuration contract

Target: Uptime Kuma 2.5.11 at the digest in plan.md. This is the native frontend
Socket.IO interface, not a promised stable public REST API. Module loading must
resolve bundled `/app/node_modules/socket.io-client`, with no runtime install.

| Event | Request | Success contract |
| --- | --- | --- |
| `needSetup` | callback | boolean |
| `setup` | username, password, callback | `{ok:true}`; only when no user exists |
| `login` | `{username,password}`, callback | `{ok:true,token}`; token never logged |
| `getMonitorList` | callback, after subscribing | acknowledgement plus separate `monitorList` event |
| `getMonitor` | numeric ID, callback | `{ok:true,monitor}` complete record |
| `add` | complete new monitor, callback | `{ok:true,monitorID}` |
| `editMonitor` | full fetched record merged with owned fields | `{ok:true}` |
| `pauseMonitor` / `resumeMonitor` | ID, callback | `{ok:true}` |
| `getSettings` | callback | `{ok:true,data}` |
| `setSettings` | merged settings, current password, callback | `{ok:true}` |

Subscribe before requests, set finite connection/event/ack deadlines, disconnect
in finally, and reject any unsuccessful response. Do not dump request/response
objects on error. Retries reread state before uncertain writes. If `add` may
have succeeded, reread by ownership key before any retry. Sequential writes only.
Existing 2FA or a changed owner password must fail clearly, never disable auth.

Owned monitor fields include name, description marker, type, target, interval,
retry/timeout, expected status/content/JSON expression and active state. Merge
full records before edit to preserve unrelated user settings. Retention is
read/merge/write `keepDataPeriodDays=30`; never replace the whole settings map.

## Planned operator interfaces

`reconcile.js bootstrap`: init-only loopback server lifecycle and native owner
setup, graceful stop, no public setup exposure.

`reconcile.js once` / `watch`: validate committed catalog and reconcile owned
monitors once or at 300-second intervals. Exit nonzero on failure; sanitized
counts/hash only. `verify`: read-only acceptance summary of definitions and
observations. `acceptance`: bounded disposable localhost fixture that creates
one distinctly owned test monitor, observes healthy/down/recovered states, then
pauses it; never stops or edits an existing app.

`backup.py snapshot` / `verify`: private checked artifact creation and
isolated verification only. Production restore is separate reviewed GitOps
with writer fencing; this interface never overwrites production state.

These interfaces are implemented; pinned-image evidence is in validation-adapter.md
and validation-backup.md.

## Restore-verification execution contract (P1 repair)

Only `backup.py verify` may fence a freshly extracted disposable clone. It must
validate the fixed image/schema, checksum, original summary and empty destination
before clone-only SQL writes. In one transaction set monitor.active=0,
notification.active=0, notification.is_default=0 and maintenance.active=0;
remove monitor_notification bindings; set JSON-encoded checkUpdate=false,
nscd=false, cloudflaredTunnelToken="". Assert every postcondition after reopening
the database, including no null/nonzero activation flags, no bindings and one
correctly decoded setting per key. Unknown schema or duplicate keys fails closed.
User/authentication records, monitor IDs/definitions apart from active, original
archive and saved history must remain intact. Never apply this fence to the
production PVC or a production recovery target.

Spawn the same pinned server on loopback with an allowlisted child environment
and fixed argv; no NODE_OPTIONS, inherited Kuma/proxy/tunnel overrides or tunnel
argument. Verify `needSetup` returns false before `login`; use read-only native
list/detail/history operations only. Never bootstrap or resume the clone.
No setup, reconciliation, settings-write or notification-test API is permitted.
Stop within the bounded deadline and discard ephemeral data after verification.

NetworkPolicy is not proof of isolation on the current cluster. A dedicated
restore service account has no production backend grants or API token. The
version-bound fence must demonstrate no monitoring/notification/update/tunnel
activity in a network-enabled fixture, while authenticating and reading restored
identities/history successfully. Tests must fail if any fenced setting/activation
is missing or changed, if a process can start before the fence, or if an
inherited tunnel/configuration override reaches the child.


## Runtime identity compatibility

Run native bootstrap/main/reconciliation and backup/restore processes as OS
UID/GID 10001 with fsGroup 10001; native user/account IDs remain unchanged.
Tests against the exact pinned image must prove its executables/modules readable,
owned data writable, and projected config/credential readable without making the
container root or source backup mount writable. The restore child inherits the
parent's 10001 identity and the existing fixed environment/fencing contract.
Only the initial data mount ownership init may be root, assigning 10001:10001.
