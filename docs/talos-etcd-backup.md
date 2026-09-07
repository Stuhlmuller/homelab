# Talos Etcd Backup

`scripts/talos-etcd-backup.py` saves a consistent etcd snapshot from the
homelab control-plane node `10.1.0.199` to the operator's computer. Run it
before control-plane maintenance and whenever a fresh recovery point is needed.
It invokes only the authenticated Talos snapshot API; it does not change
cluster desired state or restore a database.

## Destination And Retention

Choose an existing, durable directory outside every Git checkout, owned by
your user with mode `0700`. Use a private encrypted disk or volume accessible
even when `acer` and Kubernetes are unavailable. Do not use `/tmp`, a public
sync folder, or cluster-hosted storage as the durable copy. Replace the example
paths below with operator-local paths; no environment inputs configure this
workflow.

Snapshots contain Kubernetes Secrets. Each completed backup has a `0700`
directory containing a `0600` snapshot and manifest. The script never uploads
backups, overwrites older backups, or prunes them. Interrupted processes may
leave a hidden `.partial-etcd-*` directory; it is not a completed backup.
Do not remove previous verified copies to make room for an unverified one.

This command provides a manual off-node recovery point. The separate
[macOS schedule](talos-etcd-schedule.md) installs reviewed code for approximately
daily backups, offline freshness checks and retention in a dedicated scheduled
child; it leaves manual copies untouched. Remote backup-age alert delivery,
an encrypted offsite copy and an isolated restore drill remain unimplemented.
A snapshot does not provide
control-plane high availability, back up PVC contents, or preserve the Talos
machine configuration and original cluster secret material needed after a
hardware loss; keep that existing private recovery material separately.

## Save A Backup

Prerequisites: Python 3.9 or newer on Linux/macOS, a Talos client matching the
cluster's minor version, the current private Talos client configuration, and
authenticated connectivity to `10.1.0.199`. The homelab's Homebrew client at
`/opt/homebrew/bin/talosctl` is `v1.11.3`, matching the current control plane;
the Nix development shell supplies `v1.13.2`. Use the explicit Homebrew path
for this cluster so entering a Nix shell cannot select a different client.
Other operators should substitute their matching client's absolute path.
`--talosctl` is required and must name an existing executable file by absolute
path. Missing, relative, or non-executable clients fail before any Talos call;
the command never selects a client through `PATH`.
The output metadata format was checked against Talos `v1.11.3`; a changed
format fails verification instead of publishing a backup without metadata.

```sh
mkdir -m 700 /path/to/private-etcd-backups
python3 scripts/talos-etcd-backup.py backup \
  --destination /path/to/private-etcd-backups \
  --talosconfig /path/to/current-private-talosconfig \
  --talosctl /opt/homebrew/bin/talosctl
```

The destination must already exist; `mkdir` is a one-time local setup step.
The script stages a uniquely named private directory, gives the snapshot
request five minutes, and requires Talos to report database hash, revision,
key count, and database size. It then compares the snapshot's embedded
SHA-256 checksum against the streamed payload and records the full file's
SHA-256 digest in `manifest.json`. Talos syncs the snapshot file; the script
syncs the manifest file and staged directory, publishes the completed
`etcd-<UTC-time>-<unique-suffix>` directory, then syncs the destination directory
before reporting success. The destination filesystem must support directory
`fsync`; the command fails if that durability check is unavailable.

Success prints the completed path, revision, key count, byte count, and
SHA-256 digest. It never prints database contents or Talos configuration.
A nonzero exit means the new backup did not complete all checks. A destination
directory sync failure after publication retains the newly named directory,
but its persistence is unconfirmed; retain it, investigate the filesystem,
and run a new backup before maintenance. Check authenticated Talos connectivity
and etcd health for client errors; check available disk space, permissions, and
the local client version for local verification errors. Retain earlier backups
and investigate checksum or metadata failures.

## Recheck A Saved Copy

Run the offline check after transferring a backup to another private volume:

```sh
python3 scripts/talos-etcd-backup.py verify \
  --directory /path/to/private-etcd-backups/etcd-<UTC-time>-<unique-suffix>
```

The command rechecks the embedded checksum and full-file digest against the
manifest without contacting Talos. It detects incomplete or altered snapshot
bytes; it is not a restore drill or proof that application records are sound.
Keep the manifest with its snapshot when making private copies. Any recovery
must follow the separately reviewed
[control-plane maintenance runbook](talos-control-plane-maintenance.md).

## Validation And Sources

Live validation on 2026-09-07 UTC used Talos `v1.11.3` to save a private
off-node snapshot. Embedded SHA-256 and full-file manifest checks passed.
This validates the backup command and copied bytes; it does not prove restore
readiness or an offsite copy.

The fixture check performs no live calls and uses only synthetic bytes:

```sh
python3 scripts/ci/talos-etcd-backup-check.py
```

It exercises repeated backups, private permissions, corruption and truncation,
changed copies, absent metadata, client failures, timeouts, directory sync
ordering and failures, explicit client selection, and destination rejection
before Talos access, including missing or invalid client arguments.
The fixture is not a real etcd database;
`talosctl` performs the actual database metadata check during a live backup.

- [Talos 1.11 backup guidance](https://docs.siderolabs.com/talos/v1.11/build-and-extend-talos/cluster-operations-and-maintenance/disaster-recovery#backup)
- [Talos v1.11.3 snapshot implementation](https://github.com/siderolabs/talos/blob/v1.11.3/cmd/talosctl/cmd/talos/etcd.go)
