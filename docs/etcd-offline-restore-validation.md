# Offline Etcd Restore Validation

`scripts/etcd-offline-restore-check.py` checks that a verified Talos backup can
be parsed and restored into a new local etcd data directory. It runs only
`etcdutl version`, `snapshot status`, and `snapshot restore`. It never extracts
or starts the etcd server, opens a listener, contacts Talos/Kubernetes, or
changes the source backup.

This closes the database parsing and offline restoration check. It does not
test control-plane startup, Kubernetes watches, application consistency, PVC
recovery, or recovery after hardware loss. Those require the separately
reviewed [control-plane runbook](talos-control-plane-maintenance.md) and
private Talos recovery material. The output uses disposable loopback member
metadata; do not start it as a replacement control plane.

## Prepare The Local Tool Archive

Use Python 3.9 or newer on macOS or Linux, on ARM64 or AMD64. The helper pins
etcd `3.6.5`, matching the homelab's current etcd version. It selects the host
platform, checks the complete local release archive against its committed
SHA-256, and extracts only `etcdutl`. No tool is selected through `PATH`, no
environment variable configures the operation, and the validator downloads
nothing. A future etcd version needs a reviewed version/checksum update.

Download the matching archive from the
[official 3.6.5 release](https://github.com/etcd-io/etcd/releases/tag/v3.6.5)
before entering an offline environment. For an Apple Silicon operator host:

```sh
mkdir -m 700 /path/to/private-etcd-tools
curl --fail --location --silent --show-error --max-time 60 \
  https://github.com/etcd-io/etcd/releases/download/v3.6.5/etcd-v3.6.5-darwin-arm64.zip \
  --output /path/to/private-etcd-tools/etcd-v3.6.5-darwin-arm64.zip
```

For Intel macOS, use `darwin-amd64.zip`. Linux uses `linux-amd64.tar.gz` or
`linux-arm64.tar.gz`. The four pinned digests come from the release's
[SHA256SUMS](https://github.com/etcd-io/etcd/releases/download/v3.6.5/SHA256SUMS)
and were compared with GitHub's release asset digests. Native macOS ARM64
version/help execution was checked; other platform execution remains unverified.
The helper also checks the extracted executable's version and records both
archive and executable SHA-256 in its receipt.

## Validate A Saved Backup

First create or select a completed backup from
[the existing backup command](talos-etcd-backup.md). Keep its `etcd.snapshot`
and `manifest.json` together. Choose an existing private mode-`0700` output
directory outside every Git checkout and outside the source backup directory.
Use durable private storage for retained evidence; `/tmp` is unsuitable.
Allow space for a working snapshot, the restored database/WAL, and the tool.

```sh
mkdir -m 700 /path/to/private-etcd-restore-checks
python3 scripts/etcd-offline-restore-check.py \
  --backup-directory /path/to/private-etcd-backups/etcd-<UTC-time>-<unique-suffix> \
  --destination /path/to/private-etcd-restore-checks \
  --etcd-archive /path/to/private-etcd-tools/etcd-v3.6.5-darwin-arm64.zip
```

The command reuses the backup verifier for the embedded SHA-256 and manifest
digest. It verifies a separate working copy, requires parsed hash/revision/key
count/size to match the backup manifest, then runs checksum-enabled restore
into a new directory. It never accepts `--skip-hash-check`. A second status
check must retain the original revision and key count. Membership metadata
changes during restoration, so restored database hash and size may differ.
The source backup and working snapshot are checked again before success.

Each subprocess has a five-minute deadline. Successful output is published
as `restore-<UTC-time>-<unique-suffix>` with private directories and files.
`receipt.json` contains fixed database metadata, source digests, and tool
provenance. It contains no key names or values. Client diagnostics are not
printed or saved because parsing errors can include database contents.

Publication syncs the receipt and the invocation/output directory entries.
Persistence of the nested database and WAL relies on `etcdutl`'s own writes;
the helper does not recursively sync that tree or test it across a power loss.
The receipt proves completed parsing and restoration at validation time, not
independent durability of every restored file.

A nonzero exit means the checks did not all complete. Retain the source backup
and check local permissions, free space, archive version/checksum, and snapshot
integrity. Failed runs remove only their unpublished workspace; earlier outputs
are untouched. A forced interruption can leave a private `.partial-restore-*`
directory, which is not a completed check. A destination sync failure after
publication retains the new output but reports failure. Successful restored
data contains Kubernetes Secrets and is retained until the operator explicitly
disposes of it; this command is not a retention policy or an offsite backup.

## Validation Scope

Run the behavioral fixtures without a real tool, database, or cluster:

```sh
python3 scripts/ci/etcd-offline-restore-check-test.py
```

They cover independent repeated outputs, exact offline commands, archive and
snapshot corruption, private destinations, mismatched versions/metadata,
source changes, client failures/timeouts, diagnostic suppression, and failed
publication. Synthetic fixture success is not evidence of a real restore.

On 2026-09-07, the merged helper from
[PR #1007](https://github.com/Stuhlmuller/homelab/pull/1007) completed one real
offline restore with the pinned etcd `3.6.5` macOS ARM64 tool in 2.68 seconds.
The post-upgrade snapshot parsed and restored with revision `37730997` and
`2919` MVCC keys preserved. Source snapshot and manifest SHA-256 values were
unchanged; the tool provenance, fixed metadata, and receipt are retained
privately outside Git. No etcd server or network listener started. This closes
the parsing/restoration gap for that snapshot; control-plane startup,
watch recovery, application/PVC recovery, and restored-tree power-loss
durability remain untested.

The upstream [etcd 3.6 recovery guide](https://etcd.io/docs/v3.6/op-guide/recovery/)
documents snapshot status, restore-time integrity validation, and changed
member identities. It separately recommends revision bump/compaction for
Kubernetes disaster recovery; this offline database check preserves revisions
and does not implement that live recovery procedure. The exact
[3.6.5 snapshot implementation](https://github.com/etcd-io/etcd/blob/v3.6.5/etcdutl/snapshot/v3_snapshot.go)
performs database integrity and metadata parsing used by this check.
