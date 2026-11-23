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

## T035 high-UID correction — 2026-11-17

The complete frozen backup integration harness reran with **UID/GID 10001:10001**
for seed bootstrap and network-enabled verification and finished **exit 0**.

- Harness SHA256: `4a6e404648d724489a37e35b80791e2ac28131edf9e8ab720327243ee38d1fc2`.
- Unchanged backup implementation SHA256:
  `b3e3f585d2ae9062f1bed1e2ce8b1e6a70eef82d7272d274c085f574d0e12c42`.
- Exact image index remains
  `sha256:7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9`.

Runtime asserted both numeric identities, owned data/database and mode0700
owned scratch. Projected adapter, catalog, backup code and owner credential
were **root:10001, mode0440**, mounted read-only, and successfully read using
group permissions; a credential write failed EROFS. The test fixture's local
preparation/cleanup alone used root ownership capabilities on its disposable
directory. Runtime processes retained `--cap-drop ALL`, no-new-privileges and
read-only root. No production manifests or backup implementation changed in
this delegated correction.

The network-enabled positive control again emitted at least two probes and one
notification. Live native WAL backup through the separate read-only source
mount succeeded, including its direct-write EROFS assertion. The fenced clone
then produced **zero probes and zero notifications over42seconds**, exceeding
two configured20-second intervals. Native needSetup=false/login/details/paused
IDs/history, unchanged original archive digest and hostile-environment exclusion
all passed. Actual pinned updater/tunnel positive and negative counters passed.
ShellCheck, shell syntax and whitespace checks passed at the recorded hash.

Two initial fixture-setup attempts exposed host mktemp traversal and the
host-owned mode0600 test-script permissions before runtime proof. They were
corrected in disposable preparation; neither was accepted as a passing test.
The final complete run above is the evidence for UID10001 compatibility.
