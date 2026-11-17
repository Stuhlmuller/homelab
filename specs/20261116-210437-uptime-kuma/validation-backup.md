# Backup and fenced restore evidence

2026-11-17: T018–T021 and T029–T031 implementation. No live mutation,
production credential read, CNI change or public-service probe was performed.

## Final local checks

- `python3 scripts/ci/uptime-kuma-backup-test.py`: **22/22 pass**. Original
  online WAL/concurrent commits, partial catalog/history refusal, failed atomic
  publication preserving previous bundles, secret exclusion, checksum/corrupt/
  incomplete archives, traversal/absolute/symlink/duplicate rejection, existing
  destination preservation and 14-bundle retention remain covered.
- Fence tests reject unknown schema, duplicate keys, every nonzero/null monitor,
  notification/default and maintenance flag, remaining bindings, every missing/
  wrong-type/duplicate fenced setting, altered private identity/history and
  corruption at the final spawn boundary. Failed fences never spawn native Kuma.
- A 50,001-row history fixture with 512-byte payloads proves incremental
  evidence hashing stays below 2MiB Python peak allocation. SQL orders by stable
  primary key (all retained columns as fallback); no history list is materialized.
- Dedicated restore ServiceAccount/Job test verifies no token, no RBAC or
  production-backend principal grants, no production PVC, exact verify command,
  read-only backups/config/credential and writable ephemeral clone only.
- Cleanup tests prove success and fence/native failure remove only the newly
  restored clone; an existing nonempty destination is rejected and preserved.
- Pinned ShellCheck, Python/shell syntax and whitespace checks pass. Four
  backup/restore/identity manifests pass 244/244 policy assertions.

## Actual pinned network-enabled test

`bash scripts/ci/uptime-kuma-backup-integration.sh` completed **exit 0** against
exact Kuma2.5.11 index7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9,
UID1000, dropped capabilities and read-only container root. Initial unconfigured
seed bootstrap used network-none, preventing default update calls; the actual
positive/fenced test used network-enabled Docker bridge and reachable interface
IP probe/webhook sinks. No general network-isolation claim is made.

The unfenced native fixture first observed a healthy heartbeat, then the sink
returned503. The native 20-second monitor emitted **at least two probes and at
least one webhook**, proving both sinks and actual monitor/notification paths.
Snapshot then read the live WAL through a separate read-only source bind mount;
a direct source write failed EROFS. Catalog markers and nonempty history passed.

The independently restored, transactionally fenced clone ran for **42seconds,
at least two configured20-second monitor intervals**, with **zero probe requests
and zero notification requests**. Native needSetup=false, owner login, list,
monitor details/paused flags, original numeric IDs and historical heartbeat
reads all passed. Private SQL identity/history evidence also remained unchanged.
Original archive+manifest byte digest before/after matched. Poisoned inherited
NODE_OPTIONS/proxy/Kuma/tunnel values did not reach native subprocesses.

The test executed actual pinned `server/check-version.js` and cloudflared socket
handler source with strict dependency mocks and observable call/launch counters:
updater booleanfalse→0 calls, true/stringfalse→2 calls (initial+periodic);
tunnel empty stored token/no override→0 launches, stored token→1 and explicit
override→1. All counters ran without public-service contact. These tests would
fail if either pinned guard were skipped, inverted or interpreted as a string.

The first test fixture failed to produce its required positive control under
inherited transport defaults; it was not accepted as proof. The successful
fixture starts its positive native process with the same minimal environment
and establishes both native healthy/down transitions before testing the fence.
The subsequent cleanup-only finally change passed focused ownership/preservation
unit tests; it does not alter the verified startup/fence/network behavior.

## Runtime boundary and remaining acceptance

Restore validates exact full SQLite column-shape SHA from the pinned image and
unique settings, retains private original evidence, then mutates only its newly
extracted clone in one transaction. It zeros activation/default flags, removes
bindings and stores JSON checkUpdate=false, nscd=false and empty tunnel token.
An independent reopened connection checks all postconditions and unchanged
permitted evidence, again immediately before spawn. Child argv is loopback-only;
child environment allows only fixed PATH/HOME/TMPDIR. No setup, reconciliation,
resume, notification-test or settings-write API runs in the verifier.

Snapshot explicitly closes connections and converts only its isolated backup
DB to DELETE journal; source remains mode=ro and no WAL/SHM is archived. Initial
backup waits600seconds for catalog/history, nightly04:20 America/Los_Angeles
forbids overlap and retains14 bundles. Jobs have900-second deadlines and bounded
5Gi scratch; restore has no production database mount and uses its own identity.
The declared deny-all policy is defense in depth because current Flannel does
not provide general enforcement. Primary assurance is the tested version-bound
application execution fence. Schema/image changes require renewed validation.

Scheduled execution, NAS capacity, first deployed backup and actual deployed
fenced restore remain live acceptance work. No production recovery was attempted.
