# Etcd Scheduler Diagnostics

The [macOS etcd scheduler](../../talos-etcd-schedule.md) writes UTC observation
times on successful runs, age-gated skips, offline status checks, and failures.
Status timestamps use the same instant as the reported backup age and freshness.
Failed snapshot commands report `talos-etcd-snapshot`, an exit code or timeout
duration, and that prior backups were retained. Failed status and uninstall
commands identify the fixed launchd `print` or `bootout` operation. Arguments and
captured client output are not forwarded to the logs.

The September 12 read-only audit found five successful scheduled snapshots from
September 7 through 11; all five passed fresh offline checksum verification.
The longest completion interval was 26 hours 54 minutes, below the 36-hour stale
threshold. Two generic errors were followed by automatic successful retries,
but their original causes could not be recovered because the installed release
had discarded their timestamps, exit codes, and timeout classification.

The diagnostic update changes log evidence only. It does not change backup
cadence, retry behavior, freshness, retention, or installer rollback. Install
the reviewed merged revision using the existing runbook, then require loaded
status and a successful age-gated run; the earlier error lines stay unchanged.
This remains local observation, not remote alert delivery or offsite freshness.

Related: [[architecture/storage-and-state]] and
[[runbooks/talos-control-plane-maintenance]].
