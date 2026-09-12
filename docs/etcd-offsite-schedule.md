# Scheduled Etcd Offsite Attempts On macOS

[`scripts/etcd-offsite-schedule.py`](../scripts/etcd-offsite-schedule.py) gives the
[existing local snapshot schedule](talos-etcd-schedule.md) an independent offsite
publisher. The [committed policy](../scripts/config/etcd-offsite-schedule.json)
attempts publication hourly at minute 27 and on login/load. It considers a
verified offsite source stale at 36 hours. This code has synthetic validation;
it has not been installed or exercised against AWS as a scheduled service.

## Publication And Failure Semantics

The scheduler reads the local schedule's confirmed newest snapshot under its
shared lock, verifies it, and retains a private copy of both snapshot and
manifest. It releases that lock before any AWS call. Its own runtime lock
serializes offsite attempts and installation without coupling AWS availability
to the local snapshot cadence, success receipt, or retention policy.

Each snapshot SHA has a private directory under `<runtime>/attempts/<SHA>`.
The [existing publisher](etcd-offsite-publication.md) records a unique remote
prefix and exact object versions in `publication.json`. `attempt-state.json`
durably selects that pair before networking. An interrupted attempt resumes
that same prefix before considering newer local copies, even after local
retention removes its original source. The snapshot uploads first, the manifest
last. Success requires both exact versions to be downloaded and their full and
embedded checksums verified. Failed or partial copies and receipts remain on
disk; ambiguous or damaged receipts stop publication for operator inspection.
Receipt-less interrupted copies are preserved and a new private copy can be
prepared because networking cannot precede a publication receipt.

A verified snapshot SHA is skipped on later checks, without another AWS call.
The status age always comes from the **manifest actually published with that
SHA**. A newer local manifest with identical snapshot bytes cannot refresh the
old remote pair's capture time. Retry times, successful retrieval times and
hourly check times also cannot refresh source age. A stale identical snapshot
therefore remains stale until a different source is successfully published.
The scheduler does not replay all historical snapshots or automatically delete
local attempts or S3 objects. Allow disk space for retained working copies,
retrieval copies and failed partial downloads; the bucket's existing lifecycle
policy remains separately owned.

## Install A Reviewed Main Revision

Prerequisites: the existing local schedule installed on durable private disk,
a logged-in macOS GUI user, Python 3.9+, and an existing named AWS CLI/SSO profile
for the committed account. The profile must already have access to the
[dedicated bucket](etcd-offsite-storage.md). This installer creates no identity,
credentials or IAM policy and does not log in. Existing renewable SSO sessions
can refresh only within their configured session lifetime; eventual expiry
requires the operator's ordinary AWS SSO login, as described in the
[AWS SSO credential guidance](https://docs.aws.amazon.com/sdkref/latest/guide/feature-sso-credentials.html).
This cannot provide indefinite
unattended publication. Mac shutdown, logout and sleep also delay checks.

After review and merge, use a clean checkout of the full merged commit. Replace
all placeholders; the runtime must be a separate private durable directory
outside Git, temporary storage, the local runtime and scheduled snapshots.

```sh
git fetch origin main
git switch --detach <reviewed-main-SHA>
/absolute/path/to/python3 scripts/etcd-offsite-schedule.py install \
  --revision <reviewed-main-SHA> \
  --runtime-directory /path/to/private-offsite-runtime \
  --local-runtime-directory /path/to/private-etcd-runtime \
  --python /absolute/path/to/python3 \
  --aws-cli /absolute/path/to/aws \
  --profile <existing-profile-name>
```

The installer verifies exact source bytes and main ancestry, copies the scripts
and committed policy/destination into `releases/<SHA>` while preserving their
relative paths, and records their hashes and explicit local references. It
compiles the copied code and validates the plist before loading the separate
`org.homelab.etcd-offsite` LaunchAgent. Runtime source drift stops execution.
It uses the local scheduler's existing service handoff/rollback helper, under
the **offsite** lock. Failed bootstrap restores the previous settings/plist and
loaded state; private `.install-rollback-*` records remain available. Installation
starts an offsite attempt through `RunAtLoad`; installation success alone is
not publication success. It never changes the local snapshot LaunchAgent.

## Verify, Recover And Stop

```sh
/absolute/path/to/python3 /path/to/private-offsite-runtime/releases/<SHA>/scripts/etcd-offsite-schedule.py status \
  --runtime-directory /path/to/private-offsite-runtime
```

Offline status verifies the retained publication and exact-version retrieval
evidence and reports `source_created_at`, `age_hours`,
`version_retrieval_verified_at`, any `pending_sha`, the last attempt's outcome,
and whether launchd is loaded. `fresh` exits 0 unless the last attempt failed;
`missing`, `stale`, invalid evidence, a failed last attempt or a busy offsite
lock returns nonzero. A failed newer attempt preserves the previous verified
source and its age. A fresh saved copy can exist while the agent is unloaded;
check both fields. This command performs no remote reads and cannot confirm
that a previously retrieved remote version is still available.

Inspect private `schedule.log`, `schedule-error.log`, `attempt-state.json` and
per-source `attempt.json`. Failures record UTC times, the bounded operation and
whether it timed out; raw AWS arguments/output are not logged. Check the existing
SSO session, explicit executable paths, disk space and local backup status.
The next hourly check retries the pending pair. Persistent damaged evidence
needs operator investigation; retain all recovery data. No automated remote
alert delivery has been implemented or verified. These local logs and exit
codes do not notify anyone when the Mac is unavailable or SSO expires.

To stop attempts, use the installed script. It refuses to interrupt an active
offsite attempt, unloads only its own LaunchAgent, removes that plist, and
preserves all runtime records, copies and the local snapshot schedule.
Repeated uninstall succeeds when the agent is already absent.

```sh
/absolute/path/to/python3 /path/to/private-offsite-runtime/releases/<SHA>/scripts/etcd-offsite-schedule.py uninstall \
  --runtime-directory /path/to/private-offsite-runtime
```

For update or rollback, run `install` from another reviewed main revision with
the same runtime and local source runtime. To change the source runtime,
uninstall and choose a fresh offsite runtime. The manual publisher's existing
CLI and receipt-only retrieval remain available for operator recovery.

## Validation

```sh
python3 scripts/ci/etcd-offsite-backup-check.py
python3 scripts/ci/etcd-offsite-schedule-check.py
```

Fixtures cover lost upload responses, exact-version retrieval failures,
interrupted preparation/success records, source deletion before resume, SHA
and source-age deduplication, source/offsite lock separation, session failures,
source-release validation and service rollback. All AWS/launchd calls use mocks
and synthetic snapshots. These tests do not prove real recurring publication,
SSO renewal, remote alerts, control-plane restoration, or PVC recovery.
