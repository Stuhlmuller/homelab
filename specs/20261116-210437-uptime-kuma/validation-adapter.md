# Native adapter validation

Implementation T008/T009/T014, 2026-11-17. No production mutation or credentials.

- `node --test scripts/ci/uptime-kuma-test.js`: 16/16 pass. Covers first-owner
  authority, existing-owner/invalid-login preservation, duplicate preflight,
  uncertain successful add reread, resumable failure, settings/unowned record
  preservation, explicit pause, second-run no-op, retirement/auth failure,
  event-before-ack contract, native JSON fields and bounded form POST mapping.
- `bash scripts/ci/uptime-kuma-integration.sh`: exit 0 against the exact pinned
  2.5.11 image with UID1000, network none, read-only root and disposable data.
  Verified bundled modules, loopback startup, two successful bootstraps,
  wrong-password failure preserving owner, setup denial after owner exists,
  graceful server exit before main, actual add/edit/resume/pause, unchanged
  monitor ID, no duplicate and zero writes on second reconciliation, retention
  30 while preserving unrelated settings.
- Node syntax, shell syntax and whitespace checks pass.

Pinned-source findings encoded in implementation: the server awaits `sendInfo`
before installing socket handlers, so transport connect alone races the first
request; await native `info`. Native add also needs non-null `conditions` and
empty protocol-list defaults. Existing `active` changes require explicit
pause/resume; `editMonitor` does not apply active. JSON-query form POST uses
`httpBodyEncoding=form`, native body string and serialized JSON headers.

CLI defaults: `/config/monitors.json`, `/secret/admin-password`, `/app/data`,
`/status/reconcile.json`, `http://127.0.0.1:3001`. Arguments override these only
through committed command arrays. Modes bootstrap/once/watch/health implemented.
Each reconciliation holds loopback TCP3002, released after its status commit and
between watch cycles; once waits up to 120 seconds for contention. A real socket
contention/release test passes. Crash also releases the lease.
Health requires the latest attempt succeeded and last success within 660 seconds.

US2 observation and native JSON-query acceptance results are recorded below.
These disposable tests do not establish production coverage or persistent
backup recovery.

## Real CLI lease regression

Re-ran the pinned-image integration after the per-cycle lease repair. The
harness starts the real `watch` CLI, waits for its successful initial status,
then starts the real `once` CLI against the same instance and status file while
watch remains running. Once exits zero, advances lastSuccess, preserves catalog
hash and reports zero changes; watch stays live. Native API reads confirm the
single original monitor ID remains. Both processes shut down cleanly.
The complete integration exits zero; shell syntax and ShellCheck also pass.

## US2 native observation and acceptance evidence

Implemented `verify` (read-only definitions and three recent observations) and
`acceptance` (fixed loopback JSON endpoint and separately marked test monitor).
Verification distinguishes complete monitoring evidence (`ok`) from observed
application health (`healthy`), so a monitored outage is never reported healthy.
The native live heartbeat event has `monitorID` and no database ID; history rows
have database IDs. Collection merges distinct samples by actual timestamp.

The full timed pinned-image run proved real JSONata and native JSON-query
healthy/missing/multiple/false outcomes, 401 rejection, 302 rejection with no
redirect following, and unauthenticated administrative API denial. The actual
acceptance CLI collected three healthy observations at 60-second cadence, then
observed down in **120026 ms** and recovery in **59958 ms**. Its finally block
paused only the separately marked acceptance monitor and verified every other
monitor definition unchanged. No production target was stopped or modified.
SIGTERM/SIGINT during observation take the same pause/cleanup path.

Executed adapter SHA256:
`8f371518adf600918ad0cb197e07e8db7841f7b187142761e6e9d23c778ddd90`.
Timed harness SHA256:
`27905ea6363078ab0cb3e3d671059a697ef02ab0e7617504ec734d4845c6fa4d`.

The subsequent verification assertion correctly failed because the original
HTTP fixture used Kuma `/`, which redirects to `/dashboard`. This was a fixture
error, not an adapter false green. The harness fixture now uses `/dashboard`;
a focused `verify-only` mode rechecks actual native observations and both
verification interfaces without repeating the already-proven timed acceptance.
The adapter is unchanged. Focused final result is recorded below when complete.

Focused final result: `bash scripts/ci/uptime-kuma-integration.sh verify-only`
**exited 0**. It re-proved native JSON-query negative cases, unauthorized admin
access denial and once-with-watch behavior, then collected three actual healthy
observations and passed both read-only verification function and real verify
CLI. The focused watermark is captured before resuming the monitor, so its
immediate first heartbeat counts; a post-resume watermark had incorrectly
waited for a fourth heartbeat at the 180-second deadline.
Final harness SHA256:
`7a0a2e1d37fd7b3ea6ef3c7673f92af6df4b1d67b55d9754034f2f2db6fa825f`.
Adapter remains the exact timed-run hash above. Unit suite **16/16 pass**;
Node syntax, bash syntax, ShellCheck and diff whitespace checks pass.
