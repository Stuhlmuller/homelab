# Scheduled Talos Etcd Backups On macOS

`scripts/talos-etcd-schedule.py` runs the existing
[verified snapshot command](talos-etcd-backup.md) on the operator's Mac through
a user LaunchAgent. It contacts only the authenticated Talos snapshot API at
the repository's LAN endpoint. It does not change cluster configuration.

## Cadence And Storage

The committed policy in
[`scripts/config/talos-etcd-backup-schedule.json`](../scripts/config/talos-etcd-backup-schedule.json)
owns these choices:

| Setting | Behavior |
| --- | --- |
| Check | Hourly at minute 17, plus immediately when the agent loads |
| Snapshot | When the latest verified scheduled success is at least 24 hours old |
| Freshness | `status` fails when the selected snapshot is at least 36 hours old |
| Retention | Remove scheduled copies older than 28 days, preserving at least seven valid copies |
| Client | Explicit executable matching Talos `v1.11.3` |

This gives approximately daily backups: about 24–25 hours between successes on
an awake, connected Mac. `StartCalendarInterval` coalesces missed sleep events
into one invocation on wake. The age gate makes one current backup instead of
replaying a backlog. When the Mac is off or its user is logged out, this user
agent cannot run. `RunAtLoad` checks on the next login; failed LAN access retries
at the next hourly invocation. It is not an always-on scheduler.

The installer reserves `<backup-root>/scheduled` for this schedule. Existing
manual backups in the parent or sibling directories remain untouched. Use a
private durable disk outside Git and temporary directories, with sufficient
free space for retained copies and one new snapshot. Neither this schedule nor
its status command creates an offsite copy, backs up PVC data or Talos recovery
material, proves a restore, or delivers remote alerts. Local freshness status
still requires an operator or separately reviewed monitoring integration.

## Install The Reviewed Main Revision

Requirements: a logged-in macOS GUI user, Python 3.9+, the existing private
Talos client configuration, and authenticated LAN connectivity. The current
homelab client is `/opt/homebrew/bin/talosctl`; the Nix shell's client is a
different minor version. Installation checks the exact client version and
resolves Python/client symlinks to absolute executable paths. A later package
cleanup that removes either executable requires reinstalling with a compatible
explicit path. No credentials are copied into the runtime or repository.

After review and merge, fetch main and use a checkout of the full merged
commit. Replace all example paths and `<reviewed-main-SHA>` below; these are
operator-local references, not environment inputs. The backup root must
already exist with mode `0700`; the installer creates the private runtime and
its scheduled child. Never point the root at `/tmp` or a worktree.

```sh
git fetch origin main
git switch --detach <reviewed-main-SHA>
mkdir -m 700 /path/to/private-etcd-backups
/absolute/path/to/python3 scripts/talos-etcd-schedule.py install \
  --revision <reviewed-main-SHA> \
  --runtime-directory /path/to/private-etcd-runtime \
  --backup-root /path/to/private-etcd-backups \
  --talosconfig /path/to/current-private-talosconfig \
  --talosctl /opt/homebrew/bin/talosctl \
  --python /absolute/path/to/python3
```

`mkdir` is a one-time setup step; skip it when the private root already exists.
The installer checks HEAD, main ancestry, and exact tracked source bytes. It
rejects local edits to either script or the policy. It copies those three
reviewed files into `<runtime>/releases/<SHA>`, records commit identity, hashes
and explicit local references in `installation.json`, compiles the copied
Python sources, and validates the rendered plist with `plutil` before loading
`~/Library/LaunchAgents/org.homelab.etcd-backup.plist`. The loaded program uses
only the durable runtime, with no checkout or temporary-path dependency.

Before replacing a service, installation saves the previous settings, plist and
loaded state in a private `.install-rollback-*` directory under the runtime.
It holds the backup lock through configuration writes and `launchctl bootstrap`.
If the handoff fails, it stops any partly loaded new service before restoring
the previous files and loaded state. A first-install failure restores absence.
Rollback failure is an explicit error with the saved configuration path; it
never reports a working installation. Those small rollback records are retained.

Installation's `RunAtLoad` starts an age-gated attempt. Successful installation
is not proof of a successful snapshot. Use the durable script path printed by
the installer to check the result after that attempt finishes:

```sh
/absolute/path/to/python3 /path/to/private-etcd-runtime/releases/<SHA>/talos-etcd-schedule.py status \
  --runtime-directory /path/to/private-etcd-runtime
```

`status` is offline: it rechecks the selected newest snapshot's embedded and
manifest checksums, its completed-success receipt, and age. It also reports
whether the LaunchAgent is loaded. `fresh` exits 0; `missing`, `unconfirmed`,
`stale`, invalid timestamps, checksum failures or a running backup return
nonzero. An unloaded agent can still have a fresh saved snapshot; check both
fields. The command does not silently choose an older copy when the newest is
corrupt. Runtime source drift also fails the command before backup execution.

## Failure, Retention And Uninstall

Every invocation uses the same file lock in the scheduled child. The committed
LaunchAgent invokes `run --launchd`, which waits at most 60 seconds for the
installer to release the lock; its `bootstrap` command has a 30-second timeout.
This allows the initial child to finish the age-gated attempt after handoff
instead of exiting while installation still holds the lock. A wait timeout
changes no backups and retries at the next calendar invocation. Operator runs,
status, installation and uninstallation remain nonblocking and stop before
disrupting a running backup. Client failures and timeouts preserve previous copies and the
last success receipt. A published directory without a matching success receipt
is `unconfirmed`, so it cannot suppress the next attempt. Check authenticated
Talos reachability, client paths, disk space and private permissions if a run
fails. A failed receipt sync restores the previous receipt (or removes the
unconfirmed marker if restoration fails), so the next check retries. Persistent
filesystem failures still need operator attention. A corrupt snapshot or
malformed success receipt keeps offline status nonzero, but the writer preserves
older artifacts and creates a fresh verified copy with retention skipped. Do
not treat damaged copies as valid recovery points.

Only after a new snapshot and its durable receipt succeed does retention
verify every completed candidate before deleting any. It preserves at least
seven valid copies, every copy at most 28 days old, manual siblings, interrupted
`.partial-*` directories and unknown files. Verification or receipt failure
prevents pruning. Unexpected files inside a completed directory also stop
retention. A retention failure leaves a new valid backup alongside older
copies; the run reports `action: backed-up` with `retention_warning`, separating
successful protection from blocked cleanup. Candidate verification finishes
before the first deletion; a later filesystem deletion failure can leave some
eligible old copies already removed. The seven protected copies are never
deletion candidates.

Private `schedule.log` and `schedule-error.log` under the runtime contain local
results and failures. They contain no database values or Talos configuration.
Logs are not remote notifications. Check status again after the next hourly
retry; sleep, shutdown and LAN outages can exceed the freshness threshold.

To stop recurrence, use the installed command. It refuses to interrupt an
active backup, unloads only this LaunchAgent and removes its plist. Repeated
uninstallation succeeds when already absent; every backup and the durable
runtime remain available for offline verification.

```sh
/absolute/path/to/python3 /path/to/private-etcd-runtime/releases/<SHA>/talos-etcd-schedule.py uninstall \
  --runtime-directory /path/to/private-etcd-runtime
```

For an update or rollback, run `install` from another reviewed main commit
containing these scripts with the same runtime and backup root. The installer
replaces the loaded program only while the backup lock is free. To change the
backup root or committed launchd label, uninstall the old schedule and choose a
fresh runtime; uninstall preserves the old runtime's installation record.
Updates verify the prior installed release and reject a different label before
reconfiguring either service, keeping the old schedule intact. Never use
unreviewed local policy edits as a workaround; change the committed policy and
reinstall reviewed code.

## Validation And Sources

```sh
python3 scripts/ci/talos-etcd-backup-check.py
python3 scripts/ci/talos-etcd-schedule-check.py
```

These checks use synthetic snapshots and mocked local services. They exercise
age gating, offline status, missing/corrupt data, network and timeout failures,
publication failure, sleep catchup semantics, lock contention, retention,
manual-copy preservation, exact source validation, and installation/removal.
Handoff fixtures inject failures after settings/plist writes and partial
bootstrap, verify rollback and explicit rollback failure, preserve an active
backup, and run a waiting worker through its successful initial post-lock attempt.
Label-change fixtures preserve the old service and settings and require a fresh
runtime after uninstall.
They do not execute a real LaunchAgent, prove wake behavior on this Mac or
validate real etcd restores. Installation and the first scheduled snapshot
still require private live receipts.

- [Apple: scheduling timed jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html)
- [Apple launchd.plist manual: calendar intervals, wake coalescing and RunAtLoad](https://github.com/apple-oss-distributions/launchd/blob/main/man/launchd.plist.5)
